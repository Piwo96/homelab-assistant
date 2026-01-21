---
name: proxmox
description: Manage Proxmox VE virtualization platform - VMs, LXC containers, storage, and automation
version: 1.1.0
author: Philipp Rollmann
tags:
  - homelab
  - virtualization
  - proxmox
  - vm
  - lxc
  - container
  - nas
  - storage
requires:
  - python3
  - requests
triggers:
  - /proxmox
  - /nas
  - /storage
---

# Proxmox VE Management

Manage Proxmox Virtual Environment: VMs, LXC containers, storage, snapshots, and community script installations.

## Goal

Provide complete control over Proxmox infrastructure via API without needing the web UI.

## Inputs

| Input | Source | Required | Description |
|-------|--------|----------|-------------|
| `PROXMOX_HOST` | `.env` | Yes | Proxmox server IP/hostname |
| `PROXMOX_PORT` | `.env` | No | API port (default: 8006) |
| `PROXMOX_TOKEN_ID` | `.env` | Yes | API token ID (`user@realm!tokenname`) |
| `PROXMOX_TOKEN_SECRET` | `.env` | Yes | API token UUID |
| `PROXMOX_VERIFY_SSL` | `.env` | No | Verify SSL cert (default: false) |

## Tools

| Tool | Purpose |
|------|---------|
| `scripts/proxmox_api.py` | CLI for all Proxmox operations |

## Outputs

- JSON or table-formatted data from API
- Status messages for actions (start, stop, etc.)
- Error messages to stderr with exit code 1

## Quick Start

1. Configure `.env`:
   ```bash
   PROXMOX_HOST=192.168.10.140
   PROXMOX_TOKEN_ID=root@pam!homelab
   PROXMOX_TOKEN_SECRET=your-token-uuid
   ```

2. Test connection:
   ```bash
   python .claude/skills/proxmox/scripts/proxmox_api.py nodes
   ```

## Resources

- **[API.md](API.md)** - REST API reference and authentication
- **[OPERATIONS.md](OPERATIONS.md)** - Common operational tasks
- **[COMMUNITY_SCRIPTS.md](COMMUNITY_SCRIPTS.md)** - 200+ one-click app installations
- **[NAS.md](NAS.md)** - NAS storage and bind mount configuration
- **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - Known issues and solutions

## Common Commands

```bash
# Cluster
proxmox_api.py nodes                      # List all nodes
proxmox_api.py node-status <node>         # Node CPU/RAM/uptime
proxmox_api.py overview <node>            # Full node overview

# VMs
proxmox_api.py vms <node>                 # List VMs
proxmox_api.py start <node> <vmid>        # Start VM
proxmox_api.py stop <node> <vmid>         # Stop VM (hard)
proxmox_api.py shutdown <node> <vmid>     # Shutdown VM (graceful)
proxmox_api.py status <node> <vmid>       # VM status

# Containers
proxmox_api.py containers <node>          # List LXC containers
proxmox_api.py lxc-config <node> <vmid>   # Container config
proxmox_api.py start <node> <vmid>        # Start container
proxmox_api.py stop <node> <vmid>         # Stop container

# Storage & Mounts
proxmox_api.py storage <node>             # List storage
proxmox_api.py add-mount <node> <vmid> --mp 0 --source /mnt/pve/nas --target /data
proxmox_api.py remove-mount <node> <vmid> --mp 0

# Snapshots
proxmox_api.py snapshots <node> <vmid>    # List snapshots
proxmox_api.py snapshot <node> <vmid> --name backup-$(date +%Y%m%d)
proxmox_api.py rollback <node> <vmid> --name backup-20240115
```

## Workflows

### Create LXC with NAS Mount
1. Create container via web UI or API
2. Add mount: `add-mount pve 100 --mp 0 --source /mnt/pve/qnap/data --target /data`
3. Restart: `restart pve 100`
4. Verify: `lxc-config pve 100`

### Install App via Community Script
1. Check [COMMUNITY_SCRIPTS.md](COMMUNITY_SCRIPTS.md) for available apps
2. SSH to Proxmox node
3. Run the provided bash command
4. Monitor in web UI

### Pre-Maintenance Snapshot
1. Create snapshot: `snapshot pve 100 --name pre-maintenance --lxc`
2. Perform maintenance
3. If failed: `rollback pve 100 --name pre-maintenance --lxc`

## Edge Cases

| Scenario | Behavior | Mitigation |
|----------|----------|------------|
| Self-signed SSL cert | Connection fails with SSL error | Set `PROXMOX_VERIFY_SSL=false` |
| Token without privileges | 403 Forbidden | Ensure "Privilege Separation" unchecked |
| VM vs Container ambiguity | Script tries VM first, then LXC | Use `--lxc` flag for container snapshots |
| Container running during mount | Mount added but not visible | Restart container after adding mount |
| API rate limiting | Unlikely but possible with automation | Add delays between bulk operations |

## Related Skills

- [/homelab](../homelab/SKILL.md) - Overview of all homelab skills
