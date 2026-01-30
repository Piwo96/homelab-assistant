---
name: unifi-network
description: Netzwerk-Geräte und Clients verwalten (Router, Switches, Access Points, WLAN/LAN-Clients)
version: 2.0.0
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
  - "Welche Geräte sind im WLAN oder LAN verbunden?"
  - "Zeig mir alle Netzwerk-Clients und ihre IP-Adressen"
  - "Wie ist der Status von Router, Switch und Access Point?"
  - "Wer ist gerade im WiFi-Netzwerk online?"
  - "Gibt es Internetprobleme oder Netzwerkstörungen?"
  - "Zeig mir die Firewall-Regeln und Port-Weiterleitungen"
  - "Erstelle ein neues WLAN-Netzwerk oder VLAN"
  - "Wie viele Clients sind mit dem UniFi-Netzwerk verbunden?"
  - "Blockiere oder kicke ein Gerät aus dem Netzwerk"
  - "Zeig mir die UniFi Netzwerk-Übersicht mit allen Geräten"
---

# UniFi Network Management

Manage UniFi network devices: routers (UCG/UDM), switches, access points, and client devices.

## Goal

Control UniFi network infrastructure via API without needing the web UI or mobile app.

## Dual-API Architecture

This skill supports two API modes that can work independently or together:

| Mode | Auth | Features | Use Case |
|------|------|----------|----------|
| **Integration API v1** | API Key (`X-API-Key`) | Pagination, filtering, device stats, network/WiFi CRUD | Primary, official API |
| **Legacy API** | Username/Password (session) | Kick/block clients, health, DPI stats, port forwarding, firewall | Fallback for features not in Integration API |
| **Dual** | Both configured | All features available | Recommended setup |

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `UNIFI_API_KEY` | `.env` | For Integration API | API key (create in UniFi UI > Settings > API) |
| `UNIFI_HOST` | `.env` | Yes | Controller/gateway IP |
| `UNIFI_USERNAME` | `.env` | For Legacy API | Local admin username |
| `UNIFI_PASSWORD` | `.env` | For Legacy API | Local admin password |
| `UNIFI_SITE` | `.env` | No | Site name (default: `default`) |
| `UNIFI_VERIFY_SSL` | `.env` | No | Verify SSL (default: false) |

**Minimum:** Either `UNIFI_API_KEY` or `UNIFI_USERNAME` + `UNIFI_PASSWORD` must be set.

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
   # Integration API (recommended)
   UNIFI_API_KEY=your-api-key
   UNIFI_HOST=192.168.1.1
   UNIFI_SITE=default

   # Legacy API (for kick/block/health/firewall)
   UNIFI_USERNAME=admin
   UNIFI_PASSWORD=your-password
   ```

2. Test connection:
   ```bash
   python .claude/skills/unifi-network/scripts/network_api.py detect
   ```

## Resources

- **[API.md](API.md)** - REST API reference (Integration API v1 + Legacy)
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Architecture Notes

### Composition Pattern (v2.0.0)

This skill uses **composition over inheritance** to avoid breaking the existing `ProtectAPI(UniFiAPI)` inheritance relationship:

```python
# UniFiDualAPI owns instances of both APIs (composition)
class UniFiDualAPI:
    self._integration = IntegrationAPI(...)  # New Integration API
    self._legacy = UniFiAPI(...)              # Existing Legacy API

# ProtectAPI continues to inherit from UniFiAPI unchanged
class ProtectAPI(UniFiAPI):
    # Still works, shares session cache with Network API
```

**Why**: Adding Integration API support via inheritance would force ProtectAPI to carry Integration API dependencies. Composition keeps APIs isolated while allowing UniFiDualAPI to intelligently route between them.

### Lazy UUID Resolution

Integration API uses UUID-based site identifiers. The skill resolves `UNIFI_SITE=default` to UUID via `GET /v1/sites` on first API call (cached thereafter). If site name doesn't match, error message lists available sites.

### Session Sharing

Network and Protect APIs share the same session cache (`~/.cache/homelab/unifi_session_<host>.pkl`, 1.5h TTL) via the UniFiAPI base class. Integration API doesn't use sessions (stateless API key auth).

## Common Commands

```bash
# Detection & Info
network_api.py detect                     # Detect API mode and controller type
network_api.py info                       # Application version (Integration API)
network_api.py sites                      # List sites with UUIDs (Integration API)

