# Home Assistant REST API Reference

Comprehensive API for controlling and automating your smart home.

## Base URL

```
http://<homeassistant-ip>:8123/api
```

Default port: `8123`

## Authentication

### Long-Lived Access Token

**Recommended method** for API access.

**Creating a token:**
1. Open Home Assistant UI
2. Click on your profile (bottom left)
3. Scroll to "Long-Lived Access Tokens"
4. Click "Create Token"
5. Give it a name (e.g., "Homelab Skill")
6. Copy the token (shown only once!)

**Using the token:**
```bash
Authorization: Bearer YOUR_LONG_LIVED_ACCESS_TOKEN
Content-Type: application/json
```

**Example:**
```bash
curl -H "Authorization: Bearer abc123..." \
     -H "Content-Type: application/json" \
     http://192.168.10.x:8123/api/states
```

## Core Endpoints

### States

Entity states represent the current status of devices and sensors.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/states` | Get all entity states |
| GET | `/api/states/<entity_id>` | Get specific entity state |
| POST | `/api/states/<entity_id>` | Update/create entity state |
| DELETE | `/api/states/<entity_id>` | Delete entity state |

**Example - Get all states:**
```bash
GET /api/states
```
```json
[
  {
    "entity_id": "light.living_room",
    "state": "on",
    "attributes": {
      "brightness": 255,
      "friendly_name": "Living Room Light"
    },
    "last_changed": "2026-01-21T10:30:00+00:00",
    "last_updated": "2026-01-21T10:30:00+00:00"
  },
  {
    "entity_id": "sensor.temperature",
    "state": "21.5",
    "attributes": {
      "unit_of_measurement": "°C",
      "friendly_name": "Living Room Temperature"
    }
  }
]
```

**Example - Get specific state:**
```bash
GET /api/states/light.living_room
```

**Example - Update state:**
```bash
POST /api/states/sensor.custom_sensor
{
  "state": "25",
  "attributes": {
    "unit_of_measurement": "°C",
    "friendly_name": "Custom Temperature"
  }
}
```

### Services

Services are actions you can call (turn on lights, set temperature, etc.).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/services` | List all available services |
| POST | `/api/services/<domain>/<service>` | Call a service |

**Common domains:**
- `light` - Light control
- `switch` - Switch control
- `climate` - Thermostat/HVAC
- `automation` - Automation control
- `script` - Script execution
- `scene` - Scene activation

**Example - Turn on light:**
```bash
POST /api/services/light/turn_on
{
  "entity_id": "light.living_room",
  "brightness": 200,
  "color_temp": 300
}
```

**Example - Turn off all lights:**
```bash
POST /api/services/light/turn_off
{
  "entity_id": "all"
}
```

**Example - Set thermostat:**
```bash
POST /api/services/climate/set_temperature
{
  "entity_id": "climate.living_room",
  "temperature": 21
}
```

**Example - Trigger automation:**
```bash
POST /api/services/automation/trigger
{
  "entity_id": "automation.motion_light"
}
```

**Example - Activate scene:**
```bash
POST /api/services/scene/turn_on
{
  "entity_id": "scene.good_night"
}
```

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/events` | Get event listener count |
| POST | `/api/events/<event_type>` | Fire an event |

**Example - Fire custom event:**
```bash
POST /api/events/custom_event
{
  "data": {
    "message": "Hello from API"
  }
}
```

### Config & System

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/` | API status (200 = running) |
| GET | `/api/config` | Get configuration |
| GET | `/api/components` | List loaded components |
| GET | `/api/error_log` | Get error log |

**Example - Get config:**
```bash
GET /api/config
```
```json
{
  "latitude": 52.37,
  "longitude": 4.89,
  "elevation": 0,
  "unit_system": {
    "length": "km",
    "mass": "kg",
    "temperature": "°C"
  },
  "location_name": "Home",
  "time_zone": "Europe/Amsterdam",
  "components": ["automation", "light", "sensor", ...],
  "version": "2026.1.0"
}
```

