---
name: homeassistant
description: Smart Home steuern - Licht, Sensoren, Szenen, Automationen, Schalter und Geräte
version: 1.2.0
author: Philipp Rollmann
tags:
  - homelab
  - smarthome
  - homeassistant
  - automation
  - iot
requires:
  - python3
  - requests
triggers:
  - /homeassistant
  - /hass
intent_hints:
  - "Licht an/aus, dimmen, Farbe ändern"
  - "Temperatur, Sensor-Werte, Luftfeuchtigkeit"
  - "Szene aktivieren, Stimmung setzen"
  - "Geräte ein/ausschalten, Steckdose"
  - "Automation starten/stoppen"
  - "Smart Home Status, welche Geräte sind an"
  - "Wohnzimmer, Küche, Schlafzimmer (Raumsteuerung)"
---

# Home Assistant Management

Control Home Assistant: entities, scenes, automations, scripts, and smart home devices.

## Goal

Automate Home Assistant operations via REST API without needing the web UI or mobile app.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `HOMEASSISTANT_HOST` | `.env` | Yes | HA server (e.g., `homeassistant.local:8123`) |
| `HOMEASSISTANT_TOKEN` | `.env` | Yes | Long-lived access token |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/homeassistant_api.py` | CLI for all Home Assistant operations |

## Outputs

- Entity states and attributes
- Lists of automations, scenes, scripts
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

- **[API.md](API.md)** - REST API reference and authentication
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# System Status
homeassistant_api.py status               # HA running status
homeassistant_api.py config               # System configuration

# Entity Management
homeassistant_api.py entities             # List all entities
homeassistant_api.py entities --domain light    # Filter by domain
homeassistant_api.py entities --domain switch
homeassistant_api.py state <entity_id>    # Get entity state

# Light Control
homeassistant_api.py turn-on light.living_room
homeassistant_api.py turn-on light.bedroom --brightness 200
homeassistant_api.py turn-on light.office --rgb 255,180,100
homeassistant_api.py turn-off light.all

# Switch/Device Control
homeassistant_api.py turn-on switch.coffee_maker
homeassistant_api.py turn-off switch.bedroom_fan
homeassistant_api.py toggle switch.desk_lamp

# Scenes
homeassistant_api.py list-scenes
homeassistant_api.py activate-scene scene.movie_time
homeassistant_api.py activate-scene scene.good_night

# Automations
homeassistant_api.py list-automations
homeassistant_api.py trigger automation.motion_light
homeassistant_api.py enable-automation automation.morning_routine
homeassistant_api.py disable-automation automation.away_mode

# Scripts
homeassistant_api.py list-scripts
homeassistant_api.py run-script script.morning_routine
homeassistant_api.py run-script script.lock_all_doors
```

## Advanced API Operations

```bash
# System & Diagnose
homeassistant_api.py components              # Geladene Komponenten auflisten

# Alle verfügbaren Services auflisten
homeassistant_api.py services

# Entity-Status direkt setzen (für virtuelle Sensoren)
homeassistant_api.py set-state <entity_id> <state> --attributes '{"key": "value"}'

# Events auslösen
homeassistant_api.py fire-event <event_type> --data '{"key": "value"}'

# Templates rendern (Jinja2)
homeassistant_api.py render-template "{{ states('sensor.temperature') }}"

# Entity umschalten (toggle)
homeassistant_api.py toggle switch.desk_lamp
homeassistant_api.py toggle light.living_room
```

## Dashboard API (Lovelace)

Separate API für Dashboard-Verwaltung via WebSocket (`scripts/dashboard_api.py`).

```bash
# Dashboard auflisten
dashboard_api.py list

# Dashboard-Konfiguration abrufen
dashboard_api.py get
dashboard_api.py get --dashboard my-dashboard -o dashboard.json

# Dashboard-Konfiguration speichern
dashboard_api.py set dashboard.yaml
dashboard_api.py set dashboard.json --dashboard my-dashboard


# Dashboard-Optimierung optimieren
dashboard_api.py optimize                     # Haupt-Dashboard optimieren
dashboard_api.py optimize --dashboard my-dash # Spezifisches Dashboard optimieren
dashboard_api.py optimize --backup            # Mit Backup vor Optimierung
dashboard_api.py optimize --dry-run           # Zeige geplante Änderungen ohne Anwendung```

## Workflows

### Morning Routine
1. Activate scene: `activate-scene scene.morning`
2. Start coffee: `turn-on switch.coffee_maker`
3. Trigger automation: `trigger automation.morning_routine`

### Movie Night
1. Activate scene: `activate-scene scene.movie_time`
   - Dims lights, sets TV input, closes blinds (if configured)

### Leaving Home
1. Run script: `run-script script.leaving_home`
2. Or activate scene: `activate-scene scene.away`
3. Verify all off: `entities --domain light` (check states)

### Control Single Light
1. Turn on: `turn-on light.living_room`
2. Adjust brightness: `turn-on light.living_room --brightness 150`
3. Change color: `turn-on light.living_room --rgb 255,200,150`
4. Turn off: `turn-off light.living_room`

### Troubleshoot Automation
1. List automations: `list-automations`
2. Check automation state (enabled/disabled)
3. Check trigger entity: `state binary_sensor.motion_hall`
4. Manually trigger: `trigger automation.motion_light`
5. If needed, disable: `disable-automation automation.motion_light`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Invalid token | 401 Unauthorized | Create new long-lived token |
| Entity not found | 404 Not Found | Verify entity_id with `entities` |
| Light doesn't support RGB | Attribute ignored | Check light capabilities first |
| Automation disabled | Trigger fails silently | Enable first: `enable-automation` |
| Script has required variables | Script fails | Pass variables via `--data` |
| HA restarting | Connection refused | Wait and retry |

## Entity ID Patterns

Common Home Assistant entity ID patterns:
- `light.living_room` - Lights
- `switch.coffee_maker` - Switches
- `binary_sensor.motion_hall` - Binary sensors
- `sensor.temperature_outside` - Sensors
- `automation.motion_light` - Automations
- `scene.movie_time` - Scenes
- `script.morning_routine` - Scripts
- `climate.thermostat` - Climate/HVAC

## Related Skills

- [/unifi-protect](../unifi-protect/SKILL.md) - Camera integration
- [/unifi-network](../unifi-network/SKILL.md) - Presence detection
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
