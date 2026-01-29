# UniFi Protect Troubleshooting

Known issues and solutions. This document grows through self-annealing.

## Connection Issues

### SSL Certificate Error
```
requests.exceptions.SSLError: certificate verify failed
```
**Cause**: Self-signed certificate on UniFi device.
**Solution**: Set `PROTECT_VERIFY_SSL=false` in `.env`.

### Connection Refused
```
Error: Cannot connect to 192.168.1.1:443
```
**Cause**: Wrong IP, NVR offline, or firewall.
**Solution**:
1. Verify IP: `ping $PROTECT_HOST`
2. Check NVR status in UniFi Network app
3. Ensure port 443 accessible

### Login Failed
```
Error: 401 Unauthorized
```
**Cause**: Wrong credentials or cloud-only account.
**Solution**:
1. Must use LOCAL admin account, not Ubiquiti cloud account
2. Create local admin in UniFi OS: Settings → Admins → Add Admin
3. Verify password is correct

## Authentication Issues

### Cloud Account Not Working
**Cause**: Protect API requires local authentication.
**Solution**:
1. Log into UniFi OS web UI
2. Settings → Admins → Add Admin
3. Create local-only admin
4. Use these credentials in `.env`

### Session Issues
```
Error: Session expired or invalid
```
**Cause**: Session cookie invalidated.
**Solution**:
1. Script should auto-reauthenticate
2. If persistent: restart script
3. Check if credentials changed

## Camera Issues

### Camera Not Found
```
Error: Camera not found: Einfahrt
Available cameras: Haustür, Garten, Garage
```
**Cause**: Camera name doesn't match exactly or camera was removed.
**Solution**:
1. Script uses fuzzy matching - try variations: "Einfahrt", "einfahrt", "Ein_fahrt"
2. Name normalization ignores: underscores, hyphens, apostrophes, case
3. List cameras: `protect_api.py cameras`
4. Use exact camera ID if name matching fails
5. Camera may have been removed/readopted with new ID

**Fuzzy Matching Examples:**
- "Mailas Zimmer" matches "Mailas_Zimmer", "maila's zimmer", "mailas-zimmer"
- "Einfahrt" matches "einfahrt", "Ein_fahrt", "Ein-fahrt"
- Substring matching: "Tür" matches "Haustür"
- Typo tolerance: "Garagen" matches "Garage" (80% similarity)

### Snapshot Fails
```
Error: Failed to capture snapshot
```
**Cause**: Camera offline, busy, or no permissions.
**Solution**:
1. Check camera status: `protect_api.py camera-info <id>`
2. Verify camera is online
3. Some cameras don't support snapshot during certain operations

### Camera Offline
**Cause**: Network issue, power issue, or hardware failure.
**Solution**:
1. Check network connectivity to camera
2. Verify PoE power (if applicable)
3. Check camera LED status
4. Restart camera via web UI or `restart-camera <id>`

## Event Issues

### No Events Returned
**Cause**: No events in time range or wrong filter.
**Solution**:
1. Expand time range: `--last 7d`
2. Remove type filter to see all events
3. Check camera has motion detection enabled

### Event Outside Retention
```
Error: Event not found
```
**Cause**: Event deleted due to retention policy.
**Solution**:
1. Events are deleted after retention period
2. Check retention settings in Protect web UI
3. For important events: download/export promptly

## Recording Issues

### Recording Not Working
**Cause**: Recording disabled, disk full, or camera issue.
**Solution**:
1. Check status: `protect_api.py recording-status`
2. Enable if disabled: `enable-recording <id>`
3. Check NVR storage in web UI
4. Verify recording schedule allows current time

### Disk Full
```
Warning: NVR storage nearly full
```
**Cause**: Not enough space for new recordings.
**Solution**:
1. Check storage in Protect web UI
2. Reduce retention period
3. Lower recording quality
4. Add more storage if available

## Smart Light Issues

