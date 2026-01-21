# Proxmox Operations Guide

Common operations using the CLI tool or direct API calls.

## VM/Container Management

### List Resources
```bash
# All nodes
python proxmox_api.py nodes

# VMs on a node
python proxmox_api.py vms pve

# Containers on a node
python proxmox_api.py containers pve
```

### Start/Stop
```bash
# Start
python proxmox_api.py start pve 100

# Stop (graceful shutdown)
python proxmox_api.py shutdown pve 100

# Stop (force)
python proxmox_api.py stop pve 100

# Reboot
python proxmox_api.py reboot pve 100
```

### Status Check
```bash
# Single VM/container status
python proxmox_api.py status pve 100

# Node status (CPU, RAM, uptime)
python proxmox_api.py node-status pve
```

## Storage Operations

### List Storage
```bash
# All storage on a node
python proxmox_api.py storage pve

# Storage details
python proxmox_api.py storage-info qnap-media
```

### Add Mount to LXC Container
```bash
# Basic mount
python proxmox_api.py add-mount pve 100 \
  --mp 0 \
  --source /mnt/pve/qnap-media \
  --target /media

# Read-only mount
python proxmox_api.py add-mount pve 100 \
  --mp 1 \
  --source /mnt/pve/qnap-backup \
  --target /backup \
  --readonly
```

### View Container Mounts
```bash
python proxmox_api.py lxc-config pve 100
```

### Remove Mount
```bash
python proxmox_api.py remove-mount pve 100 --mp 0
```

## Snapshots

### Create Snapshot
```bash
# VM snapshot
python proxmox_api.py snapshot pve 100 --name "before-update"

# LXC snapshot
python proxmox_api.py snapshot pve 101 --name "clean-state"
```

### List Snapshots
```bash
python proxmox_api.py snapshots pve 100
```

### Rollback
```bash
python proxmox_api.py rollback pve 100 --name "before-update"
```

## Bulk Operations

### Start All Containers on Node
```bash
for vmid in $(python proxmox_api.py containers pve --ids-only); do
  python proxmox_api.py start pve $vmid
done
```

### Status Overview
```bash
python proxmox_api.py overview pve
```

## Troubleshooting

### Connection Issues
1. Check if Proxmox is reachable: `curl -k https://192.168.10.140:8006`
2. Verify token: Check Datacenter → Permissions → API Tokens
3. Check permissions: Token needs appropriate privileges

### Mount Issues
1. Verify source path exists on Proxmox host
2. Container must be stopped to add mounts
3. Check permissions: `ls -la /mnt/pve/`

### Common Errors
- `401 Unauthorized`: Invalid or expired token
- `403 Forbidden`: Token lacks permissions
- `500 Internal Server Error`: Check Proxmox logs `/var/log/pveproxy/`
