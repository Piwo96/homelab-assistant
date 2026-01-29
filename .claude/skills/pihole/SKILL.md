---
name: pihole
description: DNS und Werbeblocker verwalten - Statistiken, Blocklisten, DNS-Anfragen, Domains sperren/erlauben
version: 1.2.0
author: Philipp Rollmann
tags:
  - homelab
  - dns
  - pihole
  - adblock
  - network
requires:
  - python3
  - requests
triggers:
  - /pihole
intent_hints:
  - "Werbung geblockt, wie viele Anfragen"
  - "DNS-Statistiken, DNS-Status"
  - "Domain sperren oder freigeben"
  - "Blockliste, Allowliste verwalten"
  - "Pi-hole aktivieren/deaktivieren"
  - "Welche Domains werden geblockt"
  - "DNS-Auflösung, DNS-Probleme"
---

# Pi-hole Management

Manage Pi-hole DNS server: control ad-blocking, manage lists, view statistics, and analyze DNS queries.

## Goal

Automate Pi-hole administration without needing the web UI.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `PIHOLE_HOST` | `.env` | Yes | Pi-hole server IP/hostname |
| `PIHOLE_PASSWORD` | `.env` | Yes | Web UI password (for API auth) |
| `PIHOLE_PORT` | `.env` | No | Web port (default: 80) |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/pihole_api.py` | CLI for all Pi-hole operations |

## Outputs

- **Human-readable format** (default): Formatted statistics with emoji indicators
- **JSON format** (`--json` flag): Raw API responses for scripting
- **Status messages**: Action confirmations (enable/disable/block/allow)
- **Error messages**: Sent to stderr with "Error:" prefix
- **Version detection**: Displays detected API version on stderr

All commands support `--json` flag for machine-readable output.

## Quick Start

1. Configure `.env`:
   ```bash
   PIHOLE_HOST=pihole.local
   PIHOLE_PASSWORD=your-web-password
   ```

2. Test connection:
   ```bash
   python .claude/skills/pihole/scripts/pihole_api.py summary
   ```

## Programmatic Usage

The script exposes an `execute()` function for direct Python integration:

```python
from skills.pihole.scripts.pihole_api import execute

# Get summary
data = execute("summary", {})

# Block domain
execute("block", {"domain": "ads.example.com", "comment": "Blocked"})

# Disable with duration
execute("disable", {"duration": 300})

# Query with filters
queries = execute("queries", {"domain": "google.com"})
```

See script docstring for available actions and arguments.

## Resources

- **[API.md](API.md)** - REST API reference and authentication
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Statistics
pihole_api.py summary                     # Overview stats
pihole_api.py status                      # Blocking enabled/disabled
pihole_api.py top-domains --count 10      # Most queried domains
pihole_api.py top-clients --count 10      # Most active clients
pihole_api.py info                        # Pi-hole version and system info

# Blocking Control
pihole_api.py enable                      # Enable blocking
pihole_api.py disable                     # Disable permanently
pihole_api.py disable --duration 300      # Disable for 5 minutes

# List Management (v6 only)
pihole_api.py block example.com           # Add to blocklist
pihole_api.py allow example.com           # Add to allowlist
pihole_api.py block example.com --comment "Tracking domain"  # With comment
pihole_api.py lists                       # Show all lists

# Query Analysis
pihole_api.py queries                     # Recent DNS queries (all)
pihole_api.py queries --domain example.com    # Filter by domain
pihole_api.py queries --client 192.168.1.100  # Filter by client

# Gravity Management (v6 only)
pihole_api.py gravity-update              # Update gravity database
```

## Workflows

### Troubleshoot Blocked Site
1. User reports site not working
2. Check recent queries: `queries --domain problematic-site.com`
3. If domain is being blocked, add to allowlist: `allow problematic-site.com`
4. Verify by checking queries again or testing the site

### Temporary Disable for Testing
1. Disable: `disable --duration 600` (10 minutes)
2. Test website/app
3. Blocking re-enables automatically
4. Or manually: `enable`

### Block Unwanted Domain
1. Identify domain from logs or user request
2. Block: `block tracking.example.com --comment "User requested"`
3. Verify with: `lists` (check blocklist section)
4. Note: Requires Pi-hole v6 for API-based blocking

### Analyze Network DNS Usage
1. View summary: `summary`
2. Top domains: `top-domains`
3. Top clients: `top-clients`
4. Query types: `query-types`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Wrong password | 401 or empty response | Verify password matches web UI |
| Pi-hole v5 vs v6 | API auto-detects version | v5: list management requires web UI; v6: full API support |
| List management on v5 | "requires web interface" error | Upgrade to v6 or use web UI for blocklist/allowlist changes |
| Domain already in list | Operation succeeds silently | Check `lists` before adding |
| Wildcard domains | Use `*.example.com` syntax | Check Pi-hole docs for regex support |
| Disable without duration | Stays disabled forever | Always use `--duration` or remember to `enable` |
| Script path | Commands may fail | Use full path: `python .claude/skills/pihole/scripts/pihole_api.py` |

## Related Skills

- [/unifi-network](../unifi-network/SKILL.md) - Network-level DNS settings
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
