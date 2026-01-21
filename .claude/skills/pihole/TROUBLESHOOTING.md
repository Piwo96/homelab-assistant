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
**Cause**: Using hostname when DNS is down.
**Solution**: Use IP address instead of hostname in `.env`:
```bash
PIHOLE_HOST=192.168.1.53  # Use IP, not pihole.local
```

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
1. Check if in blocklist: `pihole_api.py query domain.com`
2. Check if in allowlist (overrides block)
3. Flush DNS cache on client: `ipconfig /flushdns` or `sudo dscacheutil -flushcache`
4. Check gravity updated: `pihole -g` (on server)

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
1. Check Pi-hole version: `pihole -v`
2. v5: Uses `/admin/api.php`
3. v6: Uses `/api/` with new endpoints
4. Update API.md with correct endpoints for your version

### Authentication Method Changed
**Cause**: v6 uses different auth mechanism.
**Solution**:
1. v5: Password via query parameter
2. v6: App password/token based
3. Check official docs for v6 API authentication

## Performance Issues

### Slow Query Response
**Cause**: Large query log or slow storage.
**Solution**:
1. Limit recent queries: `recent-queries --limit 100`
2. Check Pi-hole storage (SD card wear on Raspberry Pi)
3. Consider moving to faster storage

### High CPU on Pi-hole
**Cause**: Heavy DNS traffic or logging.
**Solution**:
1. Reduce query logging level in Pi-hole settings
2. Increase flush frequency
3. Consider scaling up hardware

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
