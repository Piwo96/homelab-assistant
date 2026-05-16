#!/usr/bin/env python3
"""Home Assistant setup helper.

Uses the HA WebSocket API to inspect / manage:
- Area Registry  (rooms)
- Entity Registry (entity → area_id mapping)
- Light Groups   (helper.group entities composed of multiple lights)

Subcommands:
  inspect           — print current areas + per-area entity counts
  list-orphans      — list entities (filtered by domain) that have no area_id
  propose           — print suggested area + assignment mapping derived from
                       entity_id patterns (eg_essen_* → Esszimmer, etc.); use
                       this to preview what `apply` would do
  apply             — create missing areas, assign entities to areas
                       (default DRY-RUN; pass --commit to actually write)

Examples:
  python ha_setup.py inspect
  python ha_setup.py list-orphans --domain light
  python ha_setup.py propose
  python ha_setup.py apply               # dry run
  python ha_setup.py apply --commit      # actually write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import websockets
except ImportError:
    print("Error: 'websockets' library required. Install with: pip install websockets", file=sys.stderr)
    sys.exit(1)


def load_env() -> dict[str, str]:
    """Read repo-root .env for HOMEASSISTANT_HOST / HOMEASSISTANT_TOKEN."""
    # Walk up from this file to find the repo root (where .env lives).
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        env_file = parent / ".env"
        if env_file.exists():
            data: dict[str, str] = {}
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
            data.update({k: v for k, v in os.environ.items() if k.startswith("HOMEASSISTANT_")})
            return data
    return dict(os.environ)


class HAWebSocket:
    def __init__(self, host: str, token: str, *, ssl: bool = False, port: int = 8123):
        self.host = host
        self.token = token
        self.port = port
        proto = "wss" if ssl else "ws"
        # If host already contains a port (e.g. "homeassistant.local:8123") respect that.
        if ":" in host and not host.startswith("["):
            self.url = f"{proto}://{host}/api/websocket"
        else:
            self.url = f"{proto}://{host}:{port}/api/websocket"
        self._msg_id = 0
        self._ws: Any = None

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def __aenter__(self):
        self._ws = await websockets.connect(self.url)
        # Auth handshake
        hello = json.loads(await self._ws.recv())
        if hello.get("type") != "auth_required":
            raise RuntimeError(f"Expected auth_required, got {hello}")
        await self._ws.send(json.dumps({"type": "auth", "access_token": self.token}))
        auth = json.loads(await self._ws.recv())
        if auth.get("type") != "auth_ok":
            raise RuntimeError(f"Auth failed: {auth}")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._ws is not None:
            await self._ws.close()

    async def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a payload with auto-assigned id and wait for the matching reply."""
        mid = self._next_id()
        payload = {**payload, "id": mid}
        await self._ws.send(json.dumps(payload))
        # Loop until we see a result whose id matches; HA may interleave events.
        while True:
            raw = await self._ws.recv()
            msg = json.loads(raw)
            if msg.get("id") == mid and msg.get("type") == "result":
                if not msg.get("success", False):
                    raise RuntimeError(f"WS call failed: {msg.get('error') or msg}")
                return msg.get("result") or {}


# ---------------------------------------------------------------------------
# Area assignment heuristic
# ---------------------------------------------------------------------------
# Pattern → (area name, priority). Higher priority wins when multiple match.
# Entity ids are normalized by splitting domain and using only the object part,
# so "light.eg_essen_tischleuchte" → "eg_essen_tischleuchte".

