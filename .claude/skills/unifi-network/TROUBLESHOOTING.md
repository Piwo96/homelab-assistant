# UniFi Network Troubleshooting

Known issues and solutions. This document grows through self-annealing.

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

### Login Failed
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
**Cause**: API requires local authentication.
**Solution**:
1. Log into UniFi web UI
2. Settings → Admins → Add Admin
3. Create local-only admin with desired permissions
4. Use these credentials in `.env`

### Session Expired
```
Error: 401 - Session expired
```
**Cause**: Cookie-based session timed out.
**Solution**:
1. Script should handle re-authentication automatically
2. If persistent: check if another session invalidated yours
3. Verify credentials still valid

## API Compatibility Issues

### Different API Paths
**Cause**: UCG, UDM, and Controller have slightly different APIs.
**Solution**:

| Device | Base Path | Notes |
|--------|-----------|-------|
| UCG/UDM | `/proxy/network/api/` | Built-in controller |
| Cloud Controller | `/api/` | Standalone controller |
| Self-hosted | `/api/` | Docker/VM controller |

### Endpoint Not Found
```
Error: 404 Not Found
```
**Cause**: API endpoint differs by firmware version.
**Solution**:
1. Check UniFi firmware version
2. Consult API.md for version-specific endpoints
3. Try alternative endpoint paths

## Operation Issues

### Client Not Found
**Cause**: Client recently disconnected or on different site.
**Solution**:
1. Use `--all` flag to include disconnected clients
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

### Locate Device LED Not Blinking
**Cause**: Feature not supported or device busy.
**Solution**:
1. Not all devices support locate function
2. Check device is fully adopted
3. Some devices only support this when idle

## Multi-Site Issues

### Wrong Site Data
```
Data returned is for different location
```
**Cause**: Wrong `UNIFI_SITE` configured.
**Solution**:
1. List sites: `network_api.py sites`
2. Site names are usually `default` for single site
3. Multi-site: use exact site name from web UI

### Site Not Found
```
Error: Site 'mysite' not found
```
**Cause**: Site name doesn't match exactly.
**Solution**:
1. Site names are case-sensitive
2. Use site ID instead of name if unsure
3. Check site exists in web UI

## Performance Issues

### Slow Client List
**Cause**: Large number of clients or slow connection.
**Solution**:
1. Use `--limit` flag to reduce results
2. Filter by network or AP if supported
3. Cache results for repeated queries

### API Rate Limiting
**Cause**: Too many requests.
**Solution**:
1. Add delays between bulk operations
2. UniFi doesn't officially document rate limits
3. If persistent: reduce request frequency

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
