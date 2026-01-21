---
name: unifi-network
description: Manage UniFi network infrastructure - routers, switches, access points, and client devices
version: 1.1.0
author: Philipp Rollmann
tags:
  - homelab
  - network
  - unifi
  - router
  - switch
  - wifi
requires:
  - python3
  - requests
triggers:
  - /unifi
  - /network
---

# UniFi Network Management

Manage UniFi network devices: routers (UCG/UDM), switches, access points, and client devices.

## Goal

Control UniFi network infrastructure via API without needing the web UI or mobile app.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `UNIFI_HOST` | `.env` | Yes | Controller/gateway IP |
| `UNIFI_USERNAME` | `.env` | Yes | Local admin username |
| `UNIFI_PASSWORD` | `.env` | Yes | Local admin password |
| `UNIFI_SITE` | `.env` | No | Site name (default: `default`) |
| `UNIFI_PORT` | `.env` | No | API port (default: 443) |
| `UNIFI_VERIFY_SSL` | `.env` | No | Verify SSL (default: false) |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/network_api.py` | CLI for all UniFi Network operations |

## Outputs

- Device and client lists in table or JSON format
- Status messages for actions
- Error messages to stderr

## Quick Start

1. Configure `.env`:
   ```bash
   UNIFI_HOST=192.168.1.1
   UNIFI_USERNAME=admin
   UNIFI_PASSWORD=your-password
   UNIFI_SITE=default
   ```

2. Test connection:
   ```bash
   python .claude/skills/unifi-network/scripts/network_api.py health
   ```

## Resources

- **[API.md](API.md)** - REST API reference and authentication
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Network Health
network_api.py health                     # Overall health status
network_api.py devices                    # List all devices (APs, switches)
network_api.py device-status <mac>        # Specific device status

# Client Management
network_api.py clients                    # List active clients
network_api.py client-info <mac>          # Client details
network_api.py kick <mac>                 # Disconnect client
network_api.py block <mac>                # Block client permanently
network_api.py unblock <mac>              # Unblock client

# Device Operations
network_api.py restart-device <mac>       # Restart AP/switch
network_api.py locate-device <mac>        # Flash LED to find device
network_api.py provision <mac>            # Force re-provision

# Configuration
network_api.py networks                   # List networks/VLANs
network_api.py port-forwards              # List port forwarding rules
network_api.py firewall-rules             # List firewall rules
```

## Workflows

### Troubleshoot Client Connection
1. Find client: `clients`
2. Get details: `client-info aa:bb:cc:dd:ee:ff`
3. Check signal strength, AP, connection time
4. If issues: `kick aa:bb:cc:dd:ee:ff` to force reconnect

### Find Physical Device
1. Get MAC: `devices`
2. Flash LED: `locate-device aa:bb:cc:dd:ee:ff`
3. Find blinking device
4. Stop: `locate-device aa:bb:cc:dd:ee:ff --stop`

### Block Unwanted Device
1. Identify device: `clients`
2. Block: `block aa:bb:cc:dd:ee:ff`
3. Device disconnected immediately
4. Stays blocked until: `unblock aa:bb:cc:dd:ee:ff`

### Restart Misbehaving AP
1. Identify AP: `devices`
2. Check status: `device-status aa:bb:cc:dd:ee:ff`
3. Restart: `restart-device aa:bb:cc:dd:ee:ff`
4. Wait 2-3 minutes for reboot
5. Verify: `device-status aa:bb:cc:dd:ee:ff`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Self-signed SSL | Connection fails | Set `UNIFI_VERIFY_SSL=false` |
| Cloud-only account | Login fails | Create local admin account |
| Multi-site setup | Wrong site data | Set correct `UNIFI_SITE` |
| UCG vs UDM vs Controller | API paths may differ | Check API.md for device-specific paths |
| Client not found | Recently disconnected | Check with `--all` flag for historical |
| Device adoption pending | Limited control | Complete adoption in web UI first |

## Related Skills

- [/pihole](../pihole/SKILL.md) - DNS management
- [/unifi-protect](../unifi-protect/SKILL.md) - Camera management
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
