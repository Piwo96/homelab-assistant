# UniFi Operations Guide

Common operations for managing UniFi networks, clients, and devices. Commands work in dual-API mode (Integration API v1 + Legacy fallback).

## Initial Setup

### Detect API Mode

```bash
python network_api.py detect
```

Output shows:
- Configured authentication methods (API Key, Username/Password)
- Integration API base URL
- Legacy Controller type (UCG/UDM or Standard)
- Active API mode (dual, integration, legacy)

### Application Info (Integration API)

```bash
python network_api.py info
python network_api.py sites
```

## Client Management

### List Clients

```bash
# Connected clients (uses Integration API if available)
python network_api.py clients

# With pagination
python network_api.py clients --limit 100 --offset 0

# All known clients including inactive (Legacy only)
python network_api.py clients --all

# JSON output
python network_api.py clients --json
```

### Client Details (Integration API)

```bash
# Get full client details by UUID
python network_api.py client-detail <client-uuid>
python network_api.py client-detail <client-uuid> --json
```

### Client Actions

```bash
# Kick client - disconnect, can reconnect (Legacy API)
python network_api.py kick aa:bb:cc:dd:ee:ff

# Block client permanently (Legacy API)
python network_api.py block aa:bb:cc:dd:ee:ff

# Unblock client (Legacy API)
python network_api.py unblock aa:bb:cc:dd:ee:ff

# Authorize guest access (Integration API)
python network_api.py authorize-guest <client-uuid>
python network_api.py authorize-guest <client-uuid> --time-limit 60 --data-limit 500

# Unauthorize guest (Integration API)
python network_api.py unauthorize-guest <client-uuid>
```

## Device Management

### List Devices

```bash
# All adopted devices (uses Integration API if available)
python network_api.py devices

# With pagination
python network_api.py devices --limit 100 --offset 0

# JSON output
python network_api.py devices --json
```

### Device Details & Statistics (Integration API)

```bash
# Full device details
python network_api.py device-detail <device-uuid>

# Device statistics: CPU, RAM, uptime, throughput
python network_api.py device-stats <device-uuid>
python network_api.py device-stats <device-uuid> --json
```

### Device Actions

```bash
# Restart device (UUID for Integration API, MAC for Legacy)
python network_api.py restart-device <device-uuid-or-mac>

# Adopt pending device
python network_api.py adopt aa:bb:cc:dd:ee:ff

# List pending devices (Integration API)
python network_api.py pending-devices

# Power cycle a switch port (Integration API)
python network_api.py power-cycle-port <device-uuid> <port-index>
```

## Network Configuration

### List Networks

```bash
# All networks/VLANs
python network_api.py networks
python network_api.py networks --limit 100
python network_api.py networks --json
```

### Network CRUD (Integration API)

```bash
# Network details
python network_api.py network-detail <network-uuid>

# Network references (clients, devices using this network)
python network_api.py network-references <network-uuid>

# Create network
python network_api.py create-network "IoT" --vlan 30
python network_api.py create-network "Guest" --vlan 40 --management GATEWAY

# Update network
python network_api.py update-network <uuid> --name "New Name"
python network_api.py update-network <uuid> --vlan 50

# Delete network
python network_api.py delete-network <uuid>
```

## WiFi Management

### List WiFi Broadcasts

```bash
python network_api.py wifis
python network_api.py wifis --json
```

### WiFi CRUD (Integration API)

```bash
# WiFi details
python network_api.py wifi-detail <wifi-uuid>

# Create WiFi
python network_api.py create-wifi "Guest WiFi" --security WPA2

# Update WiFi
python network_api.py update-wifi <uuid> --name "New SSID"
python network_api.py update-wifi <uuid> --enabled false

# Delete WiFi
python network_api.py delete-wifi <uuid>
```

## Network Statistics (Legacy API)

### Site Health

```bash
python network_api.py health
python network_api.py health --json
```

### System Info

```bash
python network_api.py sysinfo
python network_api.py sysinfo --json
```

### DPI Statistics

```bash
python network_api.py dpi-stats
python network_api.py dpi-stats --json
```

## Port Forwarding (Legacy API)

```bash
# List rules
python network_api.py port-forwards
python network_api.py port-forwards --json

# Create rule
python network_api.py create-port-forward "Web Server" 80 192.168.1.100 8080
python network_api.py create-port-forward "SSH" 22 192.168.1.50 22 --proto tcp

# Delete rule
python network_api.py delete-port-forward <rule-id>
```

## Firewall Management (Legacy API)

```bash
# List firewall rules
python network_api.py firewall-rules
python network_api.py firewall-rules --json

# List firewall groups
python network_api.py firewall-groups
python network_api.py firewall-groups --json
```

## Output Formats

All commands support `--json` flag for machine-readable output. Default is human-readable with icons.

### Pagination Defaults

Integration API commands use pagination with these defaults:
- `--limit 50` (results per page)
- `--offset 0` (starting position)

To retrieve all results, increase `--limit` or iterate with `--offset`. Legacy API returns all results (no pagination).

## Common Workflows

### Monitor Device Health

```bash
# 1. List all devices
python network_api.py devices

# 2. Get device UUID from the list
# 3. Check stats
python network_api.py device-stats <uuid>
```

### Troubleshoot Client

```bash
# 1. Find client
python network_api.py clients
python network_api.py clients --json | jq '.[] | select(.name | contains("iPhone"))'

# 2. Get details (Integration API)
python network_api.py client-detail <uuid>

# 3. Force reconnect (Legacy API)
python network_api.py kick aa:bb:cc:dd:ee:ff
```

### Setup New VLAN with WiFi

```bash
# 1. Create network
python network_api.py create-network "IoT Devices" --vlan 30

# 2. Create WiFi broadcast for this network
python network_api.py create-wifi "IoT WiFi" --security WPA2

# 3. Verify
python network_api.py networks --json
python network_api.py wifis --json
```

## Site Management

```bash
# Specify site
python network_api.py clients --site office
python network_api.py devices --site office

# Or set in environment
export UNIFI_SITE=office
```

## Python Module Usage

```python
from network_api import execute

# Dual-mode: uses Integration API when available
clients = execute("clients", {"limit": "100"})
devices = execute("devices", {})

# Integration API only
info = execute("info", {})
stats = execute("device-stats", {"id": "device-uuid"})

# Legacy API only
health = execute("health", {})
execute("kick", {"mac": "aa:bb:cc:dd:ee:ff"})
```

## Integration with jq

```bash
# Get all online devices (Integration API format)
python network_api.py devices --json | jq '.[] | select(.state=="ONLINE") | .name'

# Get wireless clients (Integration API format)
python network_api.py clients --json | jq '.[] | select(.type=="WIRELESS") | {name, ipAddress}'

# Get all VLANs
python network_api.py networks --json | jq '.[] | {name, vlanId}'
```
