# UniFi Protect API Reference

Local API for camera and NVR management on UCG/UDM.

## Base URL

**UCG/UDM:**
```
https://{ucg-ip}/proxy/protect/api
```

Uses same authentication as UniFi Network API (session-based).

## Authentication

Reuses UniFi Controller session. Login via:
```
POST https://{ucg-ip}/api/auth/login
```

See [UniFi API.md](../unifi/API.md) for details.

## Common Endpoints

### Cameras

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cameras` | List all cameras |
| GET | `/cameras/{id}` | Get camera details |
| PATCH | `/cameras/{id}` | Update camera settings |
| GET | `/cameras/{id}/snapshot` | Get current snapshot |

### Events

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events` | List events |
| GET | `/events?start={unix}&end={unix}` | Events in timerange |
| GET | `/events?types=motion,ring` | Filter by type |

**Event types:**
- `motion` - Motion detected
- `ring` - Doorbell ring
- `smartDetectZone` - Smart detection (person, vehicle, etc.)

### Recordings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/video/export` | Export video clips |
| POST | `/video/export` | Create export job |

**Export format:**
```json
{
  "camera": "camera-id",
  "start": 1640000000000,
  "end": 1640003600000
}
```

### Live Streams

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cameras/{id}/live` | RTSP stream URL |
| POST | `/cameras/{id}/rtsp` | Create RTSP session |
| DELETE | `/cameras/{id}/rtsp/{session}` | End RTSP session |

**RTSP URL format:**
```
rtsp://{ucg-ip}:7447/{token}
```

### NVR

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nvr` | NVR information |
| GET | `/nvr/status` | Storage status |

### Other Devices

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sensors` | List sensors |
| GET | `/lights` | List lights |
| GET | `/chimes` | List chimes/doorbells |
| PATCH | `/lights/{id}` | Control light |

## WebSocket Updates

Real-time updates via WebSocket:

**Connect:**
```
wss://{ucg-ip}/proxy/protect/ws/updates
```

**Message types:**
- Device updates (camera online/offline, settings changed)
- Event notifications (motion, doorbell)
- Recording status

## Response Format

```json
{
  "id": "camera-id",
  "name": "Front Door",
  "type": "UVC G4 Doorbell",
  "state": "CONNECTED",
  "isOnline": true,
  "lastSeen": 1640000000000,
  "channels": [
    {
      "id": 0,
      "width": 1600,
      "height": 1200,
      "fps": 25,
      "bitrate": 2000
    }
  ]
}
```

## Camera Settings

Common PATCH operations:

### Recording Mode
```json
{
  "recordingSettings": {
    "mode": "always"  // always, motion, never
  }
}
```

### Privacy Zones
```json
{
  "privacyZones": [
    {
      "name": "Neighbor's Window",
      "color": "#FF0000",
      "points": [[100, 100], [200, 100], [200, 200], [100, 200]]
    }
  ]
}
```

### Smart Detection
```json
{
  "smartDetectSettings": {
    "objectTypes": ["person", "vehicle"],
    "audioTypes": ["smoke", "co"]
  }
}
```

## Snapshot Quality

Snapshots support quality parameter:
```
GET /cameras/{id}/snapshot?w=1920&h=1080&q=80
```

Parameters:
- `w` - Width
- `h` - Height
- `q` - Quality (0-100)

## Error Handling

HTTP status codes:
- `200` - Success
- `400` - Bad request (invalid parameters)
- `401` - Unauthorized (session expired)
- `404` - Camera/resource not found
- `500` - Server error

## Rate Limits

No official limits documented, but recommended:
- Snapshots: Max 1/second per camera
- Events: Max 10 requests/minute
- Live streams: Max 4 concurrent per camera

## Sources

- [UniFi Protect API Documentation](https://developer.ui.com/protect/v6.2.83/gettingstarted)
