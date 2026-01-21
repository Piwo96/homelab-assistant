---
name: homelab-automation
description: Automating homelab infrastructure. Use when managing Proxmox VMs, containers, NAS mounts, or other homelab services.
version: 1.0.0
author: Philipp Rollmann
tags:
  - homelab
  - proxmox
  - pihole
  - unifi
  - network
  - dns
  - nas
  - qnap
  - storage
  - infrastructure
  - automation
requires:
  - python3
  - requests
triggers:
  - /homelab
  - /proxmox
  - /nas
  - /pihole
  - /unifi
---

# Homelab Automation

Manage your homelab infrastructure: Proxmox VMs/containers, Pi-hole DNS/ad-blocking, UniFi networking, QNAP NAS mounts.

## Quick Start

1. Set up environment variables (copy `.env.example` to `.env`):
   ```bash
   PROXMOX_HOST=192.168.10.140
   PROXMOX_TOKEN_ID=root@pam!homelab
   PROXMOX_TOKEN_SECRET=your-token-uuid

   PIHOLE_HOST=pihole.local
   PIHOLE_PASSWORD=your-password
   ```

2. Test connections:
   ```bash
   python .claude/skills/homelab/proxmox/scripts/proxmox_api.py nodes
   python .claude/skills/homelab/pihole/scripts/pihole_api.py summary
   ```

## Available Modules

### Proxmox
VM and container management via REST API.
- **[API Reference](proxmox/API.md)** - Endpoints and authentication
- **[Operations Guide](proxmox/OPERATIONS.md)** - Common tasks
- **[Python Script](proxmox/scripts/proxmox_api.py)** - CLI tool
- **[Community Scripts](proxmox/COMMUNITY_SCRIPTS.md)** - Quick app installation (200+ apps)

### Pi-hole
DNS and ad-blocking management.
- **[API Reference](pihole/API.md)** - Endpoints and authentication
- **[Operations Guide](pihole/OPERATIONS.md)** - Common tasks
- **[Python Script](pihole/scripts/pihole_api.py)** - CLI tool

### Network (UniFi)
Network and device management (UCG, UDM, Controller).
- **[API Reference](network/API.md)** - Endpoints and authentication
- **[Operations Guide](network/OPERATIONS.md)** - Common tasks
- **[Python Script](network/scripts/network_api.py)** - CLI tool

### Protect (UniFi)
Camera and NVR management.
- **[API Reference](protect/API.md)** - Endpoints and authentication
- **[Python Script](protect/scripts/protect_api.py)** - CLI tool

### Storage
NAS mount management for LXC containers.
- **[NAS Guide](storage/NAS.md)** - QNAP integration and bind mounts

## Common Commands

```bash
# Proxmox basics
proxmox_api.py nodes                    # List all nodes
proxmox_api.py vms <node>               # List VMs on node
proxmox_api.py containers <node>        # List LXC containers
proxmox_api.py start <node> <vmid>      # Start VM/container
proxmox_api.py stop <node> <vmid>       # Stop VM/container

# Storage
proxmox_api.py storage <node>           # List storage (shows QNAP)
proxmox_api.py lxc-config <node> <vmid> # Show LXC config with mounts
proxmox_api.py add-mount <node> <vmid> --source /mnt/pve/qnap --target /data

# Pi-hole
pihole_api.py summary                   # Statistics summary
pihole_api.py status                    # Blocking status
pihole_api.py disable --duration 300    # Disable blocking for 5 min
pihole_api.py enable                    # Enable blocking
pihole_api.py block example.com         # Add to blocklist
pihole_api.py allow example.com         # Add to allowlist
pihole_api.py top-domains               # Top 10 domains

# Network (UniFi)
network_api.py clients                  # List active clients
network_api.py devices                  # List devices
network_api.py kick aa:bb:cc:dd:ee:ff   # Disconnect client
network_api.py block aa:bb:cc:dd:ee:ff  # Block client
network_api.py restart-device <mac>     # Restart device
network_api.py health                   # Network health

# Protect (UniFi)
protect_api.py cameras                  # List cameras
protect_api.py snapshot <camera-id>     # Get snapshot
protect_api.py events --last 24h        # Last 24h events
protect_api.py lights                   # List lights
```

## Configuration

All configuration via environment variables. See `.env.example` in project root.
