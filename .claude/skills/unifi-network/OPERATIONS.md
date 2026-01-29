# UniFi Operations Guide

Common operations for managing UniFi networks, clients, and devices. This guide documents **only** the commands actually implemented in `network_api.py`.

## Initial Setup

Determine your controller type:
```bash
python network_api.py detect
```

This auto-detects:
- Standard Controller (port 8443)
- UDM/UDM Pro/UCG (port 443, `/proxy/network` prefix)

## Client Management

### List Clients

```bash
# All active clients (formatted output)
python network_api.py clients

# All known clients (includes inactive)
python network_api.py clients --all

# JSON output for scripting
python network_api.py clients --json
python network_api.py clients --all --json
```

**Output includes:**
- Client name/hostname
- IP address
- MAC address
- Connection type (wired/wireless)
- SSID (for wireless clients)

### Client Actions

```bash
# Kick client (disconnect, can reconnect)
python network_api.py kick aa:bb:cc:dd:ee:ff

# Block client (permanent until unblocked)
python network_api.py block aa:bb:cc:dd:ee:ff

# Unblock client
python network_api.py unblock aa:bb:cc:dd:ee:ff
```

### Finding Client Details

```bash
# Get full client details via JSON
python network_api.py clients --json | jq '.[] | select(.mac=="aa:bb:cc:dd:ee:ff")'

# Filter clients by name pattern using grep
python network_api.py clients | grep "iPhone"
```

## Device Management

### List Devices

```bash
# All network devices (APs, switches, gateways)
python network_api.py devices

# JSON output for scripting
python network_api.py devices --json
```

**Output includes:**
- Device name
- Model
- Type (uap=AP, usw=switch, ugw=gateway)
- State (1=online, 0=offline)
- Number of connected clients (for APs)

### Device Actions

```bash
# Restart device (takes 2-3 minutes)
python network_api.py restart-device aa:bb:cc:dd:ee:ff

# Adopt pending device
python network_api.py adopt aa:bb:cc:dd:ee:ff
```

## Network Statistics

### Site Health

```bash
# Overall site health with status indicators
python network_api.py health

# Detailed system information
python network_api.py sysinfo

# JSON output
python network_api.py health --json
python network_api.py sysinfo --json
```

### Traffic Statistics

```bash
# DPI (Deep Packet Inspection) statistics
python network_api.py dpi-stats

# JSON output for parsing
python network_api.py dpi-stats --json
```

## Network Configuration

### List Networks

```bash
# All WiFi networks (SSIDs)
python network_api.py wifis

# All networks (LAN, VLAN, WiFi)
python network_api.py networks

# JSON output
python network_api.py wifis --json
python network_api.py networks --json
```

## Port Forwarding

### Manage Rules

```bash
# List all port forwarding rules
python network_api.py port-forwards
python network_api.py port-forwards --json

# Create rule
python network_api.py create-port-forward "Web Server" 80 192.168.1.100 8080
python network_api.py create-port-forward "SSH" 22 192.168.1.50 22 --proto tcp

# Delete rule (use ID from list command)
python network_api.py delete-port-forward <rule-id>
```

**Protocols:** `tcp`, `udp`, `tcp_udp` (default)

## Firewall Management

### Firewall Rules

```bash
# List all firewall rules
python network_api.py firewall-rules

# JSON output
python network_api.py firewall-rules --json
```

**Output includes:**
- Rule name
- Enabled status
- Action (accept/drop/reject)
- Ruleset
- Source/destination
- Protocol and ports

### Firewall Groups

```bash
# List firewall groups (IP groups, port groups)
python network_api.py firewall-groups

# JSON output
python network_api.py firewall-groups --json
```

## Output Formats

All commands support two output formats:

### Human-Readable (Default)
- Formatted with icons and structure
- Best for interactive terminal use
- Grouped by category

### JSON (`--json` flag)
- Machine-readable structured data
- For scripting and automation
- Preserves all fields from API

## Common Workflows

### Find and Disconnect a Client

```bash
# 1. List all clients
python network_api.py clients

# 2. Find target by name/IP
python network_api.py clients | grep "suspicious"

# 3. Disconnect
python network_api.py kick aa:bb:cc:dd:ee:ff

# 4. Or block permanently
python network_api.py block aa:bb:cc:dd:ee:ff
```

### Monitor Network Health

```bash
# Check overall health
python network_api.py health

# List all devices and their status
python network_api.py devices

# Count active clients
python network_api.py clients | grep -c "📡\|📶"
```

### Bulk Operations

```bash
# Block multiple clients from file
for mac in $(cat blocked_macs.txt); do
  python network_api.py block $mac
done

# Restart all devices (one at a time with delay)
python network_api.py devices --json | jq -r '.[].mac' | while read mac; do
  python network_api.py restart-device $mac
  sleep 30
done
```

### Export Network Configuration

```bash
# Export all configuration as JSON
python network_api.py networks --json > networks.json
python network_api.py wifis --json > wifis.json
python network_api.py port-forwards --json > port-forwards.json
python network_api.py firewall-rules --json > firewall-rules.json
```

## Site Management

By default, commands operate on the `default` site. To use a different site:

```bash
# Specify site with --site flag
python network_api.py clients --site office
python network_api.py devices --site office

# Or set in environment
export UNIFI_SITE=office
python network_api.py clients
```

## Troubleshooting

### Cannot Connect

```bash
# 1. Test connectivity to host
ping $UNIFI_HOST

# 2. Test HTTPS port
curl -k https://$UNIFI_HOST:443
curl -k https://$UNIFI_HOST:8443

# 3. Detect controller type
python network_api.py detect
```

### Authentication Issues

```bash
# Verify credentials are set
echo "Host: $UNIFI_HOST"
echo "Username: $UNIFI_USERNAME"
echo "Password: [set: $(test -n "$UNIFI_PASSWORD" && echo yes || echo no)]"

# Check .env file location
ls -la .env
ls -la ../.env
```

### SSL Certificate Errors

```bash
# Set in .env
UNIFI_VERIFY_SSL=false
```

### Session Issues

Session cache stored at: `~/.cache/homelab/unifi_session_<host>.pkl`

```bash
# Clear session cache if experiencing issues
rm ~/.cache/homelab/unifi_session_*.pkl
```

## Integration with Other Tools

### Use with jq for JSON Processing

```bash
# Get IPs of all wireless clients
python network_api.py clients --json | jq -r '.[] | select(.essid) | .ip'

# Count clients per SSID
python network_api.py clients --json | jq -r '.[].essid' | sort | uniq -c

# Get offline devices
python network_api.py devices --json | jq '.[] | select(.state==0) | .name'
```

### Use with Python Import

The script can also be imported as a module:

```python
from network_api import execute

# Get clients
clients = execute("clients", {"all": False})

# Kick a client
execute("kick", {"mac": "aa:bb:cc:dd:ee:ff"})

# Get devices
devices = execute("devices", {})
```

## Notes

- **Rate Limiting**: The API has session caching (~1.5h) to avoid rate limits
- **Session Sharing**: Network and Protect APIs share the same session cache
- **Auto-Reconnect**: Session expiry is handled automatically
- **Controller Detection**: Automatically detects UCG/UDM vs Standard Controller
- **SSL Verification**: Disabled by default for self-signed certificates
