# UniFi Network Troubleshooting

Known issues and solutions. This document grows through self-annealing.

## Dual-API Mode Issues

### Understanding API Routing

The skill routes commands intelligently based on available credentials:

**Integration API preferred** (if `UNIFI_API_KEY` set):
- clients, devices, networks, wifis → Integration API with Legacy fallback
- device-stats, pending-devices, power-cycle-port → Integration API only
- client-detail, authorize-guest, network CRUD, wifi CRUD → Integration API only

**Legacy API only** (requires `UNIFI_USERNAME` + `UNIFI_PASSWORD`):
- kick, block, unblock → Legacy API only
- health, sysinfo, dpi-stats → Legacy API only
- port-forwards, firewall-rules, firewall-groups → Legacy API only

**Both APIs** (if both credentials set):
- All features available
- Dual-routed commands use Integration API first, Legacy as fallback

**Design principle**: Commands fail explicitly (RuntimeError) when required API is unavailable rather than silently degrading.

### Dual-Routing Fallback Failure
```
RuntimeError: Integration API: Invalid API key (401)
Command crashes instead of falling back to Legacy API
```
**Cause**: When Integration API fails with an error (401, 403, etc.), dual-routed commands (clients, devices, networks, wifis) did not fall back to Legacy API as expected.
**Root cause**: Error responses from Integration API raised RuntimeError before fallback logic could execute.
**Solution**: Fixed in `network_api.py` with `_dual_route()` helper that catches RuntimeError and automatically retries with Legacy API when Integration fails. No user action needed if using latest version.

### API Key Invalid or Expired
```
RuntimeError: Integration API: Invalid API key (401)
```
**Cause**: API key is invalid, expired, or revoked.
**Solution**:
1. Log into UniFi web UI
2. Settings → API → Check/recreate API key
3. Update `UNIFI_API_KEY` in `.env`

### Feature Requires Integration API
```
RuntimeError: 'device-stats' requires Integration API v1 (UNIFI_API_KEY)
```
**Cause**: Tried to use Integration API feature without API key.
**Solution**:
1. Create API key in UniFi web UI (Settings → API)
2. Add `UNIFI_API_KEY=your-key` to `.env`

### Feature Requires Legacy API
```
RuntimeError: 'kick' requires Legacy API (UNIFI_USERNAME + UNIFI_PASSWORD)
```
**Cause**: Tried to use Legacy-only feature without credentials.
**Solution**:
1. Add `UNIFI_USERNAME` and `UNIFI_PASSWORD` to `.env`
2. Must use LOCAL admin account, not cloud account

### Site UUID Resolution Failed
```
RuntimeError: Site 'mysite' not found. Available: Default, Office
```
**Cause**: `UNIFI_SITE` name doesn't match any site in the Integration API.
**Solution**:
1. Run `python network_api.py sites` to see available site names
2. Update `UNIFI_SITE` in `.env` to match exactly
3. Site names are case-insensitive but must match

### Integration API Not Available (Firmware)
```
ConnectionError: Cannot connect to Integration API
```
**Cause**: UniFi firmware may not support Integration API (requires recent firmware).
**Solution**:
1. Update UniFi firmware to latest version
2. Cloud connector requires firmware >= 5.0.3
3. Fall back to Legacy API by removing `UNIFI_API_KEY`

## Connection Issues

### SSL Certificate Error
```
requests.exceptions.SSLError: certificate verify failed
```
**Cause**: Self-signed certificate on UniFi device.
**Solution**: Set `UNIFI_VERIFY_SSL=false` in `.env`.

### Connection Refused
```
Error: Cannot connect to 192.168.1.1:443
```
**Cause**: Wrong IP, wrong port, or device not accessible.
**Solution**:
1. Verify IP is correct (gateway IP, not controller)
2. Check if device is reachable: `ping $UNIFI_HOST`
3. For UCG/UDM: port 443, for Controller: check configured port

### Login Failed (Legacy API)
```
Error: 401 Unauthorized
```
**Cause**: Wrong credentials or cloud-only account.
**Solution**:
1. Verify username/password are correct
2. **Important**: Must use LOCAL admin account, not Ubiquiti cloud account
3. Create local admin: Settings → Admins → Add Admin → Local Access Only

## Authentication Issues

### Cloud Account Not Working
**Cause**: Legacy API requires local authentication.
**Solution**:
1. Log into UniFi web UI
2. Settings → Admins → Add Admin
3. Create local-only admin with desired permissions
4. Use these credentials in `.env`