### Light Not Responding
**Cause**: Light offline, not adopted, or firmware issue.
**Solution**:
1. Check light status: `protect_api.py lights`
2. Verify light shows as "online"
3. Restart light via web UI
4. Check firmware is up to date

### Brightness Not Changing
**Cause**: Light busy or command format issue.
**Solution**:
1. Verify light ID is correct
2. Use value 0-100 for brightness
3. Try on/off first to verify connectivity

## API Compatibility

### Different Protect Versions
**Cause**: API changes between Protect versions.
**Solution**:
1. Check Protect version in web UI
2. Consult API.md for version-specific endpoints
3. Update script if needed for newer API

### UDMP vs UNVR Differences
**Cause**: Slightly different API paths.
**Solution**:
1. UDMP: Uses unified UniFi OS
2. UNVR: Dedicated NVR device
3. Base paths may differ - check API.md

## Script Errors

### AttributeError on Events/Detections
```
AttributeError: 'str' object has no attribute 'get'
```
**Cause**: API returned empty response as `{}` instead of expected list `[]`. When iterating over a dict, Python yields string keys, and calling `.get()` on strings fails.
**Root Issue**: `_protect_request()` returns `response.json() if response.text else {}`, meaning empty responses return dict instead of list.
**Solution**: Script now validates response types in `get_events()`, `get_cameras()`, and `get_detections()` before iterating. Non-list responses gracefully return empty lists.
**Pattern**: Always validate API response types before iteration when expecting lists - REST APIs may return dicts for errors/empty responses.

### NVR Uptime Shows Wrong Value
```
Example: Shows "30401 Tage" instead of "30 Tage"
```
**Cause**: Protect API returns `uptime` field in milliseconds, not seconds. Dividing by 86400 (seconds/day) instead of 86_400_000 (ms/day) produces values 1000x too large.
**Solution**: Always divide uptime by 86,400,000 to convert ms → days. Similarly for hours: divide by 3,600,000.
**Pattern**: UniFi APIs commonly use milliseconds for time durations - always verify units in API responses.

## Integration API v1 Issues

### Invalid API Key
```
RuntimeError: Protect Integration API: Invalid API key (401)
```
**Cause**: API key is invalid, expired, or not set.
**Solution**:
1. Check `PROTECT_API_KEY` in `.env`
2. Regenerate key: UniFi OS > Protect > Settings > Integration API
3. Ensure key has no extra whitespace

### Feature Requires Legacy API
```
RuntimeError: 'events' requires Legacy API (UNIFI_USERNAME + UNIFI_PASSWORD)
```
**Cause**: Events/detections are only available via the internal Legacy API. The official Integration API v1 has no REST endpoint for historical events - only WebSocket subscription (`GET /v1/subscribe/events`).
**Solution**:
1. Add `UNIFI_USERNAME` and `UNIFI_PASSWORD` to `.env`
2. Use a LOCAL admin account (not Ubiquiti cloud)
3. Both credentials together enable Dual mode (recommended)

> **Technical Note**: The Integration API v1 provides events exclusively through WebSocket streaming at `/proxy/protect/integration/v1/subscribe/events`. For querying historical events by time range, camera, or type, the Legacy API REST endpoint `/proxy/protect/api/events` must be used. This is why Dual mode (both credential types) is recommended for full functionality.

### Feature Requires Integration API
```
RuntimeError: 'ptz' requires Integration API v1 (PROTECT_API_KEY)
```
**Cause**: PTZ, chimes, RTSPS streams, viewers, liveviews, and alarm features require the Integration API v1.
**Solution**:
1. Add `PROTECT_API_KEY` to `.env`
2. Get key: UniFi OS > Protect > Settings > Integration API

### API Mode Detection
Run `protect_api.py detect` to see current API mode:
- **dual**: Both APIs available (recommended)
- **integration**: Only Integration API (no events/detections)
- **legacy**: Only Legacy API (no new features like PTZ, chimes)

