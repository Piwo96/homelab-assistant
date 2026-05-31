---
name: smart-home
description: Smart Home in Philipp's und Sophias' Haushalt steuern — Lichter, Rollos/Jalousien, Heizung, Szenen pro Etage (KG/EG/OG/DG), Bereich oder Einzelgerät. Optimiert für deutsche Alltagskommandos ('alle OG-Lichter aus', 'Rollos im Schlafzimmer hoch', 'Lamellen auf 50%').
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
requires:
  - python3
  - requests
intent_hints:
  - Lichter ein/ausschalten in einem Bereich oder einer ganzen Etage
  - Rollos öffnen/schließen oder Position/Lamellen-Neigung setzen
  - Heizung auf Zieltemperatur stellen
  - Szenen aktivieren
  - Sammel-Aktionen "alle Lichter im OG aus" / "alle Rollos im EG zu"
welcome:
  - heading: Lichter
    examples:
      - Wohnzimmer Licht an
      - alle Lichter im OG aus
      - dim das Büro auf 30%
  - heading: Rollos & Jalousien
    examples:
      - Rollos im Schlafzimmer hoch
      - Lamellen auf 50% neigen
  - heading: Heizung
    examples:
      - Bad auf 22 Grad
      - wie warm ist es im Wohnzimmer?
  - heading: Szenen
    examples:
      - starte Filmmodus
      - welche Szenen gibt es?
  - heading: Status
    examples:
      - welche Lichter sind an?
      - sind irgendwo Rollos offen?
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
smart_home_api.py rollos-status --state open       # nur offene Rollos (öffnend → zählt als offen)
smart_home_api.py klima-status --state heating     # nur aktiv heizende Geräte
```

> **Note**: `--state` is the counterweight to the write-cap. Without a filter, scope-less status queries on a 4B LLM tend to mis-trigger the write safety rule and refuse the call.

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

## Commands

**Lichter**

| Command | Args | Zweck |
|---|---|---|
| `lights-on` | `--where <X> [--brightness N]` | Lichter im Scope X einschalten |
| `lights-off` | `--where <X>` | Lichter ausschalten |
| `lights-set` | `--where <X> --brightness N` | Helligkeit setzen (0-100%) |
| `lights-status` | `[--where <X>] [--state on\|off]` | Live-Status auflisten |

**Rollos / Jalousien** — zwei Achsen: `--position` (Höhe, 0=zu/unten … 100=auf/oben) und `--tilt` (Lamellen-Neigung, 0=zu … 100=offen)

| Command | Args | Zweck |
|---|---|---|
| `rollos-open` | `--where <X>` | Rollo(s) ganz hochfahren/öffnen |
| `rollos-close` | `--where <X>` | Rollo(s) ganz runterfahren/schließen |
| `rollos-set` | `--where <X> [--position N] [--tilt N]` | Höhe und/oder Lamellen-Neigung setzen (beides in EINEM Call möglich) |
| `rollos-status` | `[--where <X>] [--state open\|closed]` | Rollenstatus auflisten; `opening`→`open`, `closing`→`closed` |

**Heizung / Klima**

| Command | Args | Zweck |
|---|---|---|
| `klima-set` | `--where <X> --target N` | Zieltemperatur setzen |
| `klima-status` | `[--where <X>] [--state heating\|idle\|off]` | Klimastatus auflisten; filtert auf `hvac_action`; `off` trifft auch `hvac_mode=off`; Response enthält `hvac_action` je Entity |

**Szenen**

| Command | Args | Zweck |
|---|---|---|
| `szenen-aktivieren` | `--name <X>` | Szene per Fuzzy-Match aktivieren |
| `szenen-liste` | — | Verfügbare Szenen auflisten |

**Sammel- & Einzel-Aktionen**

| Command | Args | Zweck |
|---|---|---|
| `bereich-aus` | `--area <X>` | Alle Lichter/Steckdosen/Rollos in einer HA-Area aus |
| `etage-aus` | `--floor <X>` | Gleiches für eine ganze Etage |
| `gerät-an` / `gerät-aus` / `gerät-toggle` | `--entity <id>` | Eine einzelne Entity schalten (entity_id) |
| `gerät-status` | `--entity <id>` | Live-Status einer einzelnen Entity |

> Alle Schreib-Commands akzeptieren `--confirm`. `--where`/`--area`/`--floor`-Auflösung siehe oben; bei >10 Treffern bricht die Aktion zur Sicherheit ab.

## Backlog (offen)

Lichter, Rollos (Höhe + Lamellen), Klima, Szenen, `bereich-aus`/`etage-aus` und die `gerät-*`-Einzelbefehle sind **implementiert** (siehe Commands oben). Noch offen:

| Idee | Skizze |
|---|---|
| Haus-Modus-Macros | `haus-modus <heim\|abwesend\|nacht\|aufstehen>` — ggf. nur dünne Wrapper um bestehende HA-Szenen |
| HA-Gruppen | Falls `group.*`-Entities angelegt werden: in `resolve_where()` bevorzugen (ein Service-Call statt n) — aktuell existieren keine Gruppen |

Der **rohe HA-Layer** bleibt im `homeassistant` Skill (entities, get-state, call-service als Fallback, wenn smart-home noch keinen passenden Befehl hat).

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
