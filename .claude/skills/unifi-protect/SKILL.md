---
name: unifi-protect
description: Kameras, Aufnahmen, Bewegungsereignisse, Kennzeichen, Gesichter, Flutlichter, Klingeln, PTZ und Streams verwalten
version: 2.0.0
author: Philipp Rollmann
tags:
  - homelab
  - security
  - camera
  - nvr
  - unifi
  - surveillance
requires:
  - python3
  - requests
triggers:
  - /protect
intent_hints:
  - "Zeig mir die Überwachungskameras und ihren Status"
  - "Was hat die Kamera in der Einfahrt aufgenommen?"
  - "Welche Bewegungsereignisse gab es vor der Haustür?"
  - "Wurde ein Kennzeichen oder Nummernschild erkannt?"
  - "Wer hat an der Türklingel geklingelt?"
  - "Mach einen Kamera-Snapshot vom Garten"
  - "Schalte das Flutlicht der Überwachungskamera ein"
  - "Zeig mir die letzte Aufnahme der Überwachungskamera"
  - "Drehe die PTZ-Kamera zum Preset Terrasse"
  - "Welche Personen oder Fahrzeuge wurden erkannt?"
  - "Starte den RTSP Live-Stream der Kamera"
  - "Löse den Kamera-Alarm aus"
---

# UniFi Protect Management

Manage UniFi Protect: cameras, NVR recordings, motion events, snapshots, smart flood lights, chimes, PTZ controls, and RTSPS streams.

## Goal

Control UniFi Protect surveillance system via API without needing the web UI or mobile app.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `PROTECT_API_KEY` | `.env` | Recommended | Integration API v1 key (UI > Protect > Settings) |
| `PROTECT_HOST` | `.env` | No | NVR/UDMP IP (fallback: UNIFI_HOST) |
| `PROTECT_VERIFY_SSL` | `.env` | No | Verify SSL (default: false) |
| `UNIFI_HOST` | `.env` | Fallback | Used if PROTECT_HOST not set |
| `UNIFI_USERNAME` | `.env` | For events | Legacy auth for events/detections |
| `UNIFI_PASSWORD` | `.env` | For events | Legacy auth for events/detections |

## API Modes

| Mode | Credentials | Features |
|------|-------------|----------|
| **Integration** | `PROTECT_API_KEY` | Cameras, lights, sensors, chimes, PTZ, RTSPS, viewers, liveviews, alarm |
| **Legacy** | `UNIFI_USERNAME` + `UNIFI_PASSWORD` | All current features including events/detections |
| **Dual** (recommended) | All three | Full feature set: Integration primary + Legacy for events |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/protect_api.py` | CLI for all UniFi Protect operations |

## Outputs

- Camera and event lists in table or JSON format
- Snapshot images saved to disk
- Status messages for actions
- Error messages to stderr

## Quick Start

1. Configure `.env`:
   ```bash
   # Integration API v1 (recommended)
   PROTECT_API_KEY=your-api-key-here

   # Legacy API (needed for events/detections)
   UNIFI_HOST=192.168.1.1
   UNIFI_USERNAME=admin
   UNIFI_PASSWORD=your-password
   ```

2. Get API key: UniFi OS > Protect > Settings > Integration API > Create API Key

3. Test connection:
   ```bash
   python .claude/skills/unifi-protect/scripts/protect_api.py detect
   python .claude/skills/unifi-protect/scripts/protect_api.py cameras
   ```

## Resources

- **[API.md](./API.md)** - REST API reference and authentication
- **[TROUBLESHOOTING.md](./TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Connection & Info
protect_api.py detect                        # Show API mode
protect_api.py meta                          # Protect version

# Camera Management
protect_api.py cameras                       # List all cameras
protect_api.py camera <id>                   # Camera details
protect_api.py snapshot <id>                 # Save snapshot
protect_api.py snapshot <id> -o photo.jpg    # Save to specific file

# Event Monitoring (requires Legacy API)
protect_api.py events                        # Recent events
protect_api.py events --last 24h             # Last 24 hours
protect_api.py events --types motion         # Motion events only
protect_api.py events --types ring           # Doorbell rings
protect_api.py events --camera Einfahrt      # Filter by camera name

# Smart Detections (requires Legacy API)
protect_api.py detections --last 6h                    # All detections
protect_api.py detections --camera Einfahrt            # Filter by camera
protect_api.py detections --type plate                 # License plates only
protect_api.py detections --type face                  # Faces only
protect_api.py detections --type vehicle               # Vehicles only
protect_api.py detections --type person                # Persons only

# Smart Lighting
protect_api.py lights                        # List smart lights
protect_api.py light-on <id>                 # Turn light on
protect_api.py light-off <id>                # Turn light off

# Chimes / Doorbells
protect_api.py chimes                        # List chimes
protect_api.py chime <id>                    # Chime details

# PTZ Controls
protect_api.py ptz-goto <camera> <slot>      # Move to preset (0-4)
protect_api.py ptz-patrol-start <camera> <slot>  # Start patrol
protect_api.py ptz-patrol-stop <camera>      # Stop patrol

# RTSPS Streams
protect_api.py rtsps-stream <id>             # Create stream
protect_api.py rtsps-streams <id>            # List streams
protect_api.py rtsps-stream-delete <id>      # Delete stream

# Viewers & Live Views
protect_api.py viewers                       # List viewers
protect_api.py liveviews                     # List live views

# Alarm
protect_api.py alarm <webhook-id>            # Trigger alarm
```

