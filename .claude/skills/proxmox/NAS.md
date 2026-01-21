# NAS Storage Guide

Managing QNAP and other NAS storage in Proxmox.

## Overview

Your QNAP NAS is already configured as Proxmox storage. This means:
- Shares are mounted on Proxmox hosts under `/mnt/pve/<storage-name>`
- You can create bind mounts from these paths to LXC containers
- VMs can use storage-backed virtual disks

## List Available Storage

```bash
python proxmox_api.py storage pve
```

Example output:
```
storage         type      content
qnap-media      cifs      images,rootdir
qnap-backup     cifs      backup
qnap-iso        cifs      iso
local           dir       images,rootdir
local-lvm       lvmthin   images,rootdir
```

## Storage Paths

Storage in Proxmox is mounted at:
```
/mnt/pve/<storage-name>/
```

Example:
- `qnap-media` → `/mnt/pve/qnap-media/`
- `qnap-backup` → `/mnt/pve/qnap-backup/`

## Adding NAS Mount to LXC Container

### Prerequisites
- Container must be stopped (or use `--force` for live config changes)
- Source path must exist on Proxmox host
- Appropriate permissions on NAS share

### Using CLI Tool

```bash
# Add media folder to container 100
python proxmox_api.py add-mount pve 100 \
  --mp 0 \
  --source /mnt/pve/qnap-media \
  --target /media

# Add read-only backup access
python proxmox_api.py add-mount pve 100 \
  --mp 1 \
  --source /mnt/pve/qnap-backup \
  --target /backup \
  --readonly
```

### Mount Point IDs
- `mp0` through `mp9` are available
- Each container can have up to 10 additional mount points
- `mp0` is typically used for primary data

### View Current Mounts

```bash
python proxmox_api.py lxc-config pve 100
```

Look for `mp0`, `mp1`, etc. in output.

### Remove Mount

```bash
python proxmox_api.py remove-mount pve 100 --mp 0
```

## Common Mount Configurations

### Media Server (Jellyfin/Plex)
```bash
python proxmox_api.py add-mount pve 100 \
  --mp 0 --source /mnt/pve/qnap-media/movies --target /media/movies
python proxmox_api.py add-mount pve 100 \
  --mp 1 --source /mnt/pve/qnap-media/tv --target /media/tv
python proxmox_api.py add-mount pve 100 \
  --mp 2 --source /mnt/pve/qnap-media/music --target /media/music
```

### Paperless-ngx
```bash
python proxmox_api.py add-mount pve 101 \
  --mp 0 --source /mnt/pve/qnap-documents/consume --target /consume
python proxmox_api.py add-mount pve 101 \
  --mp 1 --source /mnt/pve/qnap-documents/media --target /media
```

### Backup Container
```bash
python proxmox_api.py add-mount pve 102 \
  --mp 0 --source /mnt/pve/qnap-backup --target /backup
```

## Permissions

### User Mapping in LXC
Unprivileged containers need UID/GID mapping. In container config:

```
# Map container user 1000 to host user 1000
lxc.idmap: u 0 100000 1000
lxc.idmap: g 0 100000 1000
lxc.idmap: u 1000 1000 1
lxc.idmap: g 1000 1000 1
lxc.idmap: u 1001 101001 64535
lxc.idmap: g 1001 101001 64535
```

### Fixing Permissions on NAS
On QNAP, ensure shared folders have:
- Appropriate user/group ownership
- Read/write permissions for Proxmox users

## Troubleshooting

### Mount Not Visible in Container
1. Restart the container after adding mount
2. Check if source path exists: `ls /mnt/pve/qnap-media/`
3. Verify Proxmox storage is online: `pvesm status`

### Permission Denied
1. Check NAS share permissions
2. For unprivileged LXC: set up UID mapping
3. Alternative: use privileged container (less secure)

### NAS Disconnected
If NAS goes offline:
1. Check network connectivity
2. Remount: `pvesm set qnap-media --disable 0`
3. Verify: `mount | grep pve`

## Direct Manual Configuration

If needed, edit container config directly:

```bash
# On Proxmox host
nano /etc/pve/lxc/100.conf

# Add line:
mp0: /mnt/pve/qnap-media,mp=/media
```

Then restart container.