AREA_RULES: list[tuple[re.Pattern[str], str, int]] = [
    # EG (Erdgeschoss)
    (re.compile(r"^eg_essen[_/]"),               "Esszimmer",           50),
    (re.compile(r"^eg_wohn_ess[_/]"),            "Esszimmer",           60),  # wohn_ess often dining
    (re.compile(r"^eg_wohn[_/]"),                "Wohnzimmer",          40),
    (re.compile(r"^eg_kueche?[_/]|^eg_kuche[_/]"), "Küche",             50),
    (re.compile(r"^eg_garderobe[_/]"),           "Garderobe",           50),
    (re.compile(r"^eg_garage[_/]"),              "Garage",              50),
    (re.compile(r"^eg_flur[_/]"),                "Flur EG",             50),
    # OG (Obergeschoss)
    (re.compile(r"^og_kind_1[_/]"),              "Kinderzimmer 1",      50),
    (re.compile(r"^og_kind_2[_/]"),              "Kinderzimmer 2",      50),
    (re.compile(r"^og_kind_3[_/]"),              "Kinderzimmer 3",      50),
    (re.compile(r"^og_bad_kinder[_/]"),          "Bad Kinder",          50),
    (re.compile(r"^og_ankleide[_/]"),            "Ankleide OG",         50),
    (re.compile(r"^og_flur[_/]"),                "Flur OG",             50),
    (re.compile(r"^og_schlaf"),                  "Schlafzimmer",        50),
    # DG (Dachgeschoss)
    (re.compile(r"^dg_bad_eltern[_/]"),          "Bad Eltern",          50),
    (re.compile(r"^dg_ankleide[_/]"),            "Ankleide DG",         50),
    (re.compile(r"^dg_buro[_/]"),                "Büro",                50),
    (re.compile(r"^dg_spitzboden[_/]"),          "Spitzboden",          50),
    (re.compile(r"^dg_flur[_/]"),                "Flur DG",             50),
    (re.compile(r"^dg_treppenhaus"),             "Treppe",              45),
    # KG (Kellergeschoss)
    (re.compile(r"^kg_hobby[_/]"),               "Hobbyraum",           50),
    (re.compile(r"^kg_hwr[_/]"),                 "HWR",                 50),
    (re.compile(r"^kg_bad_keller[_/]"),          "Bad Keller",          50),
    (re.compile(r"^kg_technikraum[_/]"),         "Technikraum",         50),
    (re.compile(r"^kg_abstellraum[_/]"),         "Abstellraum",         50),
    (re.compile(r"^kg_flur[_/]"),                "Flur Keller",         50),
    (re.compile(r"^kg_treppe[_/]"),              "Treppe Keller",       50),
    # Außen
    (re.compile(r"^aussen[_/]"),                 "Außen",               40),
    # Cross-floor
    (re.compile(r"^eg_og_treppen|^og_eg_treppen"), "Treppe",            45),
    # Generic Wandleuchten Schlafzimmer (no etage prefix)
    (re.compile(r"^wandleuchten_schlafzimmer"),  "Schlafzimmer",        45),
]


def propose_area_for_entity(entity_id: str) -> str | None:
    """Return the suggested area name for an entity_id, or None if no rule matches."""
    if "." not in entity_id:
        return None
    object_id = entity_id.split(".", 1)[1]
    best: tuple[int, str] | None = None
    for pattern, name, priority in AREA_RULES:
        if pattern.search(object_id):
            if best is None or priority > best[0]:
                best = (priority, name)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_inspect(ws: HAWebSocket) -> None:
    areas = await ws.call({"type": "config/area_registry/list"})
    entities = await ws.call({"type": "config/entity_registry/list"})
    states = await ws.call({"type": "get_states"})

    area_by_id = {a["area_id"]: a for a in areas}
    entities_by_area: dict[str | None, list[str]] = {}
    for e in entities:
        entities_by_area.setdefault(e.get("area_id"), []).append(e["entity_id"])

    print(f"Areas defined in HA: {len(areas)}")
    for a in sorted(areas, key=lambda x: x["name"]):
        count = len(entities_by_area.get(a["area_id"], []))
        print(f"  • {a['name']:30}  id={a['area_id']:30}  entities={count}")
    orphan_count = len(entities_by_area.get(None, []))
    print(f"\nEntities without area: {orphan_count} / {len(entities)} total")
    print(f"Live states available: {len(states)}")


async def cmd_list_orphans(ws: HAWebSocket, domain: str | None) -> None:
    entities = await ws.call({"type": "config/entity_registry/list"})
    orphans = [e for e in entities if not e.get("area_id")]
    if domain:
        orphans = [e for e in orphans if e["entity_id"].startswith(f"{domain}.")]
    print(f"Orphan entities ({len(orphans)}):")
    for e in orphans:
        fn = e.get("name") or e.get("original_name") or ""
        print(f"  {e['entity_id']:55}  {fn}")


def _build_proposal(entities: list[dict[str, Any]], domain: str | None) -> dict[str, list[str]]:
    """Return area_name → [entity_ids] mapping for entities the rules cover."""
    proposal: dict[str, list[str]] = {}
    for e in entities:
        entity_id = e["entity_id"]
        if domain and not entity_id.startswith(f"{domain}."):
            continue
        suggested = propose_area_for_entity(entity_id)
        if suggested:
            proposal.setdefault(suggested, []).append(entity_id)
    return proposal


