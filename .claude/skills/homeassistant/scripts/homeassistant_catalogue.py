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
DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "scene", "script", "group"]


# House-specific floor convention encoded in entity_id prefixes. The HA
# install in this household doesn't use HA's native floor feature, but its
# naming is consistent — every entity_id is `{domain}.{floor}_{room}_...`
# with `kg/eg/og/dg/aussen` as floor markers. Surfacing the floor in the
# catalogue lets the LLM resolve "alle og Lampen aus" without having to
# enumerate the seven separate HA areas that physically sit on the OG.
FLOOR_LABELS: dict[str, str] = {
    "kg": "KG (Kellergeschoss)",
    "eg": "EG (Erdgeschoss)",
    "og": "OG (Obergeschoss)",
    "dg": "DG (Dachgeschoss)",
    "aussen": "Außen",
}
FLOOR_ORDER = ["aussen", "kg", "eg", "og", "dg", "_other"]


def floor_from_entity_id(entity_id: str) -> str:
    """Derive the floor bucket from an entity_id. Pure prefix match against
    the part after the domain. Anything that doesn't match a known prefix
    falls into the `_other` bucket so we never silently lose entities."""
    local = entity_id.split(".", 1)[-1]
    first = local.split("_", 1)[0]
    return first if first in FLOOR_LABELS else "_other"


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

    # 3. Build the catalogue from current states. Group by (domain, floor, area).
    states = api.get_states()
    # nested: domain -> floor -> area_id -> [(eid, friendly), ...]
    grouped: dict[str, dict[str, dict[str, list[tuple[str, str]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        if domain not in domains:
            continue
        friendly = s.get("attributes", {}).get("friendly_name") or eid
        floor = floor_from_entity_id(eid)
        aid = entity_area.get(eid) or "_unassigned"
        grouped[domain][floor][aid].append((eid, friendly))

    # 4. Render as Markdown: Domain → Floor → Area → entity bullets.
    out: list[str] = []
    domain_labels = {
        "light": "Lichter",
        "switch": "Schalter / Steckdosen",
        "cover": "Rollos / Jalousien",
        "climate": "Heizung / Klima",
        "scene": "Szenen",
        "script": "Skripte",
        "group": "Gruppen (bevorzugen für Sammelaktionen!)",
    }
    for domain in domains:
        floors = grouped.get(domain)
        if not floors:
            continue
        out.append(f"### {domain_labels.get(domain, domain)} ({domain})")
        for floor in FLOOR_ORDER:
            areas = floors.get(floor)
            if not areas:
                continue
            out.append(f"#### {FLOOR_LABELS.get(floor, 'Sonstige')}")
            area_sorted = sorted(areas.keys(), key=lambda a: area_names.get(a, a))
            for aid in area_sorted:
                label = area_names.get(aid, "(ohne Area)" if aid == "_unassigned" else aid)
                for eid, friendly in areas[aid][: args.max_per_area]:
                    out.append(f"- {label}: `{eid}` ({friendly})")
        out.append("")  # blank line between domains

    print("\n".join(out).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
