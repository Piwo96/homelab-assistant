# Home Assistant Troubleshooting

Known issues and solutions. This document grows through self-annealing.

## Connection Issues

### Connection Refused
```
Error: Cannot connect to homeassistant.local:8123
```
**Cause**: Wrong host, HA not running, or network issue.
**Solution**:
1. Verify host: `ping homeassistant.local`
2. Try IP instead of hostname
3. Check HA is running (via direct access or SSH)
4. Verify port 8123 is correct (or your configured port)

### DNS Resolution Fails
```
Error: Could not resolve hostname
```
**Cause**: mDNS not working for `.local` domain.
**Solution**:
1. Use IP address: `HOMEASSISTANT_HOST=192.168.1.100:8123`
2. Or add hostname to `/etc/hosts`
3. Or fix mDNS on your network

### Timeout
```
Error: Connection timed out
```
**Cause**: Network issue or HA overloaded.
**Solution**:
1. Check network connectivity
2. Check HA CPU/memory usage
3. Restart HA if unresponsive
4. Increase timeout in script if needed

## Authentication Issues

### 401 Unauthorized
```
Error: 401 - Invalid access token
```
**Cause**: Token invalid, expired, or revoked.
**Solution**:
1. Create new long-lived access token:
   - HA Web UI → Profile (bottom left)
   - Scroll to "Long-Lived Access Tokens"
   - Create Token → Copy immediately
2. Update `HOMEASSISTANT_TOKEN` in `.env`
3. Token is shown only once - create new if lost

### 403 Forbidden
```
Error: 403 - Insufficient permissions
```
**Cause**: Token user lacks permissions.
**Solution**:
1. Verify user has admin permissions
2. Check HA user permissions in Configuration → Users
3. Create token with admin user

## Entity Issues

### Entity Not Found
```
Error: Entity 'light.living_room' not found
```
**Cause**: Wrong entity_id or entity removed.
**Solution**:
1. List entities: `homeassistant_api.py entities --domain light`
2. Check exact entity_id spelling
3. Entity may have been renamed or removed
4. Check Developer Tools → States in HA web UI

### Entity Unavailable
```
State: unavailable
```
**Cause**: Device offline or integration issue.
**Solution**:
1. Check physical device is powered on
2. Check network connectivity to device
3. Restart integration in HA
4. Check HA logs for errors

### Wrong Domain
**Cause**: Using wrong service for entity type.
**Solution**:
- Lights use `light.turn_on` / `light.turn_off`
- Switches use `switch.turn_on` / `switch.turn_off`
- Check entity domain prefix (before the dot)

## Automation Issues

### Automation Not Triggering
**Cause**: Multiple possible reasons.
**Solution**:
1. Check automation is enabled: `list-automations`
2. Verify trigger conditions are met
3. Check automation trace in HA web UI
4. Manually trigger to test: `trigger automation.xxx`

### Manual Trigger Fails
```
Error: Automation trigger failed
```
**Cause**: Automation disabled or conditions not met.
**Solution**:
1. Enable automation: `enable-automation automation.xxx`
2. Check if automation has conditions that block execution
3. View automation YAML in HA for requirements

## Script Issues

### Script Requires Variables
```
Error: Missing required variable 'target'
```
**Cause**: Script expects input variables.
**Solution**:
1. Check script definition for required fields
2. Pass variables: `run-script script.xxx --data '{"target": "value"}'`
3. Or modify script to have defaults

## Service Issues

### Unsupported Attribute
```
Warning: Attribute 'rgb_color' ignored
```
**Cause**: Device doesn't support the attribute.
**Solution**:
1. Check device capabilities in HA
2. Not all lights support RGB, brightness, etc.
3. Use only supported attributes for that device

### Service Not Found
```
Error: Service 'custom_service.xxx' not found
```
**Cause**: Custom integration not loaded or wrong service name.
**Solution**:
1. Check integration is installed and configured
2. Verify service name in Developer Tools → Services
3. Restart HA after installing integrations

## Performance Issues

### Slow Response
**Cause**: Large HA installation or slow hardware.
**Solution**:
1. Limit entity queries with filters: `--domain light`
2. Check HA resource usage
3. Consider upgrading HA hardware

### Rate Limiting
**Cause**: Too many API requests.
**Solution**:
1. Add delays between bulk operations
2. Batch related operations where possible
3. HA doesn't have strict rate limits, but respect server resources

## Dashboard Issues

### WebSocket Connection Failed
```
Error: Cannot connect to WebSocket
```
**Cause**: Wrong protocol, port, or network issue.
**Solution**:
1. Verify host and port are correct
2. Check if using SSL: set `HOMEASSISTANT_SSL=true` if using HTTPS
3. Test REST API first: `homeassistant_api.py status`
4. Check firewall allows WebSocket connections

### Missing Dependencies
```
Error: 'websockets' library required
```
**Cause**: Dashboard API requires additional Python packages.
**Solution**:
```bash
pip install websockets pyyaml
```

### Dashboard Save Failed
```
Error: Failed to save config: Invalid configuration
```
**Cause**: Dashboard YAML/JSON is malformed or contains invalid entities.
**Solution**:
1. Validate YAML syntax: `python -c "import yaml; yaml.safe_load(open('dashboard.yaml'))"`
2. Validate JSON: `python -m json.tool dashboard.json`
3. Check all entity_ids exist: `homeassistant_api.py entities | grep <entity>`
4. Use `--dry-run` to preview changes first

### Dashboard Optimization No Changes
```
Dashboard is already optimized!
```
**Cause**: Dashboard already follows best practices.
**Solution**: This is not an error - dashboard is in good shape.

### Backup File Not Found
```
Error: File not found: backup.json
```
**Cause**: Trying to restore from non-existent backup.
**Solution**:
1. List backups: `ls -la *.json`
2. Create new backup: `dashboard_api.py get -o backup.json`
3. Verify file path is correct

---

## Adding New Issues

When you encounter a new issue:

1. Document the error message exactly
2. Identify the root cause
3. Provide a clear solution
4. Add to appropriate section above
