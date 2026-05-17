#!/usr/bin/env python3
"""Print a Markdown catalogue of controllable Home Assistant entities,
grouped by area, for injection into the agent's system prompt.

Does NOT follow the *_api.py / --help-json contract on purpose: it should
not be discovered as a tool. The agent runs this once at startup, captures
stdout, and pastes the result into the LLM's system prompt so the model
never has to guess entity_ids.

Usage:
    python homeassistant_catalogue.py              # prints catalogue to stdout
    python homeassistant_catalogue.py --domains light,switch  # filter
"""

import argparse
import sys
from collections import defaultdict

from homeassistant_api import HomeAssistantAPI


# Controllable domains we want the LLM to know about. Sensor/update/zone/etc.
# are deliberately excluded — they're read-only context, not action targets,
# and would balloon the prompt without helping action selection.
DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "scene", "script"]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--domains", default=",".join(DEFAULT_DOMAINS),
                   help="Comma-separated list of domains to include")
    p.add_argument("--max-per-area", type=int, default=999,
                   help="Cap lines per area (defensive, normally not needed)")
    args = p.parse_args()

    domains = [d.strip() for d in args.domains.split(",") if d.strip()]
    api = HomeAssistantAPI()

    # 1. Map area_id -> display name. HA exposes both via template.
    areas_raw = api.render_template("{{ areas() | sort | join(',') }}").strip()
    area_ids = [a.strip() for a in areas_raw.split(",") if a.strip()]
    area_names: dict[str, str] = {}
    for aid in area_ids:
        try:
            name = api.render_template(f"{{{{ area_name('{aid}') }}}}").strip()
            area_names[aid] = name or aid
        except Exception:
            area_names[aid] = aid

    # 2. Map entity_id -> area_id. We invert area_entities(aid) for each area.
    entity_area: dict[str, str] = {}
    for aid in area_ids:
        for eid in api.entities_in_area(aid):
            entity_area[eid] = aid

    # 3. Build the catalogue from current states. Group by (domain, area).
    states = api.get_states()
    by_domain_area: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    unassigned: dict[str, list[tuple[str, str]]] = defaultdict(list)  # domain -> entries
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        if domain not in domains:
            continue
        friendly = s.get("attributes", {}).get("friendly_name") or eid
        aid = entity_area.get(eid)
        if aid:
            by_domain_area[(domain, aid)].append((eid, friendly))
        else:
            unassigned[domain].append((eid, friendly))

    # 4. Render as Markdown. Domains as headers, areas as sub-bullets.
    out: list[str] = []
    domain_labels = {
        "light": "Lichter",
        "switch": "Schalter / Steckdosen",
        "cover": "Rollos / Jalousien",
        "climate": "Heizung / Klima",
        "scene": "Szenen",
        "script": "Skripte",
    }
    for domain in domains:
        domain_keys = [k for k in by_domain_area if k[0] == domain]
        if not domain_keys and not unassigned.get(domain):
            continue
        out.append(f"### {domain_labels.get(domain, domain)} ({domain})")
        # Sort areas by display name
        area_sorted = sorted(domain_keys, key=lambda k: area_names.get(k[1], k[1]))
        for (_, aid) in area_sorted:
            entries = by_domain_area[(domain, aid)][: args.max_per_area]
            label = area_names.get(aid, aid)
            for eid, friendly in entries:
                out.append(f"- {label}: `{eid}` ({friendly})")
        # Trailing block for unassigned entries (e.g. scenes without an area)
        if unassigned.get(domain):
            for eid, friendly in unassigned[domain][: args.max_per_area]:
                out.append(f"- (ohne Area): `{eid}` ({friendly})")
        out.append("")  # blank line between domains

    print("\n".join(out).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