async def cmd_propose(ws: HAWebSocket, domain: str | None) -> None:
    entities = await ws.call({"type": "config/entity_registry/list"})
    proposal = _build_proposal(entities, domain)
    print(f"Proposed area mapping ({sum(len(v) for v in proposal.values())} entity assignments "
          f"across {len(proposal)} areas):\n")
    for area in sorted(proposal):
        ids = proposal[area]
        print(f"  {area}  ({len(ids)} entities)")
        for eid in sorted(ids):
            print(f"    └─ {eid}")
    # Show entities not covered by any rule
    covered = {eid for ids in proposal.values() for eid in ids}
    all_in_domain = [
        e["entity_id"] for e in entities
        if not domain or e["entity_id"].startswith(f"{domain}.")
    ]
    not_covered = [eid for eid in all_in_domain if eid not in covered]
    if not_covered:
        print(f"\nUncovered ({len(not_covered)}) — need a new rule or manual assignment:")
        for eid in sorted(not_covered):
            print(f"  • {eid}")


async def cmd_apply(ws: HAWebSocket, *, commit: bool, domain: str | None) -> None:
    existing_areas = await ws.call({"type": "config/area_registry/list"})
    existing_by_name = {a["name"]: a for a in existing_areas}
    entities = await ws.call({"type": "config/entity_registry/list"})
    entity_by_id = {e["entity_id"]: e for e in entities}
    proposal = _build_proposal(entities, domain)

    print(f"{'[DRY RUN] ' if not commit else ''}Plan:\n")
    created = 0
    assigned = 0
    skipped = 0
    for area_name, eids in proposal.items():
        if area_name in existing_by_name:
            area_id = existing_by_name[area_name]["area_id"]
            print(f"  area exists: {area_name}  (id={area_id})")
        else:
            print(f"  CREATE area: {area_name}")
            if commit:
                result = await ws.call({"type": "config/area_registry/create", "name": area_name})
                area_id = result["area_id"]
                existing_by_name[area_name] = result
            else:
                area_id = f"<would-be-created>"
            created += 1

        for eid in eids:
            current = entity_by_id.get(eid, {}).get("area_id")
            if current == area_id:
                skipped += 1
                continue
            print(f"    assign {eid}  →  {area_name}"
                  f"{f' (was {current})' if current else ''}")
            if commit:
                await ws.call({
                    "type": "config/entity_registry/update",
                    "entity_id": eid,
                    "area_id": area_id,
                })
            assigned += 1
    print(f"\n{'Applied' if commit else 'Would apply'}: "
          f"{created} areas, {assigned} assignments ({skipped} already correct).")


async def amain():
    parser = argparse.ArgumentParser(description="Home Assistant area/entity setup helper")
    parser.add_argument("--host", help="HA host (overrides HOMEASSISTANT_HOST)")
    parser.add_argument("--token", help="HA token (overrides HOMEASSISTANT_TOKEN)")
    parser.add_argument("--ssl", action="store_true", help="Use wss://")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect")
    p_orph = sub.add_parser("list-orphans")
    p_orph.add_argument("--domain")
    p_prop = sub.add_parser("propose")
    p_prop.add_argument("--domain", default="light")
    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--commit", action="store_true", help="Actually write changes")
    p_apply.add_argument("--domain", default="light")
    args = parser.parse_args()

    env = load_env()
    host = args.host or env.get("HOMEASSISTANT_HOST")
    token = args.token or env.get("HOMEASSISTANT_TOKEN")
    if not host or not token:
        print("Error: HOMEASSISTANT_HOST and HOMEASSISTANT_TOKEN must be set "
              "(in .env or as CLI args)", file=sys.stderr)
        sys.exit(2)

    async with HAWebSocket(host, token, ssl=args.ssl) as ws:
        if args.cmd == "inspect":
            await cmd_inspect(ws)
        elif args.cmd == "list-orphans":
            await cmd_list_orphans(ws, args.domain)
        elif args.cmd == "propose":
            await cmd_propose(ws, args.domain)
        elif args.cmd == "apply":
            await cmd_apply(ws, commit=args.commit, domain=args.domain)


if __name__ == "__main__":
    asyncio.run(amain())