### History & Logbook

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/history/period/<timestamp>` | Get historical data |
| GET | `/api/logbook/<timestamp>` | Get logbook entries |

**Example - Get last 24h history:**
```bash
GET /api/history/period/2026-01-20T10:00:00+00:00?filter_entity_id=light.living_room
```

## Automation Management

Automations are managed via the `automation` domain service calls.

**List automations:**
```bash
GET /api/states
# Filter for entity_id starting with "automation."
```

**Trigger automation:**
```bash
POST /api/services/automation/trigger
{
  "entity_id": "automation.motion_light"
}
```

**Turn automation on/off:**
```bash
POST /api/services/automation/turn_on
{
  "entity_id": "automation.motion_light"
}

POST /api/services/automation/turn_off
{
  "entity_id": "automation.motion_light"
}
```

**Reload automations:**
```bash
POST /api/services/automation/reload
```

## Scene Management

**List scenes:**
```bash
GET /api/states
# Filter for entity_id starting with "scene."
```

**Activate scene:**
```bash
POST /api/services/scene/turn_on
{
  "entity_id": "scene.romantic"
}
```

**Create scene via automation:** Scenes are typically defined in YAML configuration or via UI.

## Script Management

**List scripts:**
```bash
GET /api/states
# Filter for entity_id starting with "script."
```

**Run script:**
```bash
POST /api/services/script/turn_on
{
  "entity_id": "script.morning_routine"
}

