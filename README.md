# Homelab Assistant

AI-powered automation for your homelab infrastructure. Manage Proxmox, Pi-hole, UniFi, and Home Assistant through natural language or CLI.

## Quick Start

```bash
# 1. Clone and enter directory
cd homelab-assistant

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp .env.example .env
nano .env  # Fill in your credentials

# 4. Test connections
bash setup.sh --test
```

## Available Skills

| Skill | Trigger | Purpose |
|-------|---------|---------|
| [Proxmox](.claude/skills/proxmox/SKILL.md) | `/proxmox` | VMs, containers, storage, NAS mounts |
| [Pi-hole](.claude/skills/pihole/SKILL.md) | `/pihole` | DNS management, ad-blocking |
| [UniFi Network](.claude/skills/unifi-network/SKILL.md) | `/unifi-network` | Routers, switches, APs, clients |
| [UniFi Protect](.claude/skills/unifi-protect/SKILL.md) | `/unifi-protect` | Cameras, NVR, events |
| [Home Assistant](.claude/skills/homeassistant/SKILL.md) | `/homeassistant` | Smart home, automations |

## CLI Usage

Each skill has a Python CLI tool that can be used directly:

### Proxmox
```bash
python .claude/skills/proxmox/scripts/proxmox_api.py nodes
python .claude/skills/proxmox/scripts/proxmox_api.py containers pve
python .claude/skills/proxmox/scripts/proxmox_api.py start pve 100
```

### Pi-hole
```bash
python .claude/skills/pihole/scripts/pihole_api.py summary
python .claude/skills/pihole/scripts/pihole_api.py block ads.example.com
python .claude/skills/pihole/scripts/pihole_api.py top-domains
```

### UniFi Network
```bash
python .claude/skills/unifi-network/scripts/network_api.py health
python .claude/skills/unifi-network/scripts/network_api.py clients
python .claude/skills/unifi-network/scripts/network_api.py devices
```

### UniFi Protect
```bash
python .claude/skills/unifi-protect/scripts/protect_api.py cameras
python .claude/skills/unifi-protect/scripts/protect_api.py events --last 24h
python .claude/skills/unifi-protect/scripts/protect_api.py snapshot <camera-id>
```

### Home Assistant
```bash
python .claude/skills/homeassistant/scripts/homeassistant_api.py status
python .claude/skills/homeassistant/scripts/homeassistant_api.py entities
python .claude/skills/homeassistant/scripts/homeassistant_api.py turn-on light.living_room

# Dashboard management
python .claude/skills/homeassistant/scripts/dashboard_api.py get
python .claude/skills/homeassistant/scripts/dashboard_api.py set dashboard.yaml
```

## Configuration

All credentials are stored in `.env`:

| Service | Required Variables |
|---------|-------------------|
| Proxmox | `PROXMOX_HOST`, `PROXMOX_TOKEN_ID`, `PROXMOX_TOKEN_SECRET` |
| Pi-hole | `PIHOLE_HOST`, `PIHOLE_PASSWORD` |
| UniFi | `UNIFI_HOST`, `UNIFI_USERNAME`, `UNIFI_PASSWORD` |
| Home Assistant | `HOMEASSISTANT_HOST`, `HOMEASSISTANT_TOKEN` |

See [.env.example](.env.example) for all options.

## Project Structure

```
homelab-assistant/
├── .claude/
│   └── skills/
│       ├── homelab/          # Meta-skill overview
│       ├── proxmox/          # Proxmox VE management
│       ├── pihole/           # Pi-hole DNS management
│       ├── unifi-network/    # UniFi network management
│       ├── unifi-protect/    # UniFi Protect cameras
│       └── homeassistant/    # Home Assistant control
│           ├── scripts/
│           │   ├── homeassistant_api.py
│           │   └── dashboard_api.py
│           └── dashboards/   # Dashboard YAML configs
├── .env                      # Your credentials (git-ignored)
├── .env.example              # Template for credentials
├── requirements.txt          # Python dependencies
├── setup.sh                  # Setup & test script
└── README.md
```

## Architecture

Each skill follows a 3-layer architecture:

1. **SKILL.md** - Directives (what to do)
2. **Agent** - Orchestration (decision making)
3. **Scripts** - Execution (deterministic code)

Additional resources per skill:
- `API.md` - REST API reference
- `OPERATIONS.md` - Common tasks
- `TROUBLESHOOTING.md` - Known issues

## License

MIT
