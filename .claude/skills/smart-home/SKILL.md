---
name: smart-home
description: Smart Home in Philipp's Haushalt steuern — Lichter, Rollos/Jalousien, Heizung, Szenen pro Etage (KG/EG/OG/DG), Bereich oder Einzelgerät. Optimiert für deutsche Alltagskommandos ('alle OG-Lichter aus', 'Rollos im Schlafzimmer hoch', 'Lamellen auf 50%').
triggers:
  - licht
  - lampe
  - beleuchtung
  - rollo
  - rolladen
  - jalousie
  - lamelle
  - heizung
  - klima
  - temperatur
  - szene
  - "alles aus"
  - "alle lichter"
  - obergeschoss
  - erdgeschoss
  - keller
  - dachgeschoss
intent_hints:
  - Lichter ein/ausschalten in einem Bereich oder einer ganzen Etage
  - Rollos öffnen/schließen oder Position/Lamellen-Neigung setzen
  - Heizung auf Zieltemperatur stellen
  - Szenen aktivieren
  - Sammel-Aktionen "alle Lichter im OG aus" / "alle Rollos im EG zu"
---

# Smart Home Steuerung

Domain-optimierte Skill-Schicht für Philipp's Wohnung. Spricht User-Mental-Model (Etagen, Räume, deutsche Alltagsworte), kapselt die Home Assistant-Implementierung darunter ein.

## Goal

Smart-Home-Befehle in der Sprache des Users entgegennehmen ("alle OG-Lichter aus", "Lamellen halb offen", "Bad auf 22 Grad") und in die richtigen HA-Service-Calls umsetzen — **ohne dass das LLM HA-Service-Namen oder entity_id-Konventionen kennen muss**.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| HA-Zugang | `.env` (`HOMEASSISTANT_HOST`, `HOMEASSISTANT_TOKEN`) | Ja | Geerbt vom `homeassistant` Skill |
| Hauptscript | `scripts/smart_home_api.py` | — | Argparse-CLI mit deutschem Vokabular |

## Tools

| Tool | Zweck |
|------|-------|
| `scripts/smart_home_api.py` | High-level Smart-Home-Commands; nutzt intern den `homeassistant` Skill als API |

## Outputs

- `--json`: Strukturierte Antworten `{ok, action, entities_affected, ...}` für das LLM
- Ohne `--json`: lesbare deutsche Bestätigung pro Aktion
- Fehler-Pfad: `{ok: false, error}` — niemals leere Arrays/Tracebacks

## Quick Start

```bash
# Eine einzelne Lampe schalten (Bereich oder Friendly-Name-Fragment)
smart_home_api.py lights-on --where "Büro"
smart_home_api.py lights-off --where "Esstisch"

# Eine ganze Etage
smart_home_api.py lights-off --where "OG"
smart_home_api.py lights-off --where "Obergeschoss"

# Mit Helligkeit
smart_home_api.py lights-set --where "Büro" --brightness 50

# Status
smart_home_api.py lights-status                    # alle Lichter
smart_home_api.py lights-status --where "OG"       # nur OG
smart_home_api.py lights-status --state on         # nur die die an sind
```

## Wohnungs-Struktur

| Etage | `--where` Aliasse | Bereiche (HA-Areas) |
|-------|---|---|
| **KG** | `kg`, `keller`, `kellergeschoss` | Abstellraum, Badezimmer Keller, Flur Keller, Hauswirtschaftsraum, Hobbyraum, Technikraum, Treppenhaus |
| **EG** | `eg`, `erdgeschoss` | Esszimmer, Wohnzimmer, Küche, Speisekammer, Garderobe, Flur Erdgeschoss, Garage, Eingang |
| **OG** | `og`, `obergeschoss` | Maila, Spielzimmer, Felix, Badezimmer Kinder, Ankleide (OG), Flur Obergeschoss |
| **DG** | `dg`, `dachgeschoss` | Schlafzimmer, Ankleide (DG), Büro, Badezimmer Eltern, Flur Dachgeschoss, Spitzboden |
| **Außen** | `aussen`, `terrasse`, `garten` | Terrasse, Eingang (Außenleuchten) |

