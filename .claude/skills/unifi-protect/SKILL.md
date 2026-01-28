---
name: unifi-protect
description: Kameras, Aufnahmen, Bewegungsereignisse, Kennzeichen, Gesichter und Flutlichter verwalten
version: 1.3.0
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
  - "Kameras, Überwachung, Aufnahmen"
  - "Was war vor der Tür, im Garten, in der Einfahrt"
  - "Bewegungsereignisse, Personen erkannt"
  - "Kennzeichen, Nummernschilder, Autos"
  - "Letztes Ereignis, was ist passiert"
  - "Kamera-Status, Snapshots, Bilder"
  - "Flutlicht an/aus, Licht bei Kamera"
---

# UniFi Protect Management

Manage UniFi Protect: cameras, NVR recordings, motion events, snapshots, and smart flood lights.

## Goal

Control UniFi Protect surveillance system via API without needing the web UI or mobile app.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `PROTECT_HOST` | `.env` | Yes | NVR/UDMP IP address |
| `PROTECT_USERNAME` | `.env` | Yes | Local admin username |
| `PROTECT_PASSWORD` | `.env` | Yes | Local admin password |
| `PROTECT_PORT` | `.env` | No | API port (default: 443) |
| `PROTECT_VERIFY_SSL` | `.env` | No | Verify SSL (default: false) |

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
   PROTECT_HOST=192.168.1.1
   PROTECT_USERNAME=admin
   PROTECT_PASSWORD=your-password
   ```

2. Test connection:
   ```bash
   python .claude/skills/unifi-protect/scripts/protect_api.py cameras
   ```

## Resources

- **[API.md](API.md)** - REST API reference and authentication
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Camera Management
protect_api.py cameras                    # List all cameras
protect_api.py camera <id>                # Camera details
protect_api.py snapshot <id>              # Save snapshot
protect_api.py snapshot <id> -o photo.jpg # Save to specific file

# Event Monitoring
protect_api.py events                     # Recent events
protect_api.py events --last 24h          # Last 24 hours
protect_api.py events --types motion      # Motion events only
protect_api.py events --types ring        # Doorbell rings
protect_api.py events --camera Einfahrt   # Filter by camera name
protect_api.py events --camera <id>       # Filter by camera ID

# Smart Detections (License Plates, Faces, Vehicles)
protect_api.py detections --last 6h                    # All detections
protect_api.py detections --camera Einfahrt            # Filter by camera
protect_api.py detections --type plate                 # License plates only
protect_api.py detections --type face                  # Faces only
protect_api.py detections --type vehicle               # Vehicles only
protect_api.py detections --type person                # Persons only
protect_api.py detections --camera Einfahrt --type plate  # Combined filters

# Smart Lighting
protect_api.py lights                     # List smart lights
protect_api.py light-on <id>              # Turn light on
protect_api.py light-off <id>             # Turn light off

# Kamera-Einstellungen ändern
protect_api.py update-camera <id> --settings '{"recordingSettings": {"mode": "always"}}'
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
   - Faces are detected but not matched to face groups
   - To identify known faces, use the Protect App: Detections > Faces

### Review Motion Events
1. List events: `events --types motion --last 12h`
2. Note camera and timestamp
3. Get snapshot: `snapshot <camera-id> -o evidence.jpg`
4. Or view in web UI for video playback

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

## Smart Detection Data

The `detections` command extracts data from `smartDetectZone` events. The API returns:

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
| Face not identified | API shows detection but no name | Face groups not accessible via API - use Protect App |
| Plate not readable | Vehicle detected but no plate | Low confidence, bad angle, or obscured plate |
| Camera name not found | Error message | Use `cameras` to list available names |

## Related Skills

- [/unifi-network](../unifi-network/SKILL.md) - Network device management
- [/homeassistant](../homeassistant/SKILL.md) - Home automation integration
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
