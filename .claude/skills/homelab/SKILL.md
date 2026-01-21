---
name: homelab
description: Overview of all homelab automation skills - meta-skill that guides you to the right specialized skill
version: 2.1.0
author: Philipp Rollmann
tags:
  - homelab
  - infrastructure
  - automation
  - meta
triggers:
  - /homelab
---

# Homelab Automation - Meta Skill

This is a **meta-skill** that provides an overview of all homelab automation capabilities. Each system has its own dedicated skill for focused, efficient operation.

## Available Skills

### [/proxmox](../proxmox/SKILL.md) - Virtualization & Storage
Manage Proxmox VE: VMs, LXC containers, NAS mounts, and community scripts (200+ apps).

**Use for**: VMs, containers, cluster ops, NAS mounts, app installation
**Triggers**: `/proxmox`, `/nas`, `/storage`
**Tags**: `virtualization`, `vm`, `lxc`, `container`, `nas`, `storage`

---

### [/pihole](../pihole/SKILL.md) - DNS & Ad-Blocking
Manage Pi-hole: blocklists, allowlists, statistics, blocking control.

**Use for**: DNS management, ad-blocking, query monitoring, list management
**Triggers**: `/pihole`
**Tags**: `dns`, `pihole`, `adblock`, `network`

---

### [/unifi-network](../unifi-network/SKILL.md) - Network Infrastructure
Manage UniFi network: routers (UCG/UDM), switches, access points, clients.

**Use for**: Network health, client management, device operations, firewall rules
**Triggers**: `/unifi`, `/network`
**Tags**: `network`, `unifi`, `router`, `switch`, `wifi`

---

### [/unifi-protect](../unifi-protect/SKILL.md) - Security Cameras
Manage UniFi Protect: cameras, NVR, events, snapshots, smart lights.

**Use for**: Camera management, event monitoring, snapshots, lighting control
**Triggers**: `/protect`
**Tags**: `security`, `camera`, `nvr`, `unifi`, `surveillance`

---

### [/homeassistant](../homeassistant/SKILL.md) - Smart Home Automation
Manage Home Assistant: entities, scenes, automations, scripts.

**Use for**: Smart home control, automation, scenes, device management
**Triggers**: `/homeassistant`, `/hass`
**Tags**: `smarthome`, `homeassistant`, `automation`, `iot`

---

## Quick Reference

| Need to...                          | Use Skill          | Example Command                          |
|-------------------------------------|--------------------|------------------------------------------|
| Create a VM/container               | `/proxmox`         | `proxmox_api.py vms pve`                 |
| Install an app (Plex, etc.)         | `/proxmox`         | Check COMMUNITY_SCRIPTS.md               |
| Mount NAS to container              | `/proxmox`         | `proxmox_api.py add-mount pve 100 ...`   |
| Block/allow a domain                | `/pihole`          | `pihole_api.py block ads.example.com`    |
| View DNS statistics                 | `/pihole`          | `pihole_api.py summary`                  |
| Disconnect a client                 | `/unifi`           | `network_api.py kick aa:bb:cc:dd:ee:ff`  |
| Check network health                | `/unifi`           | `network_api.py health`                  |
| View camera events                  | `/protect`         | `protect_api.py events --last 24h`       |
| Take camera snapshot                | `/protect`         | `protect_api.py snapshot <camera-id>`    |
| Control smart lights                | `/hass`            | `homeassistant_api.py turn-on light.room`|
| Run automation                      | `/hass`            | `homeassistant_api.py trigger auto.name` |

## Configuration

All skills use environment variables from `.env` in the project root:

```bash
# Proxmox
PROXMOX_HOST=192.168.10.140
PROXMOX_TOKEN_ID=root@pam!homelab
PROXMOX_TOKEN_SECRET=your-token-uuid

# Pi-hole
PIHOLE_HOST=pihole.local
PIHOLE_PASSWORD=your-password

# UniFi Network
UNIFI_HOST=192.168.1.1
UNIFI_USERNAME=admin
UNIFI_PASSWORD=your-password
UNIFI_SITE=default

# UniFi Protect
PROTECT_HOST=192.168.1.1
PROTECT_USERNAME=admin
PROTECT_PASSWORD=your-password

# Home Assistant
HOMEASSISTANT_HOST=homeassistant.local:8123
HOMEASSISTANT_TOKEN=your-long-lived-access-token
```

## Architecture

Each skill follows the 3-layer architecture:
1. **SKILL.md** - Directives (Goal, Inputs, Tools, Outputs, Edge Cases)
2. **Agent** - You (orchestration and decision-making)
3. **Scripts** - Python CLI tools (deterministic execution)

Additional resources per skill:
- **API.md** - REST API reference
- **OPERATIONS.md** - Common operational tasks
- **TROUBLESHOOTING.md** - Known issues (grows via self-annealing)

## Usage Patterns

**Single system operation**: Invoke the specific skill directly
- Example: `/proxmox` when working with VMs

**Multi-system workflow**: Invoke skills sequentially
- Example: Create VM with `/proxmox`, then configure DNS with `/pihole`

**Cross-system integration**: Some systems integrate
- Home Assistant can control UniFi Protect lights
- UniFi Network provides presence detection for Home Assistant
- Proxmox hosts containers for Pi-hole, Home Assistant, etc.

## Version History

**v2.1.0** - NAS storage merged into Proxmox skill, added TROUBLESHOOTING.md to all skills
**v2.0.0** - Split monolithic skill into 5 focused skills + meta-skill
**v1.0.0** - Original monolithic homelab skill