Die `--where` Auflösung versucht in dieser Reihenfolge:
1. **HA-Group** (z.B. `group.og_lichter`) — falls vorhanden, bevorzugen (ein Call statt n)
2. **Etage** (Prefix-Match auf entity_id: `og_*`, `kg_*`, …)
3. **HA-Area** (Display-Name oder area_id)
4. **Friendly-Name-Fragment** (case-insensitive Substring)

## Commands (v1: Lichter)

| Command | Args | Zweck |
|---|---|---|
| `lights-on` | `--where <X> [--brightness N]` | Lichter im Scope X einschalten |
| `lights-off` | `--where <X>` | Lichter ausschalten |
| `lights-set` | `--where <X> --brightness N` | Helligkeit setzen (0-100%) |
| `lights-status` | `[--where <X>] [--state on\|off]` | Live-Status auflisten |

## Migrations-Backlog (aus homeassistant Skill zu übernehmen)

Stand Mai 2026: Lichter laufen via smart_home_api.py. Folgende Capabilities aus dem `homeassistant` Skill sind noch dort und sollten in dieses Skill wandern, da sie domain-spezifisch optimiert sind:

| Bereich | Was übernehmen | Quelle |
|---|---|---|
| Rollos | `cover-open/close/set-position/set-tilt` mit `--where`-Auflösung + Lamellen-vs-Position-Vokabular | `homeassistant_api.py` (cover-* commands) |
| Klima | `klima-set --target N --where X` mit set_cover_temperature | `homeassistant_api.py call-service climate.set_temperature` |
| Szenen | `szenen-aktivieren <name>`, `szenen-liste` mit Fuzzy-Match | `homeassistant_api.py activate-scene, list-scenes` |
| Bereich-aus | `bereich-aus <area>` — alle lights/switches/covers in Area aus | neu, kombiniert |
| Etage-aus | `etage-aus <floor>` — gleicher Pattern, Stockwerk-Scope | neu, kombiniert |
| Haus-modus | `haus-modus <heim\|abwesend\|nacht\|aufstehen>` Macros | neu, ggf. via HA-Szenen |
| Catalogue | `smart_home_catalogue.py` — Floor-grouped, mit Groups-Hint | `homeassistant_catalogue.py` (1:1 übernehmen oder Symlink) |

Der **gute Stoff aus `homeassistant`** der hier rein gehört:
- Floor-Logik (kg/eg/og/dg/aussen Prefix-Mapping) — bereits in resolve_where()
- Structured `{ok: true, ...}` Returns statt HA's leerem `[]` — bereits in v1
- Entity-Validation vor service call — funktioniert weil wir HomeAssistantAPI.call_service() nutzen
- Cover-Tilt-Vokabular im Prompt + dedizierte Tools für die zwei Achsen

Der **rohe HA-Layer** bleibt im `homeassistant` Skill (entities, get-state, call-service als Fallback wenn smart-home noch keinen Befehl hat).

## Edge Cases

| Szenario | Verhalten |
|----------|-----------|
| `--where` matched 0 Entities | `{ok: false, error: "Keine Treffer für '<X>'"}` + Vorschläge aus den nächsten Treffern |
| `--where` matched >10 Entities | Aktion **wird nicht ausgeführt** — `{ok: false, error: "Zu viele Treffer (N) ..."}` — Schutz vor versehentlichem Massen-Schalten |
| Group-Match aber Group-Service schlägt fehl | Fallback auf Einzel-Schaltung aller Group-Mitglieder |
| Brightness > 100 oder < 0 | Auf [0, 100] geclampt |

## Resources

- **[scripts/smart_home_api.py](scripts/smart_home_api.py)** — Hauptscript
- **[../homeassistant/SKILL.md](../homeassistant/SKILL.md)** — Low-level HA-API (Fallback wenn dieses Skill noch keinen Befehl hat)

## Related Skills

- [/homeassistant](../homeassistant/SKILL.md) — Roh-API, wird intern genutzt