## Workflows

### Check License Plates in Driveway
1. Query detections: `detections --camera Einfahrt --type plate --last 24h`
2. Output shows: Time, Plate Number, Vehicle Type, Color, Confidence
3. Take snapshot if needed: `snapshot <camera-id> -o evidence.jpg`

### Review Face Detections
1. Query faces: `detections --camera Einfahrt --type face --last 12h`
2. Output shows: Time, Confidence, Mask (Yes/No)
3. Note: Face **identification** (matching to known persons) is not available via API

### Review Motion Events
1. List events: `events --types motion --last 12h`
2. Note camera and timestamp
3. Get snapshot: `snapshot <camera-id> -o evidence.jpg`

### Capture Evidence
1. Find camera: `cameras`
2. Take snapshot: `snapshot <id> -o incident-$(date +%Y%m%d-%H%M%S).jpg`
3. Review events: `events --camera <camera-name> --last 1h`

### Control Outdoor Lighting
1. List lights: `lights`
2. Turn on: `light-on <light-id>`
3. Turn off when done: `light-off <light-id>`

### Monitor Doorbell
1. List recent rings: `events --types ring --last 24h`
2. Get snapshot of visitor: `snapshot <doorbell-id> -o visitor.jpg`
3. Check chime settings: `chimes`

### PTZ Camera Patrol
1. List cameras: `cameras` (find PTZ camera ID)
2. Start patrol: `ptz-patrol-start <camera> 0`
3. Or move to specific preset: `ptz-goto <camera> 2`
4. Stop patrol: `ptz-patrol-stop <camera>`

### Set Up RTSPS Stream
1. Create stream: `rtsps-stream <camera-id>`
2. Use returned URL in media player (VLC, ffplay, etc.)
3. Delete when done: `rtsps-stream-delete <camera-id>`

## Smart Detection Data

The `detections` command extracts data from `smartDetectZone` events:

### License Plates
- `plate`: Recognized plate number (e.g., "ABCD1234")
- `vehicle_type`: car, suv, van, truck, motorcycle
- `color`: white, black, gray, red, blue, etc.
- `confidence`: Recognition confidence (%)

### Faces
- `confidence`: Detection confidence (%)
- `has_mask`: Whether person wears a mask
- **Note**: Face identification (matching to known persons/face groups) is NOT available via API

### Vehicles
- Same as license plates but may not have plate number if not readable

### Persons
- `confidence`: Detection confidence (%)

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Self-signed SSL | Connection fails | Set `PROTECT_VERIFY_SSL=false` |
| Cloud-only account | Login fails | Create local admin account |
| Camera offline | Snapshot fails | Check camera status first |
| NVR disk full | Recording stops | Check storage in web UI |
| Event not found | Outside retention | Events deleted after retention period |
| Smart light unresponsive | Command ignored | Check light is adopted and online |
| Face not identified | API shows detection but no name | Face groups not accessible via API |
| Plate not readable | Vehicle detected but no plate | Low confidence, bad angle, or obscured plate |
| Camera name variations | Fuzzy matching enabled | "Einfahrt", "einfahrt", "Ein_fahrt" all match |
| No API key | Integration features unavailable | Set `PROTECT_API_KEY` in `.env` |
| No legacy credentials | Events/detections unavailable | Set `UNIFI_USERNAME` + `UNIFI_PASSWORD` |
| Invalid API key | 401 error | Regenerate key in Protect settings |

## Programmatic Access

For direct Python integration without CLI:

```python
from protect_api import execute

# Get cameras
cameras = execute("cameras", {})

# Get events for specific camera
events = execute("events", {"camera": "Einfahrt", "last": "24h"})

# Get license plate detections
plates = execute("detections", {"camera": "Einfahrt", "type": "plate", "last": "6h"})

# Save snapshot
execute("snapshot", {"id": "camera-id", "output": "photo.jpg"})

# Control lights
execute("light-on", {"id": "light-id"})
execute("light-off", {"id": "light-id"})

# New: Chimes, PTZ, RTSPS, etc.
execute("chimes", {})
execute("ptz-goto", {"camera": "Einfahrt", "slot": "0"})
execute("rtsps-stream", {"id": "camera-id"})
execute("alarm", {"id": "webhook-id"})
execute("detect", {})  # Check API mode
```

### Agent Output Formatting

The skill provides `format_agent_output(action, data) -> str|None` for compact, human-readable output when used via the agent system. This prevents large JSON responses (e.g., 54K chars of events) from timing out the LLM formatter and overwhelming end users.

Supported formatters: `events`, `detections`, `cameras`, `sensors`, `lights`, `nvr`

See [TROUBLESHOOTING.md](./TROUBLESHOOTING.md#large-json-response-times-out-llm-formatter) for details.

## Related Skills

- [/unifi-network](../unifi-network/SKILL.md) - Network device management
- [/homeassistant](../homeassistant/SKILL.md) - Home automation integration
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
