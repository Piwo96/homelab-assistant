# UniFi Protect API Reference

## Integration API v1 (Primary)

Official REST API with API key authentication.

### Base URL

```
https://{host}/proxy/protect/integration/v1
```

### Authentication

```
X-API-Key: your-api-key
Accept: application/json
```

Get API key: UniFi OS > Protect > Settings > Integration API > Create API Key

### Endpoints

#### Meta

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/meta/info` | Application version |

Response: `{"applicationVersion": "string"}`

#### Cameras

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/cameras` | List all cameras |
| GET | `/cameras/{id}` | Camera details |
| PATCH | `/cameras/{id}` | Update camera settings |
| GET | `/cameras/{id}/snapshot` | Get snapshot image |

**Snapshot query params:** `?highQuality=true`

**Camera response fields:**
- `id`, `modelKey`, `state`, `name`, `mac`
- `isMicEnabled`, `micVolume`
- `osdSettings` (overlay: name, date, logo, debug, location)
- `ledSettings` (isEnabled, welcomeLed, floodLed)
- `lcdMessage` (type, resetAt, text) - for doorbells
- `videoMode`, `hdrType`, `activePatrolSlot`
- `featureFlags` (supportFullHdSnapshot, hasHdr, smartDetectTypes, smartDetectAudioTypes, videoModes, hasMic, hasLedStatus, hasSpeaker)
- `smartDetectSettings` (objectTypes, audioTypes)

**Camera PATCH body:**
```json
{
  "name": "string",
  "osdSettings": {"isNameEnabled": true, "isDateEnabled": true, "isLogoEnabled": true, "isDebugEnabled": true, "overlayLocation": "topLeft"},
  "ledSettings": {"isEnabled": true, "welcomeLed": true, "floodLed": true},
  "lcdMessage": {"type": "LEAVE_PACKAGE_AT_DOOR"},
  "videoMode": "default",
  "smartDetectSettings": {"objectTypes": ["person", "vehicle"], "audioTypes": ["alrmSmoke"]}
}
```

#### PTZ Controls

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/cameras/{id}/ptz/goto/{slot}` | Move to preset (slot 0-4) |
| POST | `/cameras/{id}/ptz/patrol/start/{slot}` | Start patrol (slot 0-4) |
| POST | `/cameras/{id}/ptz/patrol/stop` | Stop active patrol |

All return 204 (no content).

#### RTSPS Streams

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/cameras/{id}/rtsps-stream` | Create RTSPS streams |
| GET | `/cameras/{id}/rtsps-stream` | Get existing streams |
| DELETE | `/cameras/{id}/rtsps-stream` | Delete streams |

**Create body:** `{"qualities": ["high", "medium", "low"]}`

**Response:** `{"high": "rtsps://...", "medium": "rtsps://...", "low": "rtsps://...", "package": "rtsps://..."}`

**Delete query:** `?qualities=high,medium`

#### Talkback

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/cameras/{id}/talkback-session` | Create talkback session |

Response: `{"url": "...", "codec": "...", "samplingRate": 0, "bitsPerSample": 0}`

#### NVR

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/nvrs` | NVR details |

Response: `{"id": "...", "modelKey": "...", "name": "...", "doorbellSettings": {...}}`

Note: Returns object (not list). Doorbell settings include `defaultMessageText`, `customMessages`, `customImages`.

#### Sensors

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sensors` | List all sensors |
| GET | `/sensors/{id}` | Sensor details |
| PATCH | `/sensors/{id}` | Update settings |

**Sensor response fields:**
- `id`, `modelKey`, `state`, `name`, `mac`, `mountType`
- `batteryStatus` (percentage, isLow)
- `stats` (light/humidity/temperature: value + status)
- `lightSettings`, `humiditySettings`, `temperatureSettings` (isEnabled, margin, thresholds)
- `isOpened`, `openStatusChangedAt`
- `isMotionDetected`, `motionDetectedAt`, `motionSettings`
- `alarmTriggeredAt`, `alarmSettings`
- `leakDetectedAt`, `externalLeakDetectedAt`, `leakSettings`
- `tamperingDetectedAt`

#### Lights

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lights` | List all lights |
| GET | `/lights/{id}` | Light details |
| PATCH | `/lights/{id}` | Update light settings |

**Light control (on/off):**
```json
{"isLightForceEnabled": true}
```

**Full light settings:**
```json
{
  "name": "string",
  "isLightForceEnabled": true,
  "lightModeSettings": {"mode": "string", "enableAt": "string"},
  "lightDeviceSettings": {"isIndicatorEnabled": true, "pirDuration": 0, "pirSensitivity": 0, "ledLevel": 0}
}
```

