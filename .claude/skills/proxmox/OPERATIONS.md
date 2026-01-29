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

> **Note**: To update other container configuration (memory, cores, etc.), use the Proxmox web UI or make a direct API call via the `update_container_config()` method in Python.

## Snapshots

### Create Snapshot
```bash
# VM snapshot
python proxmox_api.py snapshot pve 100 --name "before-update"

# LXC snapshot (requires --lxc flag)
python proxmox_api.py snapshot pve 101 --name "clean-state" --lxc
```

### List Snapshots
```bash
# VM snapshots
python proxmox_api.py snapshots pve 100

# LXC snapshots (requires --lxc flag)
python proxmox_api.py snapshots pve 101 --lxc
```

### Rollback
```bash
# VM rollback
python proxmox_api.py rollback pve 100 --name "before-update"

# LXC rollback (requires --lxc flag)
python proxmox_api.py rollback pve 101 --name "clean-state" --lxc
```

## Bulk Operations

### Start All Containers on Node
```bash
# With explicit node name
for vmid in $(python proxmox_api.py containers pve --ids-only); do
  python proxmox_api.py start $vmid pve
done

# With auto-detection
for vmid in $(python proxmox_api.py containers --ids-only); do
  python proxmox_api.py start $vmid
done
```

### Status Overview
```bash
python proxmox_api.py overview pve
```

## Programmatic Usage (Python)

The `execute()` function allows direct Python integration without subprocess calls:

```python
from .claude.skills.proxmox.scripts.proxmox_api import execute

# List VMs (auto-detects node)
vms = execute("vms", {})

# List VMs on specific node
vms = execute("vms", {"node": "pve"})

# Start VM/Container
execute("start", {"vmid": 100, "node": "pve"})

# Get status
status = execute("status", {"vmid": 100, "node": "pve"})

# Add mount
execute("add-mount", {
    "node": "pve",
    "vmid": 101,
    "mp": 0,
    "source": "/mnt/pve/qnap-media",
    "target": "/media",
    "readonly": False
})

# Create snapshot
execute("snapshot", {
    "node": "pve",
    "vmid": 100,
    "name": "pre-update",
    "lxc": False  # True for containers
})
```

**Returns:** Raw Python data (dict/list), not JSON strings.

**Error Handling:** Raises `ValueError` for unknown actions, `KeyError` for missing arguments, `RuntimeError` for API errors.

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
