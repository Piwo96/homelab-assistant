---
name: homeassistant
description: Home Assistant (HA, HASS) administration — entities, services, scenes, scripts, automations, dashboards (Lovelace), area/entity registry, integrations (KNX, HomeKit Bridge), history/logbook. Low-level HA control plane; user-facing smart-home commands live in the smart-home skill.
version: 1.4.0
author: Philipp Rollmann
tags:
  - homelab
  - homeassistant
  - hass
  - rest-api
  - websocket
  - lovelace
  - dashboards
  - registry
  - integrations
  - knx
  - homekit
  - automation
requires:
  - python3
  - requests
triggers:
  - /homeassistant
  - /hass
  - home assistant
  - hass
  - lovelace
  - dashboard
  - registry
  - integration
  - knx
  - homekit
  - automation
intent_hints:
  - "HA-Verwaltung: Entities listen, Services aufzählen, beliebigen Service aufrufen (call-service)"
  - "Automations/Scenes/Scripts inspizieren, triggern, enable/disable, reload"
  - "Dashboard/Lovelace lesen, schreiben, optimieren, Backup/Restore"
  - "Area Registry / Entity Registry abfragen und umbenennen (WebSocket)"
  - "Integrationen verwalten: Config-Entries reload (z.B. HomeKit Bridge nach Rename)"
  - "KNX: ETS-Projekt-Metadaten, Group Monitor, Entity-CRUD (cover-Tilt für Raffstore etc.)"
  - "Historie/Logbook abfragen, Template rendern (Jinja2)"
  - "HA-Status, Konfiguration, geladene Komponenten prüfen"
  - "Für End-User-Befehle (Licht/Rollo/Heizung in Räumen) → /smart-home"
---

# Home Assistant Management

Low-level Home Assistant control plane: every HA primitive exposed as a CLI, no domain logic on top. End-user smart-home commands ("alle OG-Lichter aus", "Rollo Schlafzimmer hoch") live in the [`smart-home`](../smart-home/SKILL.md) skill, which uses this skill as its REST/WS backend.

## Goal

Drive any Home Assistant operation that the web UI or app can — entities, services, automations, scenes, scripts, dashboards, registry, integrations — from a script or agent tool, without HTTP boilerplate.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `HOMEASSISTANT_HOST` | `.env` | Yes | HA server (e.g., `homeassistant.local:8123`) |
| `HOMEASSISTANT_TOKEN` | `.env` | Yes | Long-lived access token |
| `HOMEASSISTANT_SSL` | `.env` | No | `true`/`false`, default `false` |
| `HOMEASSISTANT_VERIFY_SSL` | `.env` | No | `true`/`false`, default `true` |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/homeassistant_api.py` | CLI for entities, services, automations, scenes, scripts, history/logbook (REST API) |
| `scripts/dashboard_api.py` | CLI for dashboard/Lovelace management (WebSocket API) |
| `scripts/ha_setup.py` | Area/entity registry inspection + bulk area assignment (WebSocket) |
| `scripts/homeassistant_catalogue.py` | Markdown snapshot of controllable entities for agent system prompts (not a discoverable tool) |

## Outputs

- Entity states and attributes
- Lists of automations, scenes, scripts, services, components
- Action confirmation messages
- Error messages to stderr

## Quick Start

1. Create long-lived access token:
   - HA Web UI → Profile → Long-Lived Access Tokens → Create Token
   - Copy the token (shown only once)

2. Configure `.env`:
   ```bash
   HOMEASSISTANT_HOST=homeassistant.local:8123
   HOMEASSISTANT_TOKEN=eyJ0eXAi...your-long-token
   ```

3. Test connection:
   ```bash
   python .claude/skills/homeassistant/scripts/homeassistant_api.py status
   ```

## Resources

- **[API.md](API.md)** - REST API reference, WebSocket API, registry, config entries, KNX, authentication details
- **[OPERATIONS.md](OPERATIONS.md)** - Operational tasks: entities, automations, scenes, scripts, dashboards, registry renames, HomeKit refresh
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues (connection, auth, entities, dashboards, KNX, HomeKit)
- **[scripts/homeassistant_api.py](scripts/homeassistant_api.py)** - REST API client
- **[scripts/dashboard_api.py](scripts/dashboard_api.py)** - WebSocket API client for dashboard management
- **[scripts/ha_setup.py](scripts/ha_setup.py)** - Area/entity registry tooling
- **[dashboards/home.yaml](dashboards/home.yaml)** - Example dashboard configuration

## Common Commands

```bash
# System status
homeassistant_api.py status               # HA reachability + version
homeassistant_api.py config               # Full configuration
homeassistant_api.py components           # Loaded integrations

# Entity discovery
homeassistant_api.py entities                            # All entities (capped)
homeassistant_api.py entities --domain light             # Filter by domain
homeassistant_api.py entities --area "Wohnzimmer"        # Filter by HA area
homeassistant_api.py entities --state on                 # Filter by state
homeassistant_api.py get-state <entity_id>               # One entity, full attrs

# Generic control
homeassistant_api.py turn-on <entity_id>
homeassistant_api.py turn-off <entity_id>
homeassistant_api.py toggle <entity_id>

# Arbitrary service call (the escape hatch)
homeassistant_api.py call-service climate set_temperature \
  --entity climate.wohnzimmer --data '{"temperature": 21}'
homeassistant_api.py call-service cover set_cover_position \
  --entity cover.dg_schlafen_rollo --data '{"position": 50}'