# Network Health (Legacy API)
network_api.py health                     # Overall health status
network_api.py sysinfo                    # System information

# Client Management
network_api.py clients                    # List connected clients
network_api.py clients --limit 100        # With pagination
network_api.py client-detail <uuid>       # Client details (Integration API)
network_api.py kick <mac>                 # Disconnect client (Legacy API)
network_api.py block <mac>                # Block client (Legacy API)
network_api.py unblock <mac>              # Unblock client (Legacy API)
network_api.py authorize-guest <uuid>     # Authorize guest (Integration API)
network_api.py unauthorize-guest <uuid>   # Unauthorize guest (Integration API)

# Device Management
network_api.py devices                    # List all devices
network_api.py device-detail <uuid>       # Device details (Integration API)
network_api.py device-stats <uuid>        # CPU, RAM, uptime (Integration API)
network_api.py restart-device <id/mac>    # Restart device
network_api.py adopt <mac>                # Adopt pending device
network_api.py pending-devices            # List pending devices (Integration API)
network_api.py power-cycle-port <dev> <port>  # Power cycle port (Integration API)

# Network Configuration
network_api.py networks                   # List networks/VLANs
network_api.py network-detail <uuid>      # Network details (Integration API)
network_api.py create-network <name>      # Create network (Integration API)
network_api.py update-network <uuid>      # Update network (Integration API)
network_api.py delete-network <uuid>      # Delete network (Integration API)

# WiFi Management
network_api.py wifis                      # List WiFi broadcasts
network_api.py wifi-detail <uuid>         # WiFi details (Integration API)
network_api.py create-wifi <name>         # Create WiFi (Integration API)
network_api.py update-wifi <uuid>         # Update WiFi (Integration API)
network_api.py delete-wifi <uuid>         # Delete WiFi (Integration API)

# Port Forwarding (Legacy API)
network_api.py port-forwards              # List port forwarding rules
network_api.py create-port-forward <name> <dst_port> <fwd_ip> <fwd_port> [--proto tcp_udp]
network_api.py delete-port-forward <rule_id>

# Firewall (Legacy API)
network_api.py firewall-rules             # List firewall rules
network_api.py firewall-groups            # List firewall groups

# Statistics (Legacy API)
network_api.py dpi-stats                  # Deep Packet Inspection statistics
```

## Workflows

### Troubleshoot Client Connection
1. Find client: `clients` or `client-detail <uuid>` for full details
2. View full JSON: `clients --json`
3. If issues: `kick aa:bb:cc:dd:ee:ff` to force reconnect

### Block Unwanted Device
1. Identify device: `clients`
2. Block: `block aa:bb:cc:dd:ee:ff`
3. Stays blocked until: `unblock aa:bb:cc:dd:ee:ff`

### Monitor Device Health
1. List devices with stats: `devices`
2. Check specific device: `device-stats <uuid>`
3. Shows CPU, RAM, uptime, throughput

### Create New Network
1. Create: `create-network "IoT" --vlan 30`
2. Verify: `network-detail <uuid>`
3. Delete if needed: `delete-network <uuid>`

### Manage WiFi
1. List: `wifis`
2. Create: `create-wifi "Guest WiFi" --security WPA2`
3. Update: `update-wifi <uuid> --enabled false`
4. Delete: `delete-wifi <uuid>`

### Setup Port Forwarding
1. List existing rules: `port-forwards`
2. Create rule: `create-port-forward "Web Server" 80 192.168.1.100 8080`
3. Verify: `port-forwards --json`
4. Delete if needed: `delete-port-forward <rule_id>`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Self-signed SSL | Connection fails | Set `UNIFI_VERIFY_SSL=false` |
| Cloud-only account | Login fails (Legacy) | Create local admin or use API key |
| No API key | Integration API unavailable | Legacy API works for basic ops |
| No username/password | Legacy API unavailable | Integration API works for most ops |
| Multi-site setup | Wrong site data | Set correct `UNIFI_SITE` |
| Integration API needs UUIDs | MAC doesn't work | Use `devices` to find UUID first |
| Client not found | Recently disconnected | Check with `--all` flag (Legacy) |
| Feature not in API mode | RuntimeError with clear message | Configure both auth methods |

## Related Skills

- [/pihole](../pihole/SKILL.md) - DNS management
- [/unifi-protect](../unifi-protect/SKILL.md) - Camera management
- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
