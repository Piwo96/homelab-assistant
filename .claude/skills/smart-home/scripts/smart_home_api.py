#!/usr/bin/env python3
"""Smart Home — domain-optimierte CLI über Home Assistant.

Dieses Script übersetzt deutsche Alltagskommandos in HA-Service-Calls und
versteckt Service-Namen / entity_id-Konventionen vor dem LLM-Agenten. Es nutzt
intern den `homeassistant` Skill als rohe HA-API (importiert die
HomeAssistantAPI-Klasse aus dem Schwester-Skill).

Erweiterungs-Modell:
- v1 (jetzt): Lichter — on/off/set/status mit `--where`-Auflösung (Etage,
  Area, Group, Friendly-Name).
- v2 (folgt): Rollos / Klima / Szenen / Bereich-aus / Etage-aus / Haus-modus.

Konventionen:
- Jede Subcommand-Funktion gibt ein strukturiertes JSON-Objekt zurück
  ({ok, action, entities, ...}) statt HA's leerem [].
- `--where` matched in dieser Reihenfolge: HA-Group → Etage-Prefix →
  HA-Area → Friendly-Name-Fragment.
- Sicherheits-Cap: write-Aktionen mit >10 Treffern werden ohne explizites
  --confirm abgebrochen.
"""

import argparse
import json
import os
import sys
from typing import Any

# Pfad zum homeassistant Skill (Schwester-Verzeichnis) damit wir die rohe
# HA-API-Klasse importieren können ohne sie zu duplizieren.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HA_SCRIPTS = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "homeassistant", "scripts"))
sys.path.insert(0, _HA_SCRIPTS)
sys.path.insert(0, _THIS_DIR)  # for skill_helpers shared by both skills

from homeassistant_api import HomeAssistantAPI  # type: ignore  # noqa: E402


FLOOR_LABELS = {
    "kg": ("KG", "Kellergeschoss"),
    "eg": ("EG", "Erdgeschoss"),
    "og": ("OG", "Obergeschoss"),
    "dg": ("DG", "Dachgeschoss"),
    "aussen": ("Außen", "Außen"),
}
# Alle Aliasse die der User für eine Etage benutzen kann → Floor-Key.
FLOOR_ALIASES: dict[str, str] = {}
for k, (short, long) in FLOOR_LABELS.items():
    FLOOR_ALIASES[k] = k
    FLOOR_ALIASES[short.lower()] = k
    FLOOR_ALIASES[long.lower()] = k
FLOOR_ALIASES.update({
    "keller": "kg", "kellergeschoß": "kg",
    "erdgeschoß": "eg",
    "obergeschoß": "og",
    "dachgeschoß": "dg",
    "garten": "aussen", "terrasse": "aussen",
})


# --------------------------------------------------------------------------
# Where-Auflösung: User-String → Liste von entity_ids
# --------------------------------------------------------------------------

def _floor_of(entity_id: str) -> str | None:
    """Etage aus entity_id-Prefix ableiten (`light.og_kind_1` → 'og')."""
    local = entity_id.split(".", 1)[-1]
    first = local.split("_", 1)[0]
    return first if first in FLOOR_LABELS else None


def _norm(s: str) -> str:
    return s.strip().lower()


def resolve_where(api: HomeAssistantAPI, where: str, domain: str) -> dict[str, Any]:
    """Resolve a user-supplied `--where` string into a concrete target.

    Returns one of:
      {kind: 'group', group_id, entities, label}   — when an HA-group entity matches
      {kind: 'floor', floor, entities, label}      — when --where names an Etage
      {kind: 'area', area_id, entities, label}     — when --where names an HA-Area
      {kind: 'name', entities, label}              — friendly-name substring fallback
      {kind: 'none', entities: []}                 — nothing found
    """
    needle = _norm(where)
    if not needle:
        return {"kind": "none", "entities": [], "label": where}

    states = api.get_states()

    # 1. HA-Group: explicit group entity_id reference OR a group whose name
    #    matches AND has members in the requested domain.
    for s in states:
        if not s["entity_id"].startswith("group."):
            continue
        gid = s["entity_id"]
        members = s["attributes"].get("entity_id") or []
        fn = (s["attributes"].get("friendly_name") or "").lower()
        if needle == gid.lower() or needle == fn or needle in fn:
            domain_members = [m for m in members if isinstance(m, str) and m.startswith(f"{domain}.")]
            if domain_members:
                return {"kind": "group", "group_id": gid, "entities": domain_members,
                        "label": s["attributes"].get("friendly_name") or gid}

    # 2. Etage: floor alias.
    floor_key = FLOOR_ALIASES.get(needle)
    if floor_key:
        ents = [s["entity_id"] for s in states
                if s["entity_id"].startswith(f"{domain}.")
                and _floor_of(s["entity_id"]) == floor_key]
        if ents:
            short, _ = FLOOR_LABELS[floor_key]
            return {"kind": "floor", "floor": floor_key, "entities": ents, "label": short}

    # 3. HA-Area: display name or area_id. Use template helper for area_entities.
    areas_raw = api.render_template("{{ areas() | sort | join(',') }}").strip()
    area_ids = [a.strip() for a in areas_raw.split(",") if a.strip()]
    for aid in area_ids:
        try:
            name = api.render_template(f"{{{{ area_name('{aid}') }}}}").strip().lower()
        except Exception:
            name = aid
        if needle == aid.lower() or needle == name or needle in name:
            try:
                area_ents = api.entities_in_area(aid)
                ents = [e for e in area_ents if e.startswith(f"{domain}.")]
                if ents:
                    return {"kind": "area", "area_id": aid, "entities": ents,
                            "label": name.title() if name else aid}
            except Exception:
                continue

    # 4. Friendly-name substring fallback.
    matches: list[str] = []
    for s in states:
        if not s["entity_id"].startswith(f"{domain}."):
            continue
        fn = (s["attributes"].get("friendly_name") or "").lower()
        if needle in fn or needle in s["entity_id"]:
            matches.append(s["entity_id"])
    if matches:
        return {"kind": "name", "entities": matches, "label": where}

    return {"kind": "none", "entities": [], "label": where}


