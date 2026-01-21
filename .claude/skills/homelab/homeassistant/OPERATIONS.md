# Home Assistant Operations Guide

Common tasks and workflows for managing your smart home via API.

## Quick Reference

```bash
# Using the Python CLI tool
homeassistant_api.py <command> [options]

# Basic operations
homeassistant_api.py status                      # Check HA is running
homeassistant_api.py config                      # Show configuration
homeassistant_api.py entities                    # List all entities
homeassistant_api.py entities --domain light     # List lights only

# Control devices
homeassistant_api.py turn-on light.living_room
homeassistant_api.py turn-off light.living_room --brightness 200
homeassistant_api.py set-temperature climate.thermostat --temp 21

# Automations
homeassistant_api.py list-automations
homeassistant_api.py trigger automation.motion_light
homeassistant_api.py enable automation.motion_light
homeassistant_api.py disable automation.motion_light

# Scenes & Scripts
homeassistant_api.py list-scenes
homeassistant_api.py activate-scene scene.good_night
homeassistant_api.py run-script script.morning_routine
```

## Common Workflows

### 1. Device Control

#### Turn lights on/off
```bash
# Single light
homeassistant_api.py turn-on light.kitchen

# With brightness (0-255)
homeassistant_api.py turn-on light.kitchen --brightness 128

# With color temperature (153-500 mireds)
homeassistant_api.py turn-on light.kitchen --color-temp 300

# All lights in a room (using group)
homeassistant_api.py turn-on light.living_room_lights

# Turn off
homeassistant_api.py turn-off light.kitchen
```

#### Control switches
```bash
homeassistant_api.py turn-on switch.coffee_maker
homeassistant_api.py turn-off switch.coffee_maker
```

#### Set climate/thermostat
```bash
# Set temperature
homeassistant_api.py set-temperature climate.living_room --temp 21

# Set HVAC mode
homeassistant_api.py set-hvac-mode climate.living_room --mode heat

# Modes: off, heat, cool, auto, dry, fan_only
```

### 2. Query Entity States

#### Get current state
```bash
# Single entity
homeassistant_api.py get-state light.living_room

# Output:
# State: on
# Brightness: 255
# Last changed: 2026-01-21 10:30:00
```

#### List all entities of a type
```bash
# All lights
homeassistant_api.py entities --domain light

# All sensors
homeassistant_api.py entities --domain sensor

# All automations
homeassistant_api.py entities --domain automation

# Filter by state
homeassistant_api.py entities --domain light --state on
```

#### Get sensor readings
```bash
homeassistant_api.py get-state sensor.temperature
homeassistant_api.py get-state sensor.humidity
homeassistant_api.py get-state binary_sensor.motion_hallway
```

### 3. Automation Management

#### List all automations
```bash
homeassistant_api.py list-automations

# Output:
# automation.motion_light_hallway (on)
# automation.good_night_routine (on)
# automation.morning_alarm (off)
```

#### Trigger automation manually
```bash
homeassistant_api.py trigger automation.motion_light
```

#### Enable/disable automations
```bash
# Disable (stop from running)
homeassistant_api.py disable automation.motion_light

# Enable (allow running)
homeassistant_api.py enable automation.motion_light

# Useful for:
# - Testing
# - Temporary disable during maintenance
# - Seasonal automations
```

#### Reload automations
```bash
# After editing automation.yaml
homeassistant_api.py reload-automations
```

### 4. Scene Management

#### List scenes
```bash
homeassistant_api.py list-scenes

# Output:
# scene.good_night
# scene.romantic
# scene.movie_time
# scene.bright_work
```

#### Activate scene
```bash
homeassistant_api.py activate-scene scene.good_night

# This sets all entities to their scene-defined states:
# - All lights off except nightlights (10% brightness)
# - Thermostat to 18°C
# - Alarm system armed
```

### 5. Script Execution

#### List scripts
```bash
homeassistant_api.py list-scripts

# Output:
# script.morning_routine
# script.leaving_home
# script.coming_home
```

#### Run script
```bash
homeassistant_api.py run-script script.morning_routine

# Example morning routine:
# 1. Turn on bedroom light (slowly)
# 2. Start coffee maker
# 3. Open blinds
# 4. Announce weather
```

#### Stop running script
```bash
homeassistant_api.py stop-script script.morning_routine
```

### 6. History & Monitoring