**Light response fields:**
- `id`, `modelKey`, `state`, `name`, `mac`
- `lightModeSettings`, `lightDeviceSettings`
- `isDark`, `isLightOn`, `isLightForceEnabled`
- `lastMotion`, `isPirMotionDetected`
- `camera` (paired camera ID)

#### Chimes

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/chimes` | List all chimes |
| GET | `/chimes/{id}` | Chime details |
| PATCH | `/chimes/{id}` | Update settings |

**Response:**
```json
{
  "id": "string", "modelKey": "string", "state": "CONNECTED",
  "name": "string", "mac": "string",
  "cameraIds": ["doorbell-id"],
  "ringSettings": [{"cameraId": "...", "repeatTimes": 0, "ringtoneId": "...", "volume": 0}]
}
```

#### Viewers

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/viewers` | List all viewers |
| GET | `/viewers/{id}` | Viewer details |
| PATCH | `/viewers/{id}` | Update viewer |

Response: `{"id": "...", "modelKey": "...", "state": "CONNECTED", "name": "...", "mac": "...", "liveview": "...", "streamLimit": 0}`

#### Live Views

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/liveviews` | List all live views |
| GET | `/liveviews/{id}` | Live view details |
| POST | `/liveviews` | Create live view |
| PATCH | `/liveviews/{id}` | Update live view |

**Response:**
```json
{
  "id": "string", "modelKey": "string", "name": "string",
  "isDefault": true, "isGlobal": true, "owner": "string",
  "layout": 4,
  "slots": [{"cameras": ["cam-id"], "cycleMode": "motion", "cycleInterval": 0}]
}
```

#### Alarm Manager

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/alarm-manager/webhook/{id}` | Trigger configured alarms |

Returns 204 on success, 400 on error.

#### File Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/files/{fileType}` | Upload device asset |
| GET | `/files/{fileType}` | List device assets |

#### WebSocket Subscriptions

| Endpoint | Description |
|----------|-------------|
| `/subscribe/devices` | Device add/update/remove events |
| `/subscribe/events` | Protect event notifications (ONLY method for events) |

**Device subscription:** `{"type": "add|update|remove", "item": {...}}`
**Event subscription:** `{"type": "add|update", "item": {"id": "...", "modelKey": "...", "type": "...", "start": 0, "end": null, "device": "..."}}`

> **CRITICAL**: The Integration API v1 does NOT provide a REST endpoint for querying historical events. Events are only available through WebSocket streaming. To query events by time range, camera, or type, you MUST use the Legacy API `/events` endpoint.

---

## Legacy API (Events Fallback)

Internal API for events/detections. Used when Integration API v1 has no REST endpoint for historical events.

### Base URL

```
https://{host}/proxy/protect/api
```

### Authentication

Cookie-based session via UniFi Controller login:
```
POST https://{host}/api/auth/login
{"username": "...", "password": "..."}
```

### Events Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/events` | List events |
| GET | `/events?start={ms}&end={ms}` | Events in timerange |
| GET | `/events?types=motion,ring` | Filter by type |

**Query parameters:**
- `start` - Unix timestamp in milliseconds
- `end` - Unix timestamp in milliseconds
- `types` - Comma-separated: `motion`, `ring`, `smartDetectZone`

**Event types:**
- `motion` - Motion detected
- `ring` - Doorbell ring
- `smartDetectZone` - Smart detection (person, vehicle, plate, face)

---

## API Differences

| Aspect | Integration API v1 | Legacy API |
|--------|-------------------|------------|
| Auth | `X-API-Key` header | Cookie + CSRF token |
| Base URL | `/proxy/protect/integration/v1` | `/proxy/protect/api` |
| Events | WebSocket only (no REST) | REST `GET /events` |
| NVR | `GET /nvrs` (object) | `GET /nvr` (object) |
| Light on/off | `{"isLightForceEnabled": true}` | `{"lightOnSettings": {"isLedForceOn": true}}` |
| Snapshot | `?highQuality=true` | `?w=1920&h=1080&q=80` |
| Camera fields | Extended (OSD, LED, LCD, features) | Basic |
| Sensor fields | Extended (stats, leak, alarm, tamper) | Basic |

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 204 | Success (no content - PTZ, alarm) |
| 400 | Bad request |
| 401 | Invalid API key or session expired |
| 403 | Forbidden |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Server error |

## Rate Limits

No official limits documented. Recommended:
- Snapshots: Max 1/second per camera
- Events: Max 10 requests/minute
- Live streams: Max 4 concurrent per camera

## Sources

- [UniFi Protect Integration API](https://developer.ui.com/protect/v6.2.83/gettingstarted)
