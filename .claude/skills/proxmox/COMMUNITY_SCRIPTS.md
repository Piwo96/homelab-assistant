# Proxmox Community Scripts Integration

Quick app installation for your homelab using battle-tested community scripts.

## What are Community Scripts?

[Proxmox VE Helper-Scripts](https://github.com/community-scripts/ProxmoxVE) is a community-maintained collection of **200+ one-command installation scripts** for popular self-hosted applications. Originally created by tteck, now maintained by the community.

**Website:** https://community-scripts.github.io/Proxmox/

## Why Use Them?

- ✓ **Battle-tested**: Used by thousands of homelabbers
- ✓ **One-command**: Simple bash commands
- ✓ **Best practices**: Proper security, resource allocation
- ✓ **Wide selection**: 200+ apps across all categories
- ✓ **Active maintenance**: Regular updates and new scripts

## How It Works with This Skill

```
┌──────────────────────────────────────────────────────────┐
│ 1. Community Script → Install App (LXC/VM)              │
│    bash -c "$(wget -qLO - https://...)"                 │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 2. Homelab Skill → Post-Installation & Management       │
│    - Find container ID                                   │
│    - Add NAS mounts                                      │
│    - Start/stop containers                               │
│    - Monitor resources                                   │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ 3. Optional → API Integration                            │
│    - Add app-specific API to skill                       │
│    - Automate app-level operations                       │
└──────────────────────────────────────────────────────────┘
```

## Popular Apps by Category

### Home Automation
- **Home Assistant** - Complete home automation platform
  ```bash
  bash -c "$(wget -qLO - https://github.com/community-scripts/ProxmoxVE/raw/main/ct/homeassistant.sh)"
  ```
- **Node-RED** - Flow-based automation
- **Zigbee2MQTT** - Zigbee device integration
- **ESPHome** - ESP device management

### Document Management
- **Paperless-ngx** - Document management system
  ```bash
  bash -c "$(wget -qLO - https://github.com/community-scripts/ProxmoxVE/raw/main/ct/paperless.sh)"
  ```
- **Docspell** - Document organization

### Media Servers
- **Plex** - Media server
- **Jellyfin** - Open-source media system
- **Navidrome** - Music streaming server
- **PhotoPrism** - Photo management

### Monitoring & Observability
- **Grafana** - Metrics visualization
- **Prometheus** - Metrics collection
- **Uptime Kuma** - Uptime monitoring
- **NetData** - Real-time monitoring

### Network Services
- **Pi-hole** - DNS ad-blocking (already integrated in this skill!)
- **AdGuard Home** - Alternative DNS filtering
- **WireGuard** - VPN server
- **Nginx Proxy Manager** - Reverse proxy

### Development & DevOps
- **Docker** - Container runtime
- **Portainer** - Docker management UI
- **GitLab** - Git repository & CI/CD
- **Code-Server** - VS Code in browser

### Backup & Storage
- **Duplicati** - Backup solution
- **Vaultwarden** - Password manager
- **Syncthing** - File synchronization
- **Nextcloud** - Personal cloud

**Full list:** https://community-scripts.github.io/Proxmox/scripts

## Installation Workflow

### Example 1: Installing Paperless-ngx

```bash
# Step 1: Run community script in Proxmox Shell
bash -c "$(wget -qLO - https://github.com/community-scripts/ProxmoxVE/raw/main/ct/paperless.sh)"

# Follow interactive prompts:
# - Container ID: 105 (note this down!)
# - Resources: Accept defaults or customize
# - Network: Accept defaults

# Step 2: Find container (if you forgot the ID)
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py containers pve | grep -i paperless

# Step 3: Add NAS mount for documents
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py add-mount pve 105 \
  --source /mnt/pve/qnap-documents \
  --target /data/documents

# Step 4: Verify container is running
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py status pve 105

# Step 5: Access app
# URL displayed at end of installation (usually http://<proxmox-ip>:8000)
```

### Example 2: Managing Existing Home Assistant

```bash
# Find container ID
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py containers pve | grep -i assistant

# Check status
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py status pve <vmid>

# Start/stop
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py start pve <vmid>
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py stop pve <vmid>

# View configuration
python .claude/skills/homelab/proxmox/scripts/proxmox_api.py lxc-config pve <vmid>
```

## Post-Installation Checklist

After running a community script:

1. **Note the Container ID** - You'll need this for management
2. **Check Container Status**
   ```bash
   proxmox_api.py status pve <vmid>
   ```
3. **Add NAS Mounts** (if needed)
   ```bash
   proxmox_api.py add-mount pve <vmid> --source /mnt/pve/qnap-xxx --target /data
   ```
4. **Adjust Resources** (if needed)
   - Use Proxmox Web UI or API to modify CPU/RAM
5. **Test Access**
   - URL is shown at end of installation
   - Usually `http://<proxmox-ip>:<port>`
6. **Optional: Add API Integration**
   - Create new module in skill (e.g., `homeassistant/`, `paperless/`)

## Common Post-Install Tasks

### Adding NAS Mounts

**Media Servers** (Plex, Jellyfin):
```bash
proxmox_api.py add-mount pve <vmid> \
  --source /mnt/pve/qnap-media \
  --target /media
```

**Document Management** (Paperless):
```bash
proxmox_api.py add-mount pve <vmid> \
  --source /mnt/pve/qnap-documents \
  --target /data/documents
```

**Backups** (Vaultwarden, Duplicati):
```bash
proxmox_api.py add-mount pve <vmid> \
  --source /mnt/pve/qnap-backup \
  --target /backup
```

**Config Persistence**:
```bash
proxmox_api.py add-mount pve <vmid> \
  --source /mnt/pve/qnap-config/<app> \
  --target /config
```

### Resource Adjustment

Check current resources:
```bash
proxmox_api.py lxc-config pve <vmid>
```

Adjust via Proxmox Web UI:
- Datacenter → Container → Resources
- Modify CPU cores, RAM, Disk

## Troubleshooting

### Container won't start
```bash
# Check status
proxmox_api.py status pve <vmid>

# View Proxmox logs
# In Proxmox Shell:
pct start <vmid>  # See error output
```

### Can't access web interface
- Check firewall rules
- Verify container is running
- Check port mapping in container config

### Out of disk space
- Resize container disk via Proxmox UI
- Check NAS mounts are configured correctly

## Resources

- **Scripts Website**: https://community-scripts.github.io/Proxmox/
- **GitHub Repository**: https://github.com/community-scripts/ProxmoxVE
- **Proxmox Documentation**: https://pve.proxmox.com/wiki/
- **Community Forum**: https://forum.proxmox.com/

## Future Integrations

When you're ready to automate at the app level:

1. **Home Assistant** → Create `homeassistant/` module with API integration
2. **Paperless-ngx** → Document automation via API
3. **Grafana/Prometheus** → Metrics dashboards
4. **Vaultwarden** → Password management automation

Each can follow the same pattern as existing modules (Proxmox, Pi-hole, UniFi).