# Scenes / scripts / automations
homeassistant_api.py list-scenes
homeassistant_api.py activate-scene <scene_id>
homeassistant_api.py list-automations
homeassistant_api.py trigger <automation_id>
homeassistant_api.py enable <automation_id>
homeassistant_api.py disable <automation_id>
homeassistant_api.py reload-automations
homeassistant_api.py list-scripts
homeassistant_api.py run-script <script_id>
homeassistant_api.py stop-script <script_id>

# Diagnostics / history
homeassistant_api.py history [entity_id] --hours 24
homeassistant_api.py logbook --hours 1
```

## Advanced API Operations

`HomeAssistantAPI` (in `homeassistant_api.py`) exposes a few HA primitives that are not yet wired to subcommands but are callable from Python:

- `api.set_state(entity_id, state, attributes)` — push a state directly (virtual sensors / template hacks)
- `api.fire_event(event_type, data)` — fire arbitrary HA event
- `api.render_template(template)` — render a Jinja2 template server-side
- `api.entities_in_area(area)` — list entity_ids in an HA area

For area registry rename, entity friendly-name override, KNX entity CRUD, and HomeKit Bridge reload (all WebSocket / config-entries endpoints), see **[API.md](API.md)**.

## Dashboard API (Lovelace)

Separate API for dashboard management via WebSocket (`scripts/dashboard_api.py`).

**Prerequisites**: `pip install websockets pyyaml`

```bash
# List all dashboards
dashboard_api.py list

# Get dashboard configuration
dashboard_api.py get                          # Get main dashboard
dashboard_api.py get --dashboard my-dashboard # Get specific dashboard
dashboard_api.py get -o dashboard.json        # Save to file

# Set dashboard configuration
dashboard_api.py set dashboard.yaml           # Update main dashboard from YAML
dashboard_api.py set dashboard.json --dashboard my-dashboard

# Optimize dashboard (performance & UX improvements)
dashboard_api.py optimize                     # Optimize main dashboard
dashboard_api.py optimize --dashboard my-dash # Optimize specific dashboard
dashboard_api.py optimize --backup            # Create backup before optimizing
dashboard_api.py optimize --dry-run           # Preview changes without applying
```

**What optimize does:**
- Removes empty views
- Adds refresh intervals to entity cards
- Sets default time ranges for graph cards
- Adds mobile-friendly titles

## Admin Workflows

### Discover what's installed
1. `homeassistant_api.py components` — which integrations are loaded
2. `homeassistant_api.py entities --domain <d>` — what each integration exposes
3. `homeassistant_api.py services` — what services are callable

### Troubleshoot an automation
1. `list-automations` — check enabled/disabled
2. `get-state <trigger entity>` — confirm the trigger source is reporting
3. `trigger <automation_id>` — manual fire, bypassing trigger but respecting conditions
4. `disable <automation_id>` — take it offline while debugging

### Registry rename with HomeKit refresh
1. WebSocket `config/area_registry/list` → find the `area_id`
2. WebSocket `config/area_registry/update` → rename display
3. WebSocket `config/entity_registry/update` → override friendly names if needed
4. REST `POST /api/config/config_entries/entry/<homekit_entry_id>/reload` → push to Apple Home

Full step-by-step in **[OPERATIONS.md § 9](OPERATIONS.md)**.

### Dashboard backup / restore
1. `dashboard_api.py get -o backup_$(date +%Y%m%d).json` — snapshot
2. Edit JSON/YAML or run `dashboard_api.py optimize --backup --dry-run`
3. `dashboard_api.py set <file>` — push back

### Add KNX cover tilt (raffstore)
WebSocket `knx/update_entity` with a combined `ga_angle` field carrying both `write` and `state`. After update, reload the HomeKit Bridge config entry so Apple Home picks up the new tilt slider. Payload + caveats in **[API.md § KNX Integration](API.md)**.

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Invalid token | 401 Unauthorized | Create new long-lived token |
| Entity not found | 404 Not Found | `call-service` validates entity_id first — verify with `entities` |
| HA restarting | Connection refused | Wait and retry |
| Dashboard WebSocket timeout | Connection drops | Check network stability, retry |
| Missing websockets library | Import error | `pip install websockets pyyaml` |
| Dashboard in YAML mode | Cannot save via API | Convert to storage mode in HA settings |
| HomeKit cache stale after rename | Old names persist in Apple Home | Reload HomeKit Bridge config entry |
| `knx/project_file_remove` | DESTRUCTIVE — wipes ETS project | Never invoke speculatively; see TROUBLESHOOTING.md |

## Entity ID Patterns

Common Home Assistant entity ID patterns:
- `light.<name>` - Lights
- `switch.<name>` - Switches / smart plugs
- `cover.<name>` - Covers / blinds / shutters
- `climate.<name>` - Thermostats / HVAC
- `binary_sensor.<name>` - Binary sensors
- `sensor.<name>` - Sensors (temperature, humidity, …)
- `automation.<name>` - Automations
- `scene.<name>` - Scenes
- `script.<name>` - Scripts
- `group.<name>` - Light/cover/etc. groups

## Related Skills

- [/smart-home](../smart-home/SKILL.md) — User-facing domain layer (Etagen, Räume, deutsche Befehle); uses this skill as its HA backend
- [/unifi-protect](../unifi-protect/SKILL.md) - Camera integration
- [/unifi-network](../unifi-network/SKILL.md) - Presence detection
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
