# Pi-hole Operations Guide

Common operations using the CLI tool. All commands use the script at `.claude/skills/pihole/scripts/pihole_api.py`.

> **Note**: Some operations require Pi-hole v6. The script auto-detects your version and uses the appropriate API.

## Available Commands

| Command | Auth | v5 | v6 | Description |
|---------|------|----|----|-------------|
| `info` | No | ✅ | ✅ | Pi-hole version and system info |
| `summary` | No | ✅ | ✅ | Summary statistics |
| `status` | No | ✅ | ✅ | Blocking status (enabled/disabled) |
| `enable` | Yes | ✅ | ✅ | Enable blocking |
| `disable` | Yes | ✅ | ✅ | Disable blocking (optional `--duration`) |
| `top-domains` | Yes | ✅ | ✅ | Top queried domains (`--count` optional) |
| `top-clients` | Yes | ✅ | ✅ | Top clients by query count |
| `queries` | Yes | ✅ | ✅ | Recent queries (`--domain`/`--client` filters) |
| `block` | Yes | ❌ | ✅ | Add domain to blocklist |
| `allow` | Yes | ❌ | ✅ | Add domain to allowlist |
| `lists` | Yes | ❌ | ✅ | Show all lists |
| `gravity-update` | Yes | ❌ | ✅ | Update gravity database |

## Statistics

### Summary Stats
```bash
# Quick overview (no auth required)
python pihole_api.py summary

# Blocking status
python pihole_api.py status

# System info and version
python pihole_api.py info
```

### Top Lists
```bash
# Top 10 queried domains
python pihole_api.py top-domains

# Top 10 domains with custom count
python pihole_api.py top-domains --count 25

# Top 10 clients
python pihole_api.py top-clients

# Top 10 clients with custom count
python pihole_api.py top-clients --count 20
```

### Query History
```bash
# Recent queries (last 20 displayed)
python pihole_api.py queries

# Filter by domain
python pihole_api.py queries --domain google.com

# Filter by client IP
python pihole_api.py queries --client 192.168.1.100

# JSON output for scripting
python pihole_api.py queries --json
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

> **Requires Pi-hole v6**: List management via API is only available in Pi-hole v6+. For v5, use the web interface.

### Blocklist Management
```bash
# Add domain to blocklist
python pihole_api.py block example.com

# Add with comment
python pihole_api.py block example.com --comment "Blocked via API"

# View all lists (includes blocklists)
python pihole_api.py lists
```

### Allowlist Management
```bash
# Add domain to allowlist (whitelist)
python pihole_api.py allow example.com

# Add with comment
python pihole_api.py allow safe-site.com --comment "Allowed for work"

# View all lists (includes allowlists)
python pihole_api.py lists
```

### Viewing Lists
```bash
# Show all lists (blocklists and allowlists)
python pihole_api.py lists

# JSON output for parsing
python pihole_api.py lists --json
```

> **Note**: To remove domains from lists, use the Pi-hole web interface or direct API calls (see API.md).

## Gravity (Blocklist Updates)

> **Requires Pi-hole v6**: Gravity management via API is only available in Pi-hole v6+.

### Update Blocklists
```bash
# Pull latest blocklists and rebuild gravity
python pihole_api.py gravity-update
```

## System Information

### Version Info
```bash
# Pi-hole version and system info
python pihole_api.py info
```

## Global Options

These options work with any command:

```bash
# JSON output (all commands)
python pihole_api.py <command> --json

# Override host from environment
python pihole_api.py <command> --host 192.168.1.53

# Override password from environment
python pihole_api.py <command> --password "mypassword"

# Combined
python pihole_api.py summary --json --host 192.168.1.53
```

## Output Formats

All commands support JSON output for scripting:

```bash
# JSON output
python pihole_api.py summary --json
python pihole_api.py top-domains --json
python pihole_api.py queries --json

# Parse with jq
python pihole_api.py summary --json | jq '.data.dns_queries_today'

# Check blocking status in script
if python pihole_api.py status --json | jq -r '.data.blocking' | grep -q true; then
    echo "Blocking is enabled"
fi
```

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for detailed issue resolution.

### Quick Checks

#### Authentication Issues
```bash
# Check if password is correct (v6)
curl -X POST http://pihole.local/api/auth \
  -H "Content-Type: application/json" \
  -d '{"password":"your-password"}'
```

#### Connection Problems
1. Check if Pi-hole is reachable: `ping pihole.local`
2. Verify web interface: `curl http://pihole.local/admin`
3. Test API connection: `python pihole_api.py summary`

#### DNS Not Blocking
1. Check blocking status: `python pihole_api.py status`
2. Update gravity (v6): `python pihole_api.py gravity-update`
3. Check recent queries: `python pihole_api.py queries --domain problematic-site.com`

## Integration Examples

### Auto-disable During Work Hours
```bash
# Cron: Disable blocking 9 AM - 5 PM (8 hours = 28800 seconds)
0 9 * * 1-5 cd /path/to/homelab-assistant && python .claude/skills/pihole/scripts/pihole_api.py disable --duration 28800
```

### Daily Reports
```bash
# Cron: Email daily stats
0 0 * * * cd /path/to/homelab-assistant && python .claude/skills/pihole/scripts/pihole_api.py summary --json | mail -s "Pi-hole Daily" admin@example.com
```

### Monitor Specific Domain
```bash
# Check if domain was queried recently
python pihole_api.py queries --domain ads.tracker.com --json | jq '.data | length'
```

## API Version Compatibility

The script auto-detects your Pi-hole version:

| Feature | v5 | v6 |
|---------|----|----|
| Summary stats | ✅ | ✅ |
| Blocking control | ✅ | ✅ |
| Top domains/clients | ✅ | ✅ |
| Query history | ✅ | ✅ |
| Blocklist/allowlist management | ❌ (use web UI) | ✅ |
| Gravity updates | ❌ (use CLI) | ✅ |

See [API.md](API.md) for direct API endpoint documentation.