# --------------------------------------------------------------------------
# Lights commands
# --------------------------------------------------------------------------

MASS_ACTION_CAP = 10  # safety: refuse writes that touch more than this many entities


def _check_cap(target: dict[str, Any], confirm: bool) -> dict[str, Any] | None:
    """Return an error result if the target is too broad and confirm wasn't set."""
    if not confirm and len(target["entities"]) > MASS_ACTION_CAP:
        return {
            "ok": False,
            "error": f"Zu viele Treffer ({len(target['entities'])}) — bitte enger eingrenzen oder bestätigen.",
            "match_kind": target["kind"],
            "label": target.get("label"),
            "entities_preview": target["entities"][:5],
            "total": len(target["entities"]),
        }
    return None


def lights_on(api: HomeAssistantAPI, where: str, brightness: int | None, confirm: bool) -> dict[str, Any]:
    target = resolve_where(api, where, "light")
    if not target["entities"]:
        return {"ok": False, "error": f"Keine Lichter gefunden für '{where}'", "match_kind": "none"}
    cap = _check_cap(target, confirm)
    if cap:
        return cap
    affected: list[str] = []
    for eid in target["entities"]:
        data: dict[str, Any] = {"entity_id": eid}
        if brightness is not None:
            data["brightness_pct"] = max(0, min(100, brightness))
        api.call_service("light", "turn_on", data)
        affected.append(eid)
    return {
        "ok": True,
        "action": "lights-on",
        "match_kind": target["kind"],
        "label": target.get("label"),
        "entities_affected": affected,
        **({"brightness_pct": brightness} if brightness is not None else {}),
    }


def lights_off(api: HomeAssistantAPI, where: str, confirm: bool) -> dict[str, Any]:
    target = resolve_where(api, where, "light")
    if not target["entities"]:
        return {"ok": False, "error": f"Keine Lichter gefunden für '{where}'", "match_kind": "none"}
    cap = _check_cap(target, confirm)
    if cap:
        return cap
    affected: list[str] = []
    for eid in target["entities"]:
        api.call_service("light", "turn_off", {"entity_id": eid})
        affected.append(eid)
    return {
        "ok": True,
        "action": "lights-off",
        "match_kind": target["kind"],
        "label": target.get("label"),
        "entities_affected": affected,
    }


def lights_set(api: HomeAssistantAPI, where: str, brightness: int, confirm: bool) -> dict[str, Any]:
    return lights_on(api, where, brightness, confirm)