### Session Expired (Legacy API)
```
Error: 401 - Session expired
```
**Cause**: Cookie-based session timed out.
**Solution**:
1. Script handles re-authentication automatically
2. If persistent: clear cache `rm ~/.cache/homelab/unifi_session_*.pkl`
3. Verify credentials still valid

## API Compatibility Issues

### Different Response Formats
**Cause**: Integration API and Legacy API return different field names.
**Solution**:

| Field | Integration API | Legacy API |
|-------|----------------|------------|
| Device state | `"ONLINE"` / `"OFFLINE"` | `1` / `0` |
| MAC address | `macAddress` | `mac` |
| IP address | `ipAddress` | `ip` |
| Client type | `type: "WIRED"` | `is_wired: true` |
| WiFi security | `securityConfiguration.type` | `security` |
| VLAN | `vlanId` | `vlan` |
| Device ID | UUID string | MAC-based |

### UUID vs MAC Identifiers
**Cause**: Integration API uses UUIDs, Legacy API uses MAC addresses.
**Solution**:
1. For Integration API commands, use UUID from `devices` or `clients` output
2. For Legacy API commands (kick, block), use MAC address
3. `restart-device` accepts both (UUID for Integration, MAC for Legacy)

### Display Format Mismatch After Fallback
**Cause**: When dual-routed commands fall back from Integration API to Legacy API, display code may use wrong field names because `has_integration` flag doesn't reflect which API actually served the request.
**Symptom**: Data displays incorrectly or KeyError on field access after fallback.
**Solution**: Fixed in `network_api.py` by tracking `_last_source` attribute that indicates which API served the most recent request. Display logic now checks `_last_source` instead of `has_integration`. No user action needed if using latest version.

### Response Object Falsy Check
**Cause**: Python `requests.Response` objects with 4xx/5xx status codes are falsy (`bool(response) == False`). Using `if response:` incorrectly treats error responses as None.
**Symptom**: Error handler skips error responses, causing wrong execution path.
**Solution**: Fixed in `network_api.py` by using `response is not None` instead of `if response:`. This is an implementation detail, no user impact.

### Endpoint Not Found
```
Error: 404 Not Found
```
**Cause**: API endpoint differs by firmware version.
**Solution**:
1. Check UniFi firmware version
2. Consult API.md for endpoint-specific details
3. Try alternative endpoint paths

## Operation Issues

### Client Not Found
**Cause**: Client recently disconnected or on different site.
**Solution**:
1. Use `--all` flag to include disconnected clients (Legacy)
2. Verify correct `UNIFI_SITE` in `.env`
3. Client may be on guest network with different visibility

### Device Restart No Effect
**Cause**: Device busy or command not received.
**Solution**:
1. Wait 30 seconds, try again
2. Check device is adopted (not pending)
3. Try from web UI to verify device responsiveness
4. Check device isn't in "isolated" state

### Block Not Working
**Cause**: Client reconnects with different MAC (randomization).
**Solution**:
1. Many devices use MAC randomization
2. Block by device fingerprint if available
3. Create firewall rule instead for more persistent blocking

### Pagination Returns Empty
**Cause**: Offset beyond total count, or no matching results.
**Solution**:
1. Check `totalCount` in JSON output
2. Start with `--offset 0`
3. Verify filter syntax if using filtering

### --json Flag Not Recognized
```
error: unrecognized arguments: --json
```
**Cause**: Global flags like `--json` and `--site` were only defined on parent parser but not inherited by subparsers.
**Symptom**: Using `command --json` or `command --site X` fails with "unrecognized arguments" error.
**Solution**: Fixed in `network_api.py` by using `parents=[common]` pattern so all subcommands inherit global flags. Use `--json` after command name: `python network_api.py clients --json`. No user action needed if using latest version.

## Multi-Site Issues

### Wrong Site Data
```
Data returned is for different location
```
**Cause**: Wrong `UNIFI_SITE` configured.
**Solution**:
1. Run `python network_api.py sites` to see available sites
2. Set `UNIFI_SITE` in `.env` to match site name
3. Use `--site` flag for one-off commands

## Performance Issues

### Slow Client List
**Cause**: Large number of clients or slow connection.
**Solution**:
1. Use `--limit` flag to reduce results
2. Use pagination with `--offset`

### API Rate Limiting
```
RuntimeError: Integration API: Rate limit exceeded (429)
```
**Cause**: Too many requests.
**Solution**:
1. Add delays between bulk operations
2. Integration API has higher rate limits than Legacy
3. Reduce request frequency

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
