#!/usr/bin/env python3
"""Smart Home — domain-optimierte CLI über Home Assistant.

Dieses Script übersetzt deutsche Alltagskommandos in HA-Service-Calls und
versteckt Service-Namen / entity_id-Konventionen vor dem LLM-Agenten. Es nutzt
intern den lokalen `ha_client.py` als HA-REST-Client (minimal, nur die
Methoden die smart-home tatsächlich braucht).

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

# smart-home ist self-contained: ha_client.py + catalogue.py + skill_helpers.py
# liegen alle im selben scripts/-Verzeichnis. Damit Python sie ohne package-
# Konfiguration findet, fügen wir _THIS_DIR zum sys.path hinzu.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from ha_client import HAClient as HomeAssistantAPI  # type: ignore  # noqa: E402


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


# Scope-strings the LLM passes meaning "no scope = all entities". The status
# tools treat these as if --where were omitted entirely. Without this guard,
# Gemma's "where=*" call hit resolve_where, matched nothing, and surfaced as a
# spurious "Keine X gefunden für '*'" failure even though the user asked an
# unscoped status question.
_WILDCARD_WHERE = {"", "*", "alle", "all", "any", "*all*"}


def _is_wildcard_where(where: str | None) -> bool:
    return where is None or _norm(where) in _WILDCARD_WHERE


def resolve_where(api: HomeAssistantAPI, where: str, domain: str) -> dict[str, Any]:
    """Resolve a user-supplied `--where` string into a concrete target.

    Accepts ONLY exact identifiers — the LLM is expected to look up entity_ids
    or friendly_names in its catalogue and pass them verbatim. No substring or
    fuzzy matching: ambiguous user vocabulary is the LLM's job to translate,
    not the tool's. If nothing matches the user gets a clear "not found" so
    the LLM can disambiguate or ask back.

    Recognized inputs:
      - HA entity_id, e.g. "light.eg_essen_tischleuchte"
      - HA-Group entity_id, e.g. "group.og_lichter"
      - Floor alias / display name, e.g. "OG", "Obergeschoss"
      - HA-Area display name or area_id, e.g. "Esszimmer", "esszimmer", "Felix"
      - Friendly_name (exact, case-insensitive), e.g. "EG Essen Tischleuchte"
    """
    needle = _norm(where)
    if not needle:
        return {"kind": "none", "entities": [], "label": where}

    states = api.get_states()

    # 0. Exact entity_id (single entity) — caller passed e.g. "light.eg_..."
    if "." in needle:
        for s in states:
            if s["entity_id"].lower() == needle and s["entity_id"].startswith(f"{domain}."):
                return {"kind": "entity", "entities": [s["entity_id"]],
                        "label": s["attributes"].get("friendly_name") or s["entity_id"]}
        # group.* entity_id reference
        if needle.startswith("group."):
            for s in states:
                if s["entity_id"].lower() == needle:
                    members = s["attributes"].get("entity_id") or []
                    domain_members = [m for m in members if isinstance(m, str) and m.startswith(f"{domain}.")]
                    if domain_members:
                        return {"kind": "group", "group_id": s["entity_id"],
                                "entities": domain_members,
                                "label": s["attributes"].get("friendly_name") or s["entity_id"]}

    # 1. HA-Group by exact friendly_name.
    for s in states:
        if not s["entity_id"].startswith("group."):
            continue
        fn = (s["attributes"].get("friendly_name") or "").lower()
        if needle == fn:
            members = s["attributes"].get("entity_id") or []
            domain_members = [m for m in members if isinstance(m, str) and m.startswith(f"{domain}.")]
            if domain_members:
                return {"kind": "group", "group_id": s["entity_id"], "entities": domain_members,
                        "label": s["attributes"].get("friendly_name") or s["entity_id"]}

    # 2. Etage / floor alias (exact).
    floor_key = FLOOR_ALIASES.get(needle)
    if floor_key:
        ents = [s["entity_id"] for s in states
                if s["entity_id"].startswith(f"{domain}.")
                and _floor_of(s["entity_id"]) == floor_key]
        if ents:
            short, _ = FLOOR_LABELS[floor_key]
            return {"kind": "floor", "floor": floor_key, "entities": ents, "label": short}

    # 3. HA-Area: exact display name OR exact area_id.
    areas_raw = api.render_template("{{ areas() | sort | join(',') }}").strip()
    area_ids = [a.strip() for a in areas_raw.split(",") if a.strip()]
    for aid in area_ids:
        try:
            name = api.render_template(f"{{{{ area_name('{aid}') }}}}").strip().lower()
        except Exception:
            name = aid
        if needle == aid.lower() or needle == name:
            try:
                area_ents = api.entities_in_area(aid)
                ents = [e for e in area_ents if e.startswith(f"{domain}.")]
                if ents:
                    return {"kind": "area", "area_id": aid, "entities": ents,
                            "label": name.title() if name else aid}
            except Exception:
                continue

    # 4. Exact friendly_name (case-insensitive).
    for s in states:
        if not s["entity_id"].startswith(f"{domain}."):
            continue
        fn = (s["attributes"].get("friendly_name") or "").lower()
        if needle == fn:
            return {"kind": "name", "entities": [s["entity_id"]],
                    "label": s["attributes"].get("friendly_name") or s["entity_id"]}

    # Nothing matched exactly. Compute fuzzy candidates so the LLM can retry
    # with one of them — strict matching is the contract, but a "did you mean?"
    # hint dramatically reduces user-facing failures when the LLM picks a
    # near-miss like "Tischlampe" instead of "EG Essen Tischleuchte".
    return {
        "kind": "none",
        "entities": [],
        "label": where,
        "candidates": _fuzzy_candidates(states, domain, needle),
    }


def _fuzzy_candidates(states: list[dict], domain: str, needle: str,
                      max_results: int = 5) -> list[dict[str, str]]:
    """Score-rank candidates by friendly_name / entity_id similarity to `needle`.

    Heuristics (case-insensitive, in priority order):
      - substring of needle in friendly_name              → 1.0
      - substring of needle in entity_id (underscores→space) → 0.8
      - any prefix of needle (length ≥4) is the prefix of any haystack word → 0.5

    The "prefix of needle" rule is what gets German near-misses across the
    finish line: 'Tischlampe' → 'Tischleuchte' (common prefix 'Tischl' /
    'Tisch'), 'Beleuchtung' → 'Beleuchtungsspots' (common prefix 'Beleucht'),
    'Schlaf' → 'Schlafzimmer'. Underscores in entity_ids are split so words
    inside 'light.eg_essen_tischleuchte' are individually matchable.
    """
    needle = needle.strip().lower()
    if not needle:
        return []
    scored: list[tuple[float, dict[str, str]]] = []
    for s in states:
        eid = s["entity_id"]
        if not eid.startswith(f"{domain}."):
            continue
        eid_lower = eid.lower()
        eid_localpart = eid_lower.split(".", 1)[1] if "." in eid_lower else eid_lower
        fn_raw = s["attributes"].get("friendly_name") or eid
        fn_lower = fn_raw.lower()
        score = 0.0
        if needle in fn_lower:
            score = 1.0
        elif needle in eid_lower.replace("_", " "):
            score = 0.8
        else:
            haystack_words = (fn_lower + " " + eid_localpart.replace("_", " ")).split()
            # Prefix-of-needle: descending lengths so the best (longest) match wins.
            for length in range(min(len(needle), 12), 3, -1):
                prefix = needle[:length]
                if any(w.startswith(prefix) for w in haystack_words):
                    score = max(score, 0.5)
                    break
        if score > 0:
            scored.append((score, {"entity_id": eid, "friendly_name": fn_raw}))
    scored.sort(key=lambda t: -t[0])
    return [c for _, c in scored[:max_results]]


def _no_match(target: dict[str, Any], domain_label: str, where: str) -> dict[str, Any]:
    """Uniform 'nothing found' result that surfaces fuzzy candidates so the
    LLM can re-call the same tool with one of the suggested exact names."""
    return {
        "ok": False,
        "error": f"Keine {domain_label} gefunden für '{where}'",
        "match_kind": "none",
        "candidates": target.get("candidates", []),
    }


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
        return _no_match(target, "Lichter", where)
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
        return _no_match(target, "Lichter", where)
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


# --------------------------------------------------------------------------
# Rollos / Jalousien — two axes (position = height, tilt = slat angle)
# --------------------------------------------------------------------------

def _cover_action(api: HomeAssistantAPI, where: str, confirm: bool,
                  *, position: int | None = None, tilt: int | None = None,
                  open_all: bool = False, close_all: bool = False) -> dict[str, Any]:
    target = resolve_where(api, where, "cover")
    if not target["entities"]:
        return _no_match(target, "Rollos", where)
    cap = _check_cap(target, confirm)
    if cap:
        return cap
    affected: list[str] = []
    for eid in target["entities"]:
        if open_all:
            api.call_service("cover", "open_cover", {"entity_id": eid})
        elif close_all:
            api.call_service("cover", "close_cover", {"entity_id": eid})
        else:
            # set-mode: position + tilt can be combined per entity
            if position is not None:
                api.call_service("cover", "set_cover_position",
                                 {"entity_id": eid, "position": max(0, min(100, position))})
            if tilt is not None:
                api.call_service("cover", "set_cover_tilt_position",
                                 {"entity_id": eid, "tilt_position": max(0, min(100, tilt))})
        affected.append(eid)
    return {
        "ok": True,
        "action": "rollos-open" if open_all else "rollos-close" if close_all else "rollos-set",
        "match_kind": target["kind"],
        "label": target.get("label"),
        "entities_affected": affected,
        **({"position": position} if position is not None else {}),
        **({"tilt_position": tilt} if tilt is not None else {}),
    }


def rollos_status(api: HomeAssistantAPI, where: str | None,
                  state_filter: str | None = None) -> dict[str, Any]:
    wanted = None
    if where and not _is_wildcard_where(where):
        target = resolve_where(api, where, "cover")
        if not target["entities"]:
            return _no_match(target, "Rollos", where)
        wanted = set(target["entities"])
    items = []
    for s in api.get_states():
        if not s["entity_id"].startswith("cover."):
            continue
        if wanted is not None and s["entity_id"] not in wanted:
            continue
        if state_filter:
            # HA reports cover state as open/closed/opening/closing. Treat
            # transitional states as their target ("opening" counts as open).
            st = s["state"]
            is_open = st in ("open", "opening")
            is_closed = st in ("closed", "closing")
            if state_filter == "open" and not is_open:
                continue
            if state_filter == "closed" and not is_closed:
                continue
        attrs = s["attributes"]
        items.append({
            "entity_id": s["entity_id"],
            "friendly_name": attrs.get("friendly_name") or s["entity_id"],
            "state": s["state"],
            "position": attrs.get("current_position"),
            "tilt_position": attrs.get("current_tilt_position"),
        })
    return {"ok": True, "action": "rollos-status", "count": len(items), "rollos": items}


# --------------------------------------------------------------------------
# Klima / Heizung
# --------------------------------------------------------------------------

def klima_set(api: HomeAssistantAPI, where: str, target_temp: float, confirm: bool) -> dict[str, Any]:
    target = resolve_where(api, where, "climate")
    if not target["entities"]:
        return _no_match(target, "Heizung", where)
    cap = _check_cap(target, confirm)
    if cap:
        return cap
    affected: list[str] = []
    for eid in target["entities"]:
        api.call_service("climate", "set_temperature",
                         {"entity_id": eid, "temperature": target_temp})
        affected.append(eid)
    return {
        "ok": True,
        "action": "klima-set",
        "match_kind": target["kind"],
        "label": target.get("label"),
        "entities_affected": affected,
        "target_temperature": target_temp,
    }


def klima_status(api: HomeAssistantAPI, where: str | None,
                 state_filter: str | None = None) -> dict[str, Any]:
    wanted = None
    if where and not _is_wildcard_where(where):
        target = resolve_where(api, where, "climate")
        if not target["entities"]:
            return _no_match(target, "Heizung", where)
        wanted = set(target["entities"])
    items = []
    for s in api.get_states():
        if not s["entity_id"].startswith("climate."):
            continue
        if wanted is not None and s["entity_id"] not in wanted:
            continue
        attrs = s["attributes"]
        # HA reports two relevant fields:
        #   state            = hvac_mode (off/heat/auto/...)
        #   hvac_action attr = what the unit is doing right now (heating/idle/off)
        # For "wo läuft die Heizung?" we filter on hvac_action; "off" matches
        # either hvac_action=off or hvac_mode=off so a fully-off entity is hit.
        if state_filter:
            hvac_action = attrs.get("hvac_action")
            if state_filter == "heating" and hvac_action != "heating":
                continue
            if state_filter == "idle" and hvac_action != "idle":
                continue
            if state_filter == "off" and not (hvac_action == "off" or s["state"] == "off"):
                continue
        items.append({
            "entity_id": s["entity_id"],
            "friendly_name": attrs.get("friendly_name") or s["entity_id"],
            "state": s["state"],
            "hvac_action": attrs.get("hvac_action"),
            "current_temperature": attrs.get("current_temperature"),
            "target_temperature": attrs.get("temperature"),
        })
    return {"ok": True, "action": "klima-status", "count": len(items), "klimas": items}


# --------------------------------------------------------------------------
# Szenen
# --------------------------------------------------------------------------

def szenen_aktivieren(api: HomeAssistantAPI, name: str) -> dict[str, Any]:
    # Fuzzy match against scene friendly_name or entity_id.
    needle = _norm(name)
    matches: list[tuple[str, str]] = []
    for s in api.get_states():
        if not s["entity_id"].startswith("scene."):
            continue
        fn = (s["attributes"].get("friendly_name") or "").lower()
        if needle == s["entity_id"].lower() or needle == fn or needle in fn:
            matches.append((s["entity_id"], s["attributes"].get("friendly_name") or s["entity_id"]))
    if not matches:
        return {"ok": False, "error": f"Keine Szene gefunden für '{name}'"}
    if len(matches) > 1:
        return {"ok": False, "error": f"Mehrere Szenen passen zu '{name}'",
                "candidates": [{"entity_id": e, "friendly_name": f} for e, f in matches]}
    eid, fname = matches[0]
    api.call_service("scene", "turn_on", {"entity_id": eid})
    return {"ok": True, "action": "szenen-aktivieren", "entity_id": eid, "friendly_name": fname}


def _entities_in_scope_across_domains(api: HomeAssistantAPI, where: str,
                                       domains: list[str]) -> dict[str, list[str]]:
    """Resolve --where for each domain and collect the entity_ids. Returns
    dict mapping domain → list of entity_ids that matched the scope."""
    by_domain: dict[str, list[str]] = {}
    for d in domains:
        target = resolve_where(api, where, d)
        if target["entities"]:
            by_domain[d] = target["entities"]
    return by_domain


def bereich_aus(api: HomeAssistantAPI, area: str, confirm: bool) -> dict[str, Any]:
    """Turn off all lights + switches in the given scope. Covers untouched
    (closing covers has different semantics — user can use rollos-close)."""
    scope = _entities_in_scope_across_domains(api, area, ["light", "switch"])
    total = sum(len(v) for v in scope.values())
    if total == 0:
        # Cross-domain "did you mean?" — merge candidates from both domains.
        states = api.get_states()
        candidates = (_fuzzy_candidates(states, "light", area, max_results=3)
                      + _fuzzy_candidates(states, "switch", area, max_results=2))
        return {"ok": False,
                "error": f"Keine Lichter/Steckdosen gefunden für Bereich '{area}'",
                "candidates": candidates}
    if not confirm and total > MASS_ACTION_CAP:
        return {"ok": False, "error": f"Zu viele Treffer ({total}) — bitte enger eingrenzen oder --confirm",
                "total": total, "entities_preview": [e for v in scope.values() for e in v][:5]}
    affected: dict[str, list[str]] = {}
    for domain, ents in scope.items():
        affected[domain] = []
        for eid in ents:
            api.call_service(domain, "turn_off", {"entity_id": eid})
            affected[domain].append(eid)
    return {"ok": True, "action": "bereich-aus", "scope": area,
            "entities_affected_by_domain": affected, "total": total,
            "note": "Lichter und Steckdosen aus. Rollos unverändert (nutze rollos-close separat)."}


def etage_aus(api: HomeAssistantAPI, floor: str, confirm: bool) -> dict[str, Any]:
    """Same as bereich-aus but resolves by floor (KG/EG/OG/DG/Außen)."""
    # Reuse bereich-aus — resolve_where handles floors via FLOOR_ALIASES.
    return bereich_aus(api, floor, confirm)


def gerät_action(api: HomeAssistantAPI, entity_id: str, action: str) -> dict[str, Any]:
    """Escape-hatch: direct entity action for rare cases the named commands
    don't cover. Validates the entity exists, then calls turn_on/off/toggle
    via its domain. Returns structured success."""
    try:
        state = api.get_state(entity_id)
    except Exception:
        return {"ok": False, "error": f"Entity '{entity_id}' nicht gefunden in HA"}
    domain = entity_id.split(".", 1)[0]
    service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(action)
    if not service:
        return {"ok": False, "error": f"Unbekannte Aktion '{action}'"}
    api.call_service(domain, service, {"entity_id": entity_id})
    return {"ok": True, "action": f"gerät-{action}", "entity_id": entity_id,
            "previous_state": state["state"]}


def gerät_status(api: HomeAssistantAPI, entity_id: str) -> dict[str, Any]:
    """Escape-hatch: raw state of a specific entity_id."""
    try:
        s = api.get_state(entity_id)
    except Exception:
        return {"ok": False, "error": f"Entity '{entity_id}' nicht gefunden"}
    return {"ok": True, "action": "gerät-status", "entity_id": entity_id,
            "state": s["state"], "friendly_name": s["attributes"].get("friendly_name"),
            "attributes": s["attributes"]}


def szenen_liste(api: HomeAssistantAPI) -> dict[str, Any]:
    scenes = [{"entity_id": s["entity_id"],
               "friendly_name": s["attributes"].get("friendly_name") or s["entity_id"]}
              for s in api.get_states() if s["entity_id"].startswith("scene.")]
    return {"ok": True, "action": "szenen-liste", "count": len(scenes), "szenen": scenes}


def lights_status(api: HomeAssistantAPI, where: str | None, state_filter: str | None) -> dict[str, Any]:
    if where and not _is_wildcard_where(where):
        target = resolve_where(api, where, "light")
        if not target["entities"]:
            return _no_match(target, "Lichter", where)
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

    # ----- Rollos / Jalousien -----
    rop = sub.add_parser(
        "rollos-open",
        help=("Rollos/Jalousien komplett HOCHFAHREN (position=100). Nutze für "
              "'Rollo hoch', 'Rollos öffnen', 'Jalousie ganz auf'."),
    )
    rop.add_argument("--where", required=True, help="Scope wie bei lights-*")
    rop.add_argument("--confirm", action="store_true")
    rop.set_defaults(_is_write=True)

    rcl = sub.add_parser(
        "rollos-close",
        help=("Rollos/Jalousien komplett HERUNTERFAHREN (position=0). Nutze für "
              "'Rollo runter', 'Rollos zu', 'Jalousie schließen', '100% runter'."),
    )
    rcl.add_argument("--where", required=True, help="Scope wie bei lights-*")
    rcl.add_argument("--confirm", action="store_true")
    rcl.set_defaults(_is_write=True)

    rset = sub.add_parser(
        "rollos-set",
        help=("Rollos setzen — zwei UNABHÄNGIGE Achsen: --position (Höhe: 0=zu/"
              "unten, 100=auf/oben) und/oder --tilt (Lamellen-Neigung: 0=zu/"
              "vertikal, 100=offen/horizontal). 'Lamellen auf X% neigen' → "
              "--tilt X. 'Rollo halb runter' → --position 50. Beide zusammen "
              "möglich. NIEMALS Lamellen-Neigung mit --position verwechseln!"),
    )
    rset.add_argument("--where", required=True, help="Scope wie bei lights-*")
    rset.add_argument("--position", type=int,
                      help="Höhe 0 (ganz unten/zu) bis 100 (ganz oben/offen)")
    rset.add_argument("--tilt", type=int,
                      help="Lamellen-Neigung 0 (zu) bis 100 (offen)")
    rset.add_argument("--confirm", action="store_true")
    rset.set_defaults(_is_write=True)

    rstat = sub.add_parser(
        "rollos-status",
        help=("Live-Status der Rollos abfragen (Position + Lamellen-Neigung). "
              "Ohne --where: alle. Mit --where: nur Scope. Optional --state "
              "open/closed zum Filtern. Nutze für 'welche Rollos sind offen?', "
              "'sind irgendwo Rollos offen?', 'wie weit ist das Rollo im X?'."),
    )
    rstat.add_argument("--where", help="optional Scope (Etage / Area / Group / Name)")
    rstat.add_argument("--state", choices=["open", "closed"],
                       help="optional Filter: nur 'open' oder 'closed' Rollos")

    # ----- Klima / Heizung -----
    kset = sub.add_parser(
        "klima-set",
        help=("Heizung auf Zieltemperatur stellen. Nutze für 'Heizung im Bad "
              "auf 22°', 'Wohnzimmer auf 21 Grad stellen', 'kühler im Büro'."),
    )
    kset.add_argument("--where", required=True, help="Scope wie bei lights-*")
    kset.add_argument("--target", type=float, required=True,
                      help="Zieltemperatur in °C, z.B. 21 oder 22.5")
    kset.add_argument("--confirm", action="store_true")
    kset.set_defaults(_is_write=True)

    kstat = sub.add_parser(
        "klima-status",
        help=("Live-Status der Heizung: aktuelle und Ziel-Temperatur plus "
              "hvac_action (heating/idle/off). Ohne --where: alle. Optional "
              "--state heating/idle/off filtert auf die hvac_action. Nutze für "
              "'wie warm ist es im X?', 'wo läuft die Heizung gerade?', 'auf "
              "welche Temperatur ist Y eingestellt?'."),
    )
    kstat.add_argument("--where", help="optional Scope")
    kstat.add_argument("--state", choices=["heating", "idle", "off"],
                       help="optional Filter: hvac_action heating/idle, oder komplett off")

    # ----- Szenen -----
    sact = sub.add_parser(
        "szenen-aktivieren",
        help=("Eine Szene aktivieren per Friendly-Name-Fragment (z.B. "
              "'Schlafenszeit', 'Filmmodus'). Nutze für 'Szene X starten', "
              "'aktivier die Y-Szene'."),
    )
    sact.add_argument("name", help="Name oder Fragment der Szene")
    sact.set_defaults(_is_write=True)

    sub.add_parser(
        "szenen-liste",
        help="Alle verfügbaren Szenen auflisten. Nutze für 'welche Szenen gibt es?'.",
    )

    # ----- Macros: Bereich-/Etage-aus -----
    ba = sub.add_parser(
        "bereich-aus",
        help=("Alle LICHTER und STECKDOSEN in einem Bereich/Raum ausschalten. "
              "Rollos werden NICHT angefasst (dafür separat rollos-close). "
              "Nutze für 'alles im Wohnzimmer aus', 'Felix-Zimmer aus', "
              "'mach im Büro alles aus'."),
    )
    ba.add_argument("area", help="HA-Area / Bereich, z.B. 'Wohnzimmer', 'Büro', 'Felix'")
    ba.add_argument("--confirm", action="store_true",
                    help="Sicherheits-Cap (>10) übergehen")
    ba.set_defaults(_is_write=True)

    ea = sub.add_parser(
        "etage-aus",
        help=("Alle LICHTER und STECKDOSEN auf einer ganzen Etage ausschalten "
              "(KG/EG/OG/DG/Außen). Rollos werden NICHT angefasst. Nutze für "
              "'alle OG-Lichter aus', 'alles im EG aus', 'Keller aus'."),
    )
    ea.add_argument("floor", help="Etage: 'OG', 'Obergeschoss', 'EG', 'KG', 'DG', 'Außen'")
    ea.add_argument("--confirm", action="store_true")
    ea.set_defaults(_is_write=True)

    # ----- Escape-hatch: direct entity action -----
    ga = sub.add_parser(
        "gerät-an",
        help=("ESCAPE-HATCH: ein spezifisches Gerät per entity_id einschalten. "
              "Nur nutzen wenn lights-on/rollos-* nicht passen (z.B. seltene "
              "Domain). Validiert dass die Entity existiert."),
    )
    ga.add_argument("--entity", required=True, help="z.B. switch.kg_hwr_schaltsteckd")
    ga.set_defaults(_is_write=True)

    gao = sub.add_parser(
        "gerät-aus",
        help="ESCAPE-HATCH: spezifisches Gerät per entity_id ausschalten.",
    )
    gao.add_argument("--entity", required=True)
    gao.set_defaults(_is_write=True)

    gtog = sub.add_parser(
        "gerät-toggle",
        help="ESCAPE-HATCH: spezifisches Gerät per entity_id togglen.",
    )
    gtog.add_argument("--entity", required=True)
    gtog.set_defaults(_is_write=True)

    gst = sub.add_parser(
        "gerät-status",
        help=("ESCAPE-HATCH: Roh-Status einer spezifischen Entity. Nur nutzen "
              "wenn lights-status / rollos-status / klima-status nicht passen."),
    )
    gst.add_argument("--entity", required=True)

    # ----- Context (für Agent System-Prompt) -----
    sub.add_parser(
        "context",
        help=("Liefert den Entity-Catalogue als Markdown-Block für den "
              "Agent-System-Prompt. Wird vom Agent beim Routing auf smart-home "
              "abgerufen und gecached. NICHT als User-Tool nutzen."),
    )

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.help_json:
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
        elif args.command == "rollos-open":
            result = _cover_action(api, args.where, args.confirm, open_all=True)
        elif args.command == "rollos-close":
            result = _cover_action(api, args.where, args.confirm, close_all=True)
        elif args.command == "rollos-set":
            if args.position is None and args.tilt is None:
                result = {"ok": False, "error": "rollos-set braucht mindestens --position oder --tilt"}
            else:
                result = _cover_action(api, args.where, args.confirm,
                                       position=args.position, tilt=args.tilt)
        elif args.command == "rollos-status":
            result = rollos_status(api, args.where, args.state)
        elif args.command == "klima-set":
            result = klima_set(api, args.where, args.target, args.confirm)
        elif args.command == "klima-status":
            result = klima_status(api, args.where, args.state)
        elif args.command == "szenen-aktivieren":
            result = szenen_aktivieren(api, args.name)
        elif args.command == "szenen-liste":
            result = szenen_liste(api)
        elif args.command == "bereich-aus":
            result = bereich_aus(api, args.area, args.confirm)
        elif args.command == "etage-aus":
            result = etage_aus(api, args.floor, args.confirm)
        elif args.command == "gerät-an":
            result = gerät_action(api, args.entity, "on")
        elif args.command == "gerät-aus":
            result = gerät_action(api, args.entity, "off")
        elif args.command == "gerät-toggle":
            result = gerät_action(api, args.entity, "toggle")
        elif args.command == "gerät-status":
            result = gerät_status(api, args.entity)
        elif args.command == "context":
            from catalogue import build_markdown
            # `ok: True` keeps the exit-code logic at the bottom of main()
            # (returns 1 unless result.ok is truthy) happy without leaking
            # into the agent's consumer, which only reads `markdown`.
            result = {"ok": True, "markdown": build_markdown(api)}
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