#### Get entity history
```bash
# Last 24 hours
homeassistant_api.py history sensor.temperature --hours 24

# Specific time range
homeassistant_api.py history light.living_room \
  --start "2026-01-20 10:00" \
  --end "2026-01-20 18:00"
```

#### View logbook
```bash
# Recent activity
homeassistant_api.py logbook --hours 1

# Shows:
# - Entity state changes
# - Automation triggers
# - Script executions
# - Service calls
```

### 7. Bulk Operations

#### Turn off all lights
```bash
homeassistant_api.py turn-off-all lights
```

#### Get all battery levels
```bash
homeassistant_api.py entities --domain sensor --attribute battery

# Shows all battery-powered devices and their levels
```

#### Check which lights are on
```bash
homeassistant_api.py entities --domain light --state on
```

## Advanced Use Cases

### 1. Create Custom Automation Logic

```bash
# Example: Turn on hallway light if motion detected

# 1. Check motion sensor
STATE=$(homeassistant_api.py get-state binary_sensor.hallway_motion --json | jq -r '.state')

# 2. If motion detected
if [ "$STATE" == "on" ]; then
  # Turn on light
  homeassistant_api.py turn-on light.hallway

  # Wait 5 minutes
  sleep 300

  # Check if still motion
  STATE=$(homeassistant_api.py get-state binary_sensor.hallway_motion --json | jq -r '.state')

  # Turn off if no motion
  if [ "$STATE" == "off" ]; then
    homeassistant_api.py turn-off light.hallway
  fi
fi
```

### 2. Create Scene from Current State

```bash
# Get current state of all lights in living room
homeassistant_api.py entities --domain light --area living_room --json > scene_snapshot.json

# Later: Restore this state
# (Requires parsing JSON and calling turn-on with saved attributes)
```

### 3. Monitor and Alert

```bash
# Check all battery levels and alert if low
homeassistant_api.py entities --domain sensor --attribute battery --json | \
  jq '.[] | select(.attributes.battery < 20) | .entity_id'

# Output: List of entities with low battery
```

### 4. Batch Device Control

```bash
# Turn on all lights in basement at 50% brightness
for light in $(homeassistant_api.py entities --domain light --area basement | grep entity_id); do
  homeassistant_api.py turn-on $light --brightness 128
done
```

## Troubleshooting

### Check HA is reachable
```bash
homeassistant_api.py status

# Should return:
# Home Assistant is running
# Version: 2026.1.0
```

### Verify authentication
```bash
homeassistant_api.py config

# If you get 401 Unauthorized:
# - Check HOMEASSISTANT_TOKEN in .env
# - Verify token is still valid in HA UI
```

### Debug entity not found
```bash
# List all entities
homeassistant_api.py entities | grep <search-term>

# Get exact entity_id
homeassistant_api.py entities --json | jq '.[] | select(.attributes.friendly_name | contains("Living Room"))'
```

### Service call fails
```bash
# List available services for a domain
homeassistant_api.py list-services --domain light

# Check entity supports the service
homeassistant_api.py get-state light.kitchen --json | jq '.attributes.supported_features'
```

## Integration with Other Homelab Services

### Trigger HA scene from Proxmox event
```bash
# When VM starts, activate "Work Mode" scene
proxmox_api.py status pve 100 | grep running && \
  homeassistant_api.py activate-scene scene.work_mode
```

### Network-based automations
```bash
# When specific client connects to UniFi, welcome home
network_api.py clients | grep "iPhone" && \
  homeassistant_api.py run-script script.coming_home
```

### Pi-hole integration
```bash
# Enable Pi-hole blocking when "Sleep Mode" activated
pihole_api.py enable && \
  homeassistant_api.py activate-scene scene.good_night
```

## Best Practices

1. **Use scenes for complex state changes**
   - Define scenes in HA UI
   - Activate via API
   - Easier to modify than scripts

2. **Enable/disable automations instead of deleting**
   - Seasonal automations can be toggled
   - Testing is easier
   - No need to recreate

3. **Use groups for bulk operations**
   - Create groups in HA (light.living_room_lights)
   - Control all with single command
   - More reliable than loops

4. **Monitor battery levels**
   - Regular checks prevent dead sensors
   - Set up low-battery automation
   - Replace proactively

5. **Use template rendering for complex logic**
   - Test templates via API before creating automations
   - Validate complex conditions
   - Debug issues

## Next Steps

- Create custom automations via YAML configuration
- Set up blueprints for common patterns
- Integrate with voice assistants
- Build custom dashboards
- Add more sensors and devices