# Or use the script name directly as service
POST /api/services/script/morning_routine
```

**Stop script:**
```bash
POST /api/services/script/turn_off
{
  "entity_id": "script.morning_routine"
}
```

## Template Rendering

**Render a template:**
```bash
POST /api/template
{
  "template": "The temperature is {{ states('sensor.temperature') }}°C"
}
```

Response:
```json
"The temperature is 21.5°C"
```

## WebSocket API

For real-time updates and dashboard management, use the WebSocket API at:
```
ws://<homeassistant-ip>:8123/api/websocket
```

**Connection flow:**
1. Connect to WebSocket
2. Receive auth_required message
3. Send auth message with access token
4. Subscribe to events or send commands

**Example auth:**
```json
{
  "type": "auth",
  "access_token": "YOUR_TOKEN"
}
```

### Registry Operations (WebSocket)

Area and entity registry mutations are **only available via WebSocket** — the REST API has no equivalent.

**List area registry:**
```json
{ "id": 10, "type": "config/area_registry/list" }
```
Returns array of `{ area_id, name, aliases, ... }`. `area_id` is the stable identifier and never changes on rename.

**Rename an area (display name only, area_id stays unchanged):**
```json
{ "id": 11, "type": "config/area_registry/update", "area_id": "kinderzimmer_1", "name": "Maila" }
```
All entity area references are preserved automatically — no automation breakage.

**List entity registry:**
```json
{ "id": 12, "type": "config/entity_registry/list" }
```
Returns array of `{ entity_id, original_name, name, area_id, ... }`. `name` is the user override; `original_name` is the integration default and stays untouched.

**Override entity friendly name:**
```json
{ "id": 13, "type": "config/entity_registry/update", "entity_id": "light.kinderzimmer_1", "name": "Maila Licht" }
```
`state_attr(entity_id, 'friendly_name')` reflects the override immediately. Set `name` to `null` to revert to `original_name`.

> **Note**: `config_entries/reload` does NOT exist as a WebSocket command — use the REST endpoint below.

### Config Entry Management (REST)

**List all config entries (metadata only):**
```bash
GET /api/config/config_entries/entry
```
Returns `entry_id`, `domain`, `title`, `state`. The internal `options` dict (e.g. HomeKit filter, port) is not exposed by the API at all — modify it via the options flow in the UI.

**Reload a config entry (e.g. HomeKit Bridge after registry changes):**
```bash
POST /api/config/config_entries/entry/{entry_id}/reload
```
Returns `{"require_restart": false}` on success. Use this to make integrations re-sync after area/entity renames.

> **Tip**: To find the HomeKit Bridge `entry_id`, `GET /api/config/config_entries/entry` and filter by `domain == "homekit"`. Note: the `homekit` component appearing in `GET /api/components` only means the integration code is loaded — a configured bridge requires an actual config entry.

### KNX Integration (WebSocket)

The KNX integration exposes WebSocket commands for project metadata, monitor, and **entity CRUD**.

**Read-only (safe to probe):**
- `knx/get_knx_project` — full ETS project: `info`, `communication_objects`, `group_addresses`
- `knx/group_monitor_info` — `project_loaded` flag + recent telegrams
- `knx/subscribe_telegrams` — live telegram stream
- `knx/get_entity_config` — current config for a KNX entity (requires `entity_id`)

**Mutating (use only with explicit approval):**
- `knx/update_entity` — update a KNX entity's config. Required: `entity_id`, `platform`, `data`.
- `knx/create_entity` — create a new KNX entity. Required: `platform`, `data`.
- `knx/project_file_process` — upload a `.knxproj` file (replaces current project).
- `knx/project_file_remove` — **DESTRUCTIVE**: removes imported ETS project. Never invoke speculatively.

**Adding tilt support to a KNX cover (raffstore):**

The KNX cover entity uses a combined `ga_angle` field containing BOTH `write` and `state` GA addresses (not separate `ga_angle_set` / `ga_angle_state` fields):

```json
{
  "type": "knx/update_entity",
  "entity_id": "cover.foo",
  "platform": "cover",
  "data": {
    "entity": { "name": "Foo", "device_info": null, "entity_category": null },
    "knx": {
      "ga_up_down": { "write": "3/0/N", "passive": [] },
      "ga_stop": { "write": "3/1/N", "passive": [] },
      "ga_position_set": { "write": "3/2/N", "passive": [] },
      "ga_position_state": { "state": "3/3/N", "passive": [] },
      "ga_angle": { "write": "3/4/N", "state": "3/5/N", "passive": [] },
      "travelling_time_up": 25.0,
      "travelling_time_down": 25.0,
      "sync_state": true,
      "invert_updown": false,
      "invert_position": false,
      "invert_angle": false
    }
  }
}
```

After update, `supported_features` jumps from 15 → 207 (adds `SET_TILT_POSITION` 128 and `STOP_TILT` 64). HA reads `current_tilt_position` from the state GA. Reload the HomeKit Bridge config entry (REST POST `/api/config/config_entries/entry/<id>/reload`) so Apple Home picks up the new tilt slider.

### Dashboard Management (Lovelace)

Dashboard operations require WebSocket API (not available via REST).

**List dashboards:**
```json
{
  "id": 1,
  "type": "lovelace/dashboards/list"
}
```

**Get dashboard config:**
```json
{
  "id": 2,
  "type": "lovelace/config",
  "url_path": null
}
```

**Save dashboard config:**
```json
{
  "id": 3,
  "type": "lovelace/config/save",
  "config": {
    "title": "Home",
    "views": [...]
  },
  "url_path": null
}
```

> **Note**: Use `scripts/dashboard_api.py` for dashboard operations - it handles WebSocket authentication and message flow.

## Error Handling

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created (new entity state) |
| 400 | Bad request (invalid JSON or parameters) |
| 401 | Unauthorized (missing/invalid token) |
| 404 | Not found (entity doesn't exist) |
| 405 | Method not allowed |

**Error response:**
```json
{
  "message": "Entity not found: light.nonexistent"
}
```

## Rate Limiting

No official rate limits, but recommended:
- Max 10 requests/second for normal operations
- Use WebSocket for real-time updates instead of polling
- Cache entity states when possible

## Common Use Cases

### 1. Turn on light when sensor triggered
```python
# Check sensor
state = GET /api/states/binary_sensor.motion_hallway

if state['state'] == 'on':
    # Turn on light
    POST /api/services/light/turn_on
    {"entity_id": "light.hallway"}
```

### 2. Get all lights and their states
```python
states = GET /api/states
lights = [s for s in states if s['entity_id'].startswith('light.')]
```

### 3. Create custom sensor
```python
POST /api/states/sensor.custom_counter
{
  "state": "42",
  "attributes": {
    "unit_of_measurement": "items",
    "friendly_name": "My Counter"
  }
}
```

## Resources

- **Official REST API Docs**: https://developers.home-assistant.io/docs/api/rest/
- **Home Assistant Core**: https://www.home-assistant.io/
- **API Integration**: https://www.home-assistant.io/integrations/api/
- **WebSocket API**: https://developers.home-assistant.io/docs/api/websocket/

## Sources

- [REST API | Home Assistant Developer Docs](https://developers.home-assistant.io/docs/api/rest/)
- [Home Assistant API Integration](https://www.home-assistant.io/integrations/api/)
