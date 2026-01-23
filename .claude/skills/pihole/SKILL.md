---
name: pihole
description: Manage Pi-hole DNS and ad-blocking - queries, blocklists, allowlists, and statistics
version: 1.1.0
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

- Statistics in human-readable format
- JSON data with `--json` flag
- Status messages for actions
- Error messages to stderr

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

## Resources

- **[API.md](API.md)** - REST API reference and authentication
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Statistics
pihole_api.py summary                     # Overview stats
pihole_api.py status                      # Blocking enabled/disabled
pihole_api.py top-domains                 # Most queried domains
pihole_api.py top-ads                     # Most blocked domains
pihole_api.py top-clients                 # Most active clients
pihole_api.py query-types                 # Query type distribution

# Blocking Control
pihole_api.py enable                      # Enable blocking
pihole_api.py disable                     # Disable permanently
pihole_api.py disable --duration 300      # Disable for 5 minutes

# List Management
pihole_api.py block example.com           # Add to blocklist
pihole_api.py allow example.com           # Add to allowlist
pihole_api.py unblock example.com         # Remove from blocklist
pihole_api.py unallow example.com         # Remove from allowlist

# Query Analysis
pihole_api.py recent-queries              # Recent DNS queries
pihole_api.py recent-blocked              # Recently blocked queries
pihole_api.py query example.com           # Check if domain is blocked
```

## Workflows

### Troubleshoot Blocked Site
1. User reports site not working
2. Check recent blocks: `recent-blocked`
3. Find domain: `query problematic-site.com`
4. If blocked: `allow problematic-site.com`
5. Verify: `query problematic-site.com`

### Temporary Disable for Testing
1. Disable: `disable --duration 600` (10 minutes)
2. Test website/app
3. Blocking re-enables automatically
4. Or manually: `enable`

### Block Unwanted Domain
1. Identify domain from logs or user request
2. Block: `block tracking.example.com`
3. Verify in blocklist

### Analyze Network DNS Usage
1. View summary: `summary`
2. Top domains: `top-domains`
3. Top clients: `top-clients`
4. Query types: `query-types`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Wrong password | 401 or empty response | Verify password matches web UI |
| Pi-hole v6 API changes | Endpoints may differ | Check API.md for version differences |
| Domain already in list | Operation succeeds silently | Check list before adding |
| Wildcard domains | Use `*.example.com` syntax | Check Pi-hole docs for regex support |
| Disable without duration | Stays disabled forever | Always use `--duration` or remember to `enable` |

## Related Skills

- [/unifi-network](../unifi-network/SKILL.md) - Network-level DNS settings
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
