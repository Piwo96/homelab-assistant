# Pi-hole Operations Guide

Common operations using the CLI tool or direct API calls.

## Statistics

### Summary Stats
```bash
# Quick overview (no auth required)
python pihole_api.py summary

# Detailed stats
python pihole_api.py stats
```

### Top Lists
```bash
# Top 10 blocked domains
python pihole_api.py top-blocked

# Top 10 allowed domains
python pihole_api.py top-allowed

# Top 10 clients
python pihole_api.py top-clients
```

### Query History
```bash
# Recent queries
python pihole_api.py queries

# Filter by domain
python pihole_api.py queries --domain google.com

# Filter by client
python pihole_api.py queries --client 192.168.1.100

# Show only blocked queries
python pihole_api.py queries --blocked
```

## Blocking Control

### Enable/Disable
```bash
# Disable blocking permanently
python pihole_api.py disable

# Disable for 5 minutes
python pihole_api.py disable --duration 300

# Re-enable blocking
python pihole_api.py enable

# Check status
python pihole_api.py status
```

## Custom Lists

### Blocklist Management
```bash
# Add domain to blocklist
python pihole_api.py block example.com --comment "Blocked via API"

# Add regex to blocklist
python pihole_api.py block-regex "^ad[sz]?[0-9]*\\..*"

# List all blocked domains
python pihole_api.py list-blocked
```

### Allowlist Management
```bash
# Add domain to allowlist (whitelist)
python pihole_api.py allow example.com

# Add regex to allowlist
python pihole_api.py allow-regex ".*\\.safe\\.com$"

# List all allowed domains
python pihole_api.py list-allowed
```

### Remove from Lists
```bash
# Remove from blocklist
python pihole_api.py unblock example.com

# Remove from allowlist
python pihole_api.py unallow example.com
```

## Gravity (Blocklist Updates)

### Update Blocklists
```bash
# Pull latest blocklists and rebuild gravity
python pihole_api.py gravity-update

# Check gravity status
python pihole_api.py gravity-status
```

## System Management

### Service Control
```bash
# Restart Pi-hole services
python pihole_api.py restart

# Reboot system (caution!)
python pihole_api.py reboot
```

### Version Info
```bash
# Pi-hole version and system info
python pihole_api.py info
```

## Monitoring

### Real-time Stats
```bash
# Watch stats (updates every 5 seconds)
python pihole_api.py watch

# Show stats for last 24h
python pihole_api.py stats --hours 24
```

### Client Tracking
```bash
# List all clients seen in last 24h
python pihole_api.py clients

# Get details for specific client
python pihole_api.py client-info 192.168.1.100
```

## Bulk Operations

### Import Domains
```bash
# Import domains from file (one per line)
python pihole_api.py import-blocklist domains.txt

# Import allowlist
python pihole_api.py import-allowlist safe-domains.txt
```

### Export Lists
```bash
# Export current blocklist
python pihole_api.py export-blocklist > my-blocklist.txt

# Export allowlist
python pihole_api.py export-allowlist > my-allowlist.txt
```

## Troubleshooting

### Authentication Issues
```bash
# Test login
python pihole_api.py test-auth

# Check if password is correct
curl -X POST http://pihole.local/api/auth \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}'
```

### Connection Problems
1. Check if Pi-hole is reachable: `ping pihole.local`
2. Verify web interface: `curl http://pihole.local/admin`
3. Check container status: `python proxmox_api.py status pve-rollmann 102`

### DNS Not Blocking
1. Check blocking status: `python pihole_api.py status`
2. Verify gravity database: `python pihole_api.py gravity-status`
3. Update gravity: `python pihole_api.py gravity-update`
4. Check if domain is whitelisted: `python pihole_api.py list-allowed`

### Slow Queries
1. Check upstream DNS servers: `python pihole_api.py upstreams`
2. Verify network latency to Pi-hole
3. Check Pi-hole system resources via Proxmox

## Integration Examples

### Auto-disable During Work Hours
```bash
# Disable blocking 9 AM - 5 PM (e.g., for work sites)
0 9 * * 1-5 python pihole_api.py disable --duration 28800
```

### Daily Reports
```bash
# Email daily stats
0 0 * * * python pihole_api.py summary --json | mail -s "Pi-hole Daily" admin@example.com
```

### Block Domains from Threat Feed
```bash
# Import fresh threat list daily
0 3 * * * wget -O /tmp/threats.txt https://example.com/threats && \
  python pihole_api.py import-blocklist /tmp/threats.txt
```

## Legacy Commands (Pi-hole v5)

If using older Pi-hole version:

```bash
# Summary
curl "http://pihole.local/admin/api.php?summary"

# Enable/Disable with auth token
curl "http://pihole.local/admin/api.php?disable=300&auth=TOKEN"
curl "http://pihole.local/admin/api.php?enable&auth=TOKEN"
```

Get token from: `/etc/pihole/setupVars.conf` → `WEBPASSWORD`