def lights_status(api: HomeAssistantAPI, where: str | None, state_filter: str | None) -> dict[str, Any]:
    if where:
        target = resolve_where(api, where, "light")
        if not target["entities"]:
            return {"ok": False, "error": f"Keine Lichter gefunden für '{where}'", "match_kind": "none"}
        wanted = set(target["entities"])
    else:
        wanted = None  # all lights

    all_states = api.get_states()
    items = []
    for s in all_states:
        if not s["entity_id"].startswith("light."):
            continue
        if wanted is not None and s["entity_id"] not in wanted:
            continue
        if state_filter and s["state"] != state_filter:
            continue
        items.append({
            "entity_id": s["entity_id"],
            "friendly_name": s["attributes"].get("friendly_name") or s["entity_id"],
            "state": s["state"],
            "brightness": s["attributes"].get("brightness"),
        })
    return {"ok": True, "action": "lights-status", "count": len(items), "lights": items}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Smart Home (HA-backed) — domain-optimierte CLI.")
    p.add_argument("--json", action="store_true", help="Antworten als JSON ausgeben")
    p.add_argument("--help-json", action="store_true", help="Hilfe als JSON (für Skill-Loader)")
    sub = p.add_subparsers(dest="command")

    lon = sub.add_parser(
        "lights-on",
        help=("Lichter EINSCHALTEN im angegebenen Scope. Scope ist eine Etage "
              "('OG', 'EG', 'KG', 'DG', 'Außen'), eine HA-Area "
              "('Wohnzimmer', 'Felix', 'Büro'), eine HA-Group entity_id, oder "
              "ein Friendly-Name-Fragment ('Esstisch'). Nutze für 'Licht an', "
              "'mach das Licht im X an', 'alle Lichter im OG einschalten'."),
    )
    lon.add_argument("--where", required=True,
                     help="Etage / Area / Group / Name-Fragment, z.B. 'OG', 'Wohnzimmer', 'Büro', 'Esstisch'")
    lon.add_argument("--brightness", type=int,
                     help="Helligkeit 0-100 (Prozent). Wenn ausgelassen: aktuelle/Default-Helligkeit.")
    lon.add_argument("--confirm", action="store_true",
                     help="Sicherheits-Cap (>10 Treffer) übergehen — nur bei explizitem User-Wunsch setzen.")
    lon.set_defaults(_is_write=True)

    loff = sub.add_parser(
        "lights-off",
        help=("Lichter AUSSCHALTEN im angegebenen Scope. Scope wie bei lights-on. "
              "Nutze für 'Licht aus', 'alle Lichter im EG aus', 'mach das Wohnzimmerlicht aus'."),
    )
    loff.add_argument("--where", required=True,
                      help="Etage / Area / Group / Name-Fragment, z.B. 'OG', 'Esstisch', 'Wohnzimmer'")
    loff.add_argument("--confirm", action="store_true",
                      help="Sicherheits-Cap (>10 Treffer) übergehen — nur bei explizitem User-Wunsch setzen.")
    loff.set_defaults(_is_write=True)

    lset = sub.add_parser(
        "lights-set",
        help=("Lichter EIN und auf eine bestimmte HELLIGKEIT setzen. Nutze für "
              "'dim Esstischlicht auf 30%', 'Licht im Büro auf 50%', "
              "'Wohnzimmer voll an' (brightness=100)."),
    )
    lset.add_argument("--where", required=True, help="Scope wie bei lights-on")
    lset.add_argument("--brightness", type=int, required=True, help="Helligkeit 0-100 (Prozent)")
    lset.add_argument("--confirm", action="store_true")
    lset.set_defaults(_is_write=True)

    lstat = sub.add_parser(
        "lights-status",
        help=("Live-Status der Lichter abfragen. Ohne --where: alle Lichter im "
              "Haus. Mit --where: nur die Lichter in diesem Scope. Optional "
              "--state on/off zum Filtern. Nutze für 'welche Lichter sind an?', "
              "'ist das Licht im Büro an?', 'Status der Küchenbeleuchtung'."),
    )
    lstat.add_argument("--where", help="optional Scope (Etage / Area / Group / Name)")
    lstat.add_argument("--state", choices=["on", "off"], help="optional Filter: nur 'on' oder 'off' Entities")

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.help_json:
        # Reuse the homeassistant skill's emitter so the format matches the
        # loader's HelpJsonScript shape exactly (including the `positional` flag).
        try:
            from skill_helpers import emit_help_json  # type: ignore
        except ImportError:
            sys.path.insert(0, _HA_SCRIPTS)
            from skill_helpers import emit_help_json  # type: ignore
        emit_help_json(parser)
        return 0

    if not args.command:
        parser.print_help()
        return 1

    api = HomeAssistantAPI()
    try:
        if args.command == "lights-on":
            result = lights_on(api, args.where, args.brightness, args.confirm)
        elif args.command == "lights-off":
            result = lights_off(api, args.where, args.confirm)
        elif args.command == "lights-set":
            result = lights_set(api, args.where, args.brightness, args.confirm)
        elif args.command == "lights-status":
            result = lights_status(api, args.where, args.state)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            return 1
    except Exception as e:
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        if isinstance(result, dict) and result.get("ok"):
            label = result.get("label") or result.get("action")
            n = len(result.get("entities_affected") or result.get("lights") or [])
            print(f"OK — {result.get('action')} auf '{label}' ({n} Entities)")
        else:
            print(f"FEHLER — {result.get('error') if isinstance(result, dict) else result}")
            return 1
    return 0 if (isinstance(result, dict) and result.get("ok")) else 1


if __name__ == "__main__":
    sys.exit(main())
