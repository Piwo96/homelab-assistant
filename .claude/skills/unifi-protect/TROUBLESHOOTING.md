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
Error: Camera with ID 'xxx' not found
```
**Cause**: Wrong ID or camera removed.
**Solution**:
1. List cameras: `protect_api.py cameras`
2. Use correct camera ID from list
3. Camera may have been removed/readopted with new ID

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

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