## API Architecture Patterns

### ProtectDualAPI Facade
The `ProtectDualAPI` class implements a facade pattern that automatically routes requests to the correct API:
- **Integration API v1** (primary): Official API with API key auth (`X-API-Key` header)
- **Legacy API** (fallback): Internal API with cookie-based session auth

**Routing logic:**
- If operation supported by Integration API → use Integration API
- If operation only in Legacy API (events, detections) → use Legacy API
- Payloads automatically transformed between API formats

**Pattern benefits:**
1. Single interface for both APIs
2. Graceful fallback for missing credentials
3. Automatic payload translation (light control, NVR endpoints, snapshots)
4. Clear error messages when required credentials missing

### Why Two APIs?

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| Integration v1 has NO REST events endpoint | Cannot query historical events by time/camera/type | Keep Legacy API for `GET /events` |
| Legacy API lacks new features | No PTZ, chimes, RTSPS, alarm support | Use Integration API for modern features |
| Different auth mechanisms | API key vs username/password | `ProtectDualAPI` handles both transparently |

**Best practice**: Configure BOTH credential types (Dual mode) for full feature coverage.

## Migration from v1.x to v2.0

### Light Control Payload Changed
**Before (Legacy)**: `{"lightOnSettings": {"isLedForceOn": true}}`
**After (Integration)**: `{"isLightForceEnabled": true}`
**Impact**: Handled automatically by `ProtectDualAPI`. No user action needed.

### Snapshot Parameters Changed
**Before (Legacy)**: `?w=1920&h=1080&q=80`
**After (Integration)**: `?highQuality=true`
**Impact**: `--width` and `--height` CLI flags only work with Legacy API. Integration API uses `highQuality` boolean.

### NVR Endpoint Changed
**Before (Legacy)**: `GET /nvr` (singular)
**After (Integration)**: `GET /nvrs` (plural, returns object not list)
**Impact**: Handled automatically by `ProtectDualAPI.get_nvr()`.

### Authentication Headers Changed
**Before (Legacy)**: Cookie-based session (`POST /api/auth/login` → session cookie + CSRF token)
**After (Integration)**: API key header (`X-API-Key: your-api-key`)
**Impact**: `ProtectDualAPI` maintains separate sessions for each API type.

### Enhanced Response Data
**Integration API v1 returns richer fields:**
- **Cameras**: `featureFlags`, `smartDetectSettings`, `osdSettings`, `ledSettings`, `lcdMessage`
- **Sensors**: `stats` (light/temp/humidity), `leak`, `alarm`, `tampering` data
- **Lights**: `lightModeSettings`, `lightDeviceSettings`, motion detection state

**Benefit**: More granular control and status information without extra API calls.

## CLI Script Issues

### --json Flag Not Working After Subcommand
```
Example: `protect_api.py cameras --json` returns error
```
**Cause**: When using argparse with subcommands, flags on the parent parser only apply BEFORE the subcommand (e.g., `--json cameras`). The parser stops processing parent flags once it encounters the subcommand name.
**Solution**: Add global flags to both parent parser AND each subparser using `parents=[json_parent]`. This allows flags to work in both positions: `--json cameras` AND `cameras --json`.
**Pattern**: For flags that should work anywhere in the command, define them in a parent parser and pass via `parents=` to all subparsers.

### --last Duration Only Accepts Hours
```
Example: `--last 7d` or `--last 30m` returns error
```
**Cause**: Original implementation only parsed "h" suffix for hours.
**Solution**: Script now supports `_parse_duration()` helper that handles:
- **d** suffix: days (e.g., `--last 7d` = 7 days)
- **h** suffix: hours (e.g., `--last 24h` = 24 hours)
- **m** suffix: minutes (e.g., `--last 30m` = 30 minutes)
**Pattern**: Duration parsing should support common time units (d/h/m) with simple suffix detection for CLI ergonomics.

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
