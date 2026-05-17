#!/usr/bin/env python3
"""Baut den Entity-Catalogue für den smart-home System-Prompt-Context.

Wird von smart_home_api.py's `context` Subcommand aufgerufen. Output ist
self-contained Markdown — der Agent kettet Skill-Context-Blocks nur noch
zusammen, keine zusätzliche Wrapper-Sektion.
"""

from collections import defaultdict
from datetime import datetime

from ha_client import HAClient


DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "scene", "script", "group"]

FLOOR_LABELS: dict[str, str] = {
    "kg": "KG (Kellergeschoss)",
    "eg": "EG (Erdgeschoss)",
    "og": "OG (Obergeschoss)",
    "dg": "DG (Dachgeschoss)",
    "aussen": "Außen",
}
FLOOR_ORDER = ["aussen", "kg", "eg", "og", "dg", "_other"]

DOMAIN_LABELS = {
    "light": "Lichter",
    "switch": "Schalter / Steckdosen",
    "cover": "Rollos / Jalousien",
    "climate": "Heizung / Klima",
    "scene": "Szenen",
    "script": "Skripte",
    "group": "Gruppen (bevorzugen für Sammelaktionen!)",
}


def floor_from_entity_id(entity_id: str) -> str:
    local = entity_id.split(".", 1)[-1]
    first = local.split("_", 1)[0]
    return first if first in FLOOR_LABELS else "_other"


def build_markdown(client: HAClient, domains: list[str] | None = None, max_per_area: int = 999) -> str:
    """Erzeuge den Catalogue-Markdown für den smart-home Skill."""
    domains = domains or DEFAULT_DOMAINS

    areas_raw = client.render_template("{{ areas() | sort | join(',') }}").strip()
    area_ids = [a.strip() for a in areas_raw.split(",") if a.strip()]
    area_names: dict[str, str] = {}
    for aid in area_ids:
        try:
            name = client.render_template(f"{{{{ area_name('{aid}') }}}}").strip()
            area_names[aid] = name or aid
        except Exception:
            area_names[aid] = aid

    entity_area: dict[str, str] = {}
    for aid in area_ids:
        for eid in client.entities_in_area(aid):
            entity_area[eid] = aid

    states = client.get_states()
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

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    out: list[str] = [
        f"BEKANNTE ENTITIES (smart-home, Snapshot {ts} — keine entity_ids erfinden, immer aus dieser Liste wählen):",
        "",
    ]
    for domain in domains:
        floors = grouped.get(domain)
        if not floors:
            continue
        out.append(f"### {DOMAIN_LABELS.get(domain, domain)} ({domain})")
        for floor in FLOOR_ORDER:
            areas = floors.get(floor)
            if not areas:
                continue
            out.append(f"#### {FLOOR_LABELS.get(floor, 'Sonstige')}")
            area_sorted = sorted(areas.keys(), key=lambda a: area_names.get(a, a))
            for aid in area_sorted:
                label = area_names.get(aid, "(ohne Area)" if aid == "_unassigned" else aid)
                for eid, friendly in areas[aid][:max_per_area]:
                    out.append(f"- {label}: `{eid}` ({friendly})")
        out.append("")
    return "\n".join(out).rstrip()
