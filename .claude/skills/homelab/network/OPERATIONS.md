# UniFi Operations Guide

Common operations for managing UniFi networks, clients, and devices.

## Initial Setup

Determine your controller type:
```bash
python unifi_api.py detect
```

This auto-detects:
- Standard Controller (port 8443)
- UDM/UDM Pro (port 443, `/proxy/network` prefix)

## Client Management

### List Clients

```bash
# All active clients
python unifi_api.py clients

# All known clients (includes inactive)
python unifi_api.py clients --all

# Filter by hostname
python unifi_api.py clients --filter "iPhone"
```

### Client Actions

```bash
# Kick client (disconnect)
python unifi_api.py kick aa:bb:cc:dd:ee:ff

# Block client
python unifi_api.py block aa:bb:cc:dd:ee:ff

# Unblock client
python unifi_api.py unblock aa:bb:cc:dd:ee:ff

# Get client details
python unifi_api.py client-info aa:bb:cc:dd:ee:ff
```

## Device Management

### List Devices

```bash
# All devices
python unifi_api.py devices

# Filter by type
python unifi_api.py devices --type uap    # Access Points
python unifi_api.py devices --type usw    # Switches
python unifi_api.py devices --type ugw    # Gateways
```

### Device Actions

```bash
# Restart device
python unifi_api.py restart-device aa:bb:cc:dd:ee:ff

# Adopt pending device
python unifi_api.py adopt aa:bb:cc:dd:ee:ff

# Locate device (LED blink)
python unifi_api.py locate aa:bb:cc:dd:ee:ff

# Get device details
python unifi_api.py device-info aa:bb:cc:dd:ee:ff
```

### Firmware Updates

```bash
# Check for updates
python unifi_api.py check-updates

# Upgrade specific device
python unifi_api.py upgrade aa:bb:cc:dd:ee:ff
```

## Network Statistics

### Site Health

```bash
# Overall site health
python unifi_api.py health

# Detailed system info
python unifi_api.py sysinfo
```

### Traffic Statistics

```bash
# DPI (Deep Packet Inspection) stats
python unifi_api.py dpi-stats

# Top applications
python unifi_api.py top-apps --count 10

# Top clients by traffic
python unifi_api.py top-traffic --count 10
```

### Recent Events

```bash
# Last 100 events
python unifi_api.py events

# Filter by type
python unifi_api.py events --type user
python unifi_api.py events --type admin
```

## WiFi Network Management

### List Networks

```bash
# All WiFi networks
python unifi_api.py wifis

# All networks (LAN, VLAN, etc.)
python unifi_api.py networks
```

### Enable/Disable WiFi

```bash
# Disable WiFi network
python unifi_api.py wifi-disable "Guest WiFi"

# Enable WiFi network
python unifi_api.py wifi-enable "Guest WiFi"
```

### Guest Portal

```bash
# Create guest voucher
python unifi_api.py create-voucher --duration 1440 --quota 1  # 24h, 1 device

# List active vouchers
python unifi_api.py vouchers
```

## Port Forwarding

### Manage Rules

```bash
# List port forwarding rules
python unifi_api.py port-forwards

# Create rule
python unifi_api.py add-port-forward \
  --name "Web Server" \
  --dst-port 80 \
  --fwd-ip 192.168.1.100 \
  --fwd-port 8080

# Delete rule
python unifi_api.py delete-port-forward <rule-id>
```

## System Management (UDM Only)

### Backups

```bash
# List backups
python unifi_api.py backups

# Create backup
python unifi_api.py create-backup
```

### System Control

```bash
# Reboot UDM
python unifi_api.py reboot-system

# Power off UDM (caution!)
python unifi_api.py poweroff-system
```

## Monitoring & Alerts

### Real-time Monitoring

```bash
# Watch client count
python unifi_api.py watch-clients

# Monitor bandwidth
python unifi_api.py watch-bandwidth
```

### Custom Queries

```bash
# Clients on specific SSID
python unifi_api.py clients --ssid "Main WiFi"

# Devices offline
python unifi_api.py devices --status offline

# Clients by IP range
python unifi_api.py clients --ip-range 192.168.1.0/24
```

## Bulk Operations

### Block Multiple Clients

```bash
# From file (one MAC per line)
python unifi_api.py bulk-block macs.txt

# From command
cat suspicious_macs.txt | xargs -I {} python unifi_api.py block {}
```

### Restart All APs

```bash
# Get all AP MACs
python unifi_api.py devices --type uap --macs-only > aps.txt

# Restart each (with delay)
for mac in $(cat aps.txt); do
  python unifi_api.py restart-device $mac
  sleep 30
done
```

## Troubleshooting

### Connection Issues

1. **Cannot connect:**
   ```bash
   # Test connectivity
   curl -k https://192.168.10.xxx:8443

   # Check controller type
   python unifi_api.py detect
   ```

2. **Login fails:**
   - Verify username/password in `.env`
   - Check if account has admin privileges
   - UDM: Try `/api/auth/login` instead of `/api/login`

3. **SSL errors:**
   - Set `UNIFI_VERIFY_SSL=false` in `.env`
   - Or add certificate to trust store

### Common Errors

**401 Unauthorized:**
- Session expired → Re-login automatically handled
- Invalid credentials → Check UNIFI_USERNAME/PASSWORD

**403 Forbidden:**
- Account lacks permissions
- Need admin or super-admin role

**404 Not Found:**
- Wrong site name (try `default`)
- UDM: Missing `/proxy/network` prefix

**429 Rate Limited:**
- Too many requests
- Implement delays between calls

## Integration Examples

### Auto-block suspicious clients

```bash
# Monitor and auto-block clients with excessive failed auth
python unifi_api.py events --type user | \
  grep "authentication failure" | \
  awk '{print $5}' | \
  xargs -I {} python unifi_api.py block {}
```

### Daily network report

```bash
# Generate daily stats
python unifi_api.py health --json > /tmp/health.json
python unifi_api.py clients --json > /tmp/clients.json
python unifi_api.py dpi-stats --json > /tmp/dpi.json

# Email report
mail -s "Daily UniFi Report" admin@example.com < /tmp/health.json
```

### Guest WiFi scheduler

```bash
# Disable guest WiFi at night
0 23 * * * python unifi_api.py wifi-disable "Guest"

# Enable in morning
0 7 * * * python unifi_api.py wifi-enable "Guest"
```

## Cloud API Operations

For read-only cloud access:

```bash
# Set Cloud API key
export UNIFI_CLOUD_API_KEY=your-key

# List hosts
python unifi_api.py cloud-hosts

# List sites
python unifi_api.py cloud-sites

# List devices
python unifi_api.py cloud-devices
```

Note: Cloud API is read-only. Use local API for write operations.
