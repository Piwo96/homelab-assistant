---
name: unifi-network
description: Netzwerk-Geräte und Clients verwalten (Router, Switches, Access Points, WLAN/LAN-Clients)
version: 1.2.0
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
intent_hints:
  - "Geräte im Netzwerk, LAN oder WLAN"
  - "Welche Geräte sind online/verbunden"
  - "Kabelgebundene oder drahtlose Geräte"
  - "Netzwerk-Status, Router, Switch, Access Point"
  - "Wer ist im WLAN, wie viele Clients"
  - "Internet-Probleme, Netzwerk-Gesundheit"
  - "Port-Forwarding, Firewall-Regeln"
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

**Note**: `network_api.py` can also be imported as a Python module via `execute(action, args)` function for programmatic access.

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
network_api.py detect                     # Detect controller type (UCG/UDM/Standard)
network_api.py health                     # Overall health status
network_api.py sysinfo                    # System information

# Client Management
network_api.py clients                    # List active clients
network_api.py clients --all              # List all known clients (includes inactive)
network_api.py kick <mac>                 # Disconnect client
network_api.py block <mac>                # Block client permanently
network_api.py unblock <mac>              # Unblock client

# Device Management
network_api.py devices                    # List all devices (APs, switches, gateways)
network_api.py restart-device <mac>       # Restart AP/switch
network_api.py adopt <mac>                # Adopt pending device

# Network Configuration
network_api.py networks                   # List networks/VLANs
network_api.py wifis                      # List WiFi networks/SSIDs

# Port Forwarding
network_api.py port-forwards              # List port forwarding rules
network_api.py create-port-forward <name> <dst_port> <fwd_ip> <fwd_port> [--proto tcp_udp]
network_api.py delete-port-forward <rule_id>

# Firewall
network_api.py firewall-rules             # List firewall rules
network_api.py firewall-groups            # List firewall groups (IP/port groups)

# Statistics
network_api.py dpi-stats                  # Deep Packet Inspection statistics
```

## Workflows

### Troubleshoot Client Connection
1. Find client: `clients` or `clients --all` for inactive
2. View full JSON details: `clients --json | grep -A 20 "aa:bb:cc:dd:ee:ff"`
3. If issues: `kick aa:bb:cc:dd:ee:ff` to force reconnect

### Block Unwanted Device
1. Identify device: `clients`
2. Block: `block aa:bb:cc:dd:ee:ff`
3. Device disconnected immediately
4. Stays blocked until: `unblock aa:bb:cc:dd:ee:ff`

### Restart Misbehaving AP
1. Identify AP: `devices`
2. Restart: `restart-device aa:bb:cc:dd:ee:ff`
3. Wait 2-3 minutes for reboot
4. Verify: `devices | grep aa:bb:cc:dd:ee:ff`

### Setup Port Forwarding
1. List existing rules: `port-forwards`
2. Create rule: `create-port-forward "Web Server" 80 192.168.1.100 8080`
3. Verify: `port-forwards --json`
4. Delete if needed: `delete-port-forward <rule_id>`

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
