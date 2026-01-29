# Pi-hole Troubleshooting

Known issues and solutions. This document grows through self-annealing.

## Connection Issues

### Empty Response / No Data
```
Error: Empty response from Pi-hole
```
**Cause**: Wrong password or API not enabled.
**Solution**:
1. Verify `PIHOLE_PASSWORD` matches web UI password
2. Check Pi-hole is running: `pihole status`
3. Verify API is accessible: `curl http://$PIHOLE_HOST/admin/api.php`

### Connection Refused
```
Error: Cannot connect to pihole.local:80
```
**Cause**: Wrong host, Pi-hole not running, or firewall.
**Solution**:
1. Verify hostname/IP: `ping $PIHOLE_HOST`
2. Check lighttpd: `systemctl status lighttpd`
3. Check port: `nc -zv $PIHOLE_HOST 80`

### DNS Resolution of Pi-hole Host Fails
```
Error: Could not resolve hostname
```
**Cause**: Using hostname when DNS is down (circular dependency - Pi-hole provides DNS).
**Solution**: Use IP address instead of hostname in `.env`:
```bash
PIHOLE_HOST=192.168.1.53  # Use IP, not pihole.local
```

**Why this happens**: If Pi-hole is your primary DNS server and it's down, your system can't resolve hostnames including `pihole.local`. Using an IP address bypasses DNS resolution.

## Authentication Issues

### 401 Unauthorized / Wrong Password
```
Error: Authentication failed
```
**Cause**: Password mismatch.
**Solution**:
1. Reset password: `pihole -a -p` (on Pi-hole server)
2. Update `PIHOLE_PASSWORD` in `.env`
3. Password is the **web interface password**, not sudo password

## Operation Issues

### Domain Not Being Blocked
**Cause**: Multiple possible reasons.
**Solution**:
1. Check recent queries: `pihole_api.py queries --domain example.com`
2. View lists to check if in blocklist or allowlist: `pihole_api.py lists` (v6 only)
3. Flush DNS cache on client: `ipconfig /flushdns` or `sudo dscacheutil -flushcache`
4. Update gravity: `pihole_api.py gravity-update` (v6) or `pihole -g` (on server)

### Changes Not Taking Effect
**Cause**: DNS caching.
**Solution**:
1. Restart Pi-hole DNS: `pihole restartdns` (on server)
2. Flush client DNS cache
3. Wait for TTL expiry

### Disable Duration Not Working
**Cause**: API limitation or format issue.
**Solution**:
1. Verify duration is in seconds (not minutes)
2. Use integer value: `--duration 300`
3. Check Pi-hole version - older versions may not support timed disable

## Pi-hole v5 vs v6 Differences

### API Endpoints Changed
**Cause**: Pi-hole v6 has new API structure.
**Solution**:
1. Script auto-detects version - no manual configuration needed
2. v5: Uses `/admin/api.php`
3. v6: Uses `/api/` with new endpoints
4. Check detected version in output: "Connected to Pi-hole (v5)" or "(v6)"

### Authentication Method Changed
**Cause**: v6 uses session-based authentication.
**Solution**:
1. v5: Uses API key if provided via `PIHOLE_API_KEY`
2. v6: Uses password to get session ID (SID), auto-renews on 401
3. Script handles both automatically

### List Management Not Available in v5
**Cause**: v5 API doesn't support blocklist/allowlist management.
**Error**: "Blocklist management requires web interface in v5"
**Solution**:
1. Upgrade to Pi-hole v6 for full API support
2. Or use web interface for list management
3. Or use SSH and `pihole` CLI commands

## Performance Issues

### Slow Query Response
**Cause**: Large query log or slow storage.
**Solution**:
1. Query log is limited to 20 entries by default in output
2. Use `--json` flag for programmatic access without formatting overhead
3. Check Pi-hole storage (SD card wear on Raspberry Pi)
4. Consider moving to faster storage

### High CPU on Pi-hole
**Cause**: Heavy DNS traffic or logging.
**Solution**:
1. Reduce query logging level in Pi-hole settings
2. Increase flush frequency
3. Consider scaling up hardware

## Script Issues

### ImportError: requests module not found
**Error**: "Error: 'requests' library required"
**Solution**: Install requests library: `pip install requests`

### Session Expired During Long Operations
**Cause**: v6 sessions expire after 300 seconds (5 minutes) by default.
**Behavior**: Script automatically re-authenticates on 401 errors.
**Solution**: If still failing, check password is correct.

### SSL/TLS Verification Warnings
**Cause**: Self-signed certificates or HTTP-only setup.
**Behavior**: SSL warnings are automatically suppressed in the script.
**Solution**: If you want SSL verification, set `verify_ssl=True` when initializing API.

### .env File Not Found
**Cause**: Script searches in multiple locations but can't find `.env`.
**Locations checked**:
1. Current working directory
2. Parent directory
3. 5 levels up (for nested script locations)
**Solution**: Create `.env` in project root with `PIHOLE_HOST` and `PIHOLE_PASSWORD`.

### HTTPS/HTTP Confusion
**Cause**: `PIHOLE_HOST` includes `http://` or `https://` prefix.
**Behavior**: Script strips these prefixes and uses HTTP by default.
**Note**: Pi-hole typically runs on HTTP (port 80) unless configured otherwise.
**Solution**: Set `PIHOLE_HOST=pihole.local` or `PIHOLE_HOST=192.168.1.53` (no protocol prefix).

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
