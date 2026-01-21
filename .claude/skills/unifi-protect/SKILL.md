---
name: unifi-protect
description: Manage UniFi Protect cameras, NVR, events, and smart home lighting
version: 1.1.0
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
protect_api.py camera-info <id>           # Camera details
protect_api.py snapshot <id>              # Display snapshot info
protect_api.py snapshot <id> --save photo.jpg  # Save snapshot

# Event Monitoring
protect_api.py events                     # Recent events
protect_api.py events --last 24h          # Last 24 hours
protect_api.py events --type motion       # Motion events only
protect_api.py events --type ring         # Doorbell rings
protect_api.py events --camera <id>       # Events for specific camera

# Recording Control
protect_api.py recording-status           # Recording status all cameras
protect_api.py enable-recording <id>      # Enable recording
protect_api.py disable-recording <id>     # Disable recording

# Smart Lighting
protect_api.py lights                     # List smart lights
protect_api.py light-on <id>              # Turn light on
protect_api.py light-off <id>             # Turn light off
protect_api.py light-brightness <id> 50   # Set brightness (0-100)
```

## Workflows

### Review Motion Events
1. List events: `events --type motion --last 12h`
2. Note camera and timestamp
3. Get snapshot: `snapshot <camera-id> --save evidence.jpg`
4. Or view in web UI for video playback

### Capture Evidence
1. Find camera: `cameras`
2. Take snapshot: `snapshot <id> --save incident-$(date +%Y%m%d-%H%M%S).jpg`
3. Review events: `events --camera <id> --last 1h`

### Disable Recording Temporarily
1. Check status: `recording-status`
2. Disable: `disable-recording <camera-id>`
3. Do maintenance/private activity
4. Re-enable: `enable-recording <camera-id>`

### Control Outdoor Lighting
1. List lights: `lights`
2. Turn on: `light-on <light-id>`
3. Adjust brightness: `light-brightness <light-id> 75`
4. Turn off when done: `light-off <light-id>`

### Monitor Doorbell
1. List recent rings: `events --type ring --last 24h`
2. Get snapshot of visitor: `snapshot <doorbell-id> --save visitor.jpg`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Self-signed SSL | Connection fails | Set `PROTECT_VERIFY_SSL=false` |
| Cloud-only account | Login fails | Create local admin account |
| Camera offline | Snapshot fails | Check camera status first |
| NVR disk full | Recording stops | Check storage in web UI |
| Event not found | Outside retention | Events deleted after retention period |
| Smart light unresponsive | Command ignored | Check light is adopted and online |

## Related Skills

- [/unifi-network](../unifi-network/SKILL.md) - Network device management
- [/homeassistant](../homeassistant/SKILL.md) - Home automation integration
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
