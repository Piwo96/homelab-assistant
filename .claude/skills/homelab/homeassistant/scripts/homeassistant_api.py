#!/usr/bin/env python3
"""
Home Assistant API Client

Comprehensive CLI tool for managing your smart home via Home Assistant API.
Supports: entities, automations, scenes, scripts, services.

Usage:
    python homeassistant_api.py status
    python homeassistant_api.py entities --domain light
    python homeassistant_api.py turn-on light.living_room --brightness 200
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except ImportError:
    print("Error: 'requests' library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def load_env():
    """Load environment variables from .env file if present."""
    env_paths = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path(__file__).parent.parent.parent.parent.parent / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip())
            break


class HomeAssistantAPI:
    """Home Assistant REST API client."""

    def __init__(
        self,
        host: str = None,
        token: str = None,
        port: int = 8123,
        ssl: bool = False,
        verify_ssl: bool = None,
    ):
        load_env()

        self.host = host or os.environ.get("HOMEASSISTANT_HOST", "homeassistant.local")
        self.token = token or os.environ.get("HOMEASSISTANT_TOKEN")
        self.port = port or int(os.environ.get("HOMEASSISTANT_PORT", "8123"))
        self.ssl = ssl or os.environ.get("HOMEASSISTANT_SSL", "false").lower() == "true"

        verify_env = os.environ.get("HOMEASSISTANT_VERIFY_SSL", "true").lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"

        if not self.token:
            print("Error: HOMEASSISTANT_TOKEN required", file=sys.stderr)
            print("Create a Long-Lived Access Token in HA UI → Profile → Security", file=sys.stderr)
            sys.exit(1)

        # Remove http/https prefix
        self.host = self.host.replace("http://", "").replace("https://", "")

        protocol = "https" if self.ssl else "http"
        self.base_url = f"{protocol}://{self.host}:{self.port}/api"

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        self.session.verify = self.verify_ssl

    def _request(self, method: str, endpoint: str, data: dict = None, params: dict = None) -> Any:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(
                method,
                url,
                json=data,
                params=params,
                timeout=30,
            )
            response.raise_for_status()

            if response.text:
                return response.json()
            return {}
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                print("Error: Unauthorized. Check your access token.", file=sys.stderr)
            elif e.response.status_code == 404:
                print(f"Error: Not found: {endpoint}", file=sys.stderr)
            else:
                print(f"HTTP Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"API error: {e}", file=sys.stderr)
            sys.exit(1)

    # System & Config
    def get_status(self) -> dict:
        """Check if Home Assistant is running."""
        return self._request("GET", "/")

    def get_config(self) -> dict:
        """Get Home Assistant configuration."""
        return self._request("GET", "/config")

    def get_components(self) -> List[str]:
        """Get loaded components."""
        return self._request("GET", "/components")

    def get_error_log(self) -> str:
        """Get error log."""
        return self._request("GET", "/error_log")

    # States
    def get_states(self) -> List[dict]:
        """Get all entity states."""
        return self._request("GET", "/states")

    def get_state(self, entity_id: str) -> dict:
        """Get specific entity state."""
        return self._request("GET", f"/states/{entity_id}")

    def set_state(self, entity_id: str, state: str, attributes: dict = None) -> dict:
        """Set entity state."""
        data = {"state": state}
        if attributes:
            data["attributes"] = attributes
        return self._request("POST", f"/states/{entity_id}", data)

    # Services
    def get_services(self) -> List[dict]:
        """Get all available services."""
        return self._request("GET", "/services")

    def call_service(self, domain: str, service: str, data: dict = None) -> List[dict]:
        """Call a service."""
        return self._request("POST", f"/services/{domain}/{service}", data)

    # Events
    def fire_event(self, event_type: str, data: dict = None) -> dict:
        """Fire an event."""
        return self._request("POST", f"/events/{event_type}", data)

    # History
    def get_history(self, entity_id: str = None, start_time: datetime = None, end_time: datetime = None) -> List[dict]:
        """Get historical data."""
        if not start_time:
            start_time = datetime.now() - timedelta(days=1)

        timestamp = start_time.isoformat()
        endpoint = f"/history/period/{timestamp}"

        params = {}
        if entity_id:
            params["filter_entity_id"] = entity_id
        if end_time:
            params["end_time"] = end_time.isoformat()

        return self._request("GET", endpoint, params=params)

    # Logbook
    def get_logbook(self, start_time: datetime = None, end_time: datetime = None, entity_id: str = None) -> List[dict]:
        """Get logbook entries."""
        if not start_time:
            start_time = datetime.now() - timedelta(hours=1)

        timestamp = start_time.isoformat()
        endpoint = f"/logbook/{timestamp}"

        params = {}
        if entity_id:
            params["entity"] = entity_id
        if end_time:
            params["end_time"] = end_time.isoformat()

        return self._request("GET", endpoint, params=params)

    # Template rendering
    def render_template(self, template: str) -> str:
        """Render a template."""
        result = self._request("POST", "/template", {"template": template})
        return result

    # Convenience methods
    def turn_on(self, entity_id: str, **kwargs) -> List[dict]:
        """Turn on entity (light, switch, etc.)."""
        domain = entity_id.split(".")[0]
        data = {"entity_id": entity_id}
        data.update(kwargs)
        return self.call_service(domain, "turn_on", data)

    def turn_off(self, entity_id: str, **kwargs) -> List[dict]:
        """Turn off entity."""
        domain = entity_id.split(".")[0]
        data = {"entity_id": entity_id}
        data.update(kwargs)
        return self.call_service(domain, "turn_off", data)

    def toggle(self, entity_id: str) -> List[dict]:
        """Toggle entity."""
        domain = entity_id.split(".")[0]
        return self.call_service(domain, "toggle", {"entity_id": entity_id})

    # Automation helpers
    def list_automations(self) -> List[dict]:
        """List all automations."""
        states = self.get_states()
        return [s for s in states if s["entity_id"].startswith("automation.")]

    def trigger_automation(self, automation_id: str) -> List[dict]:
        """Trigger an automation."""
        return self.call_service("automation", "trigger", {"entity_id": automation_id})

    def reload_automations(self) -> List[dict]:
        """Reload all automations."""
        return self.call_service("automation", "reload", {})

    # Scene helpers
    def list_scenes(self) -> List[dict]:
        """List all scenes."""
        states = self.get_states()
        return [s for s in states if s["entity_id"].startswith("scene.")]

    def activate_scene(self, scene_id: str) -> List[dict]:
        """Activate a scene."""
        return self.call_service("scene", "turn_on", {"entity_id": scene_id})

    # Script helpers
    def list_scripts(self) -> List[dict]:
        """List all scripts."""
        states = self.get_states()
        return [s for s in states if s["entity_id"].startswith("script.")]

    def run_script(self, script_id: str) -> List[dict]:
        """Run a script."""
        script_name = script_id.replace("script.", "")
        return self.call_service("script", script_name, {})

    def stop_script(self, script_id: str) -> List[dict]:
        """Stop a running script."""
        return self.call_service("script", "turn_off", {"entity_id": script_id})


def main():
    parser = argparse.ArgumentParser(description="Home Assistant API Client")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # System
    subparsers.add_parser("status", help="Check HA status")
    subparsers.add_parser("config", help="Get configuration")
    subparsers.add_parser("components", help="List components")

    # Entities
    entities = subparsers.add_parser("entities", help="List entities")
    entities.add_argument("--domain", help="Filter by domain (light, sensor, etc.)")
    entities.add_argument("--state", help="Filter by state (on, off, etc.)")
    entities.add_argument("--area", help="Filter by area")

    get_state = subparsers.add_parser("get-state", help="Get entity state")
    get_state.add_argument("entity_id", help="Entity ID")

    # Control
    turn_on = subparsers.add_parser("turn-on", help="Turn on entity")
    turn_on.add_argument("entity_id", help="Entity ID")
    turn_on.add_argument("--brightness", type=int, help="Brightness (0-255)")
    turn_on.add_argument("--color-temp", type=int, help="Color temperature (mireds)")

    turn_off = subparsers.add_parser("turn-off", help="Turn off entity")
    turn_off.add_argument("entity_id", help="Entity ID")

    toggle = subparsers.add_parser("toggle", help="Toggle entity")
    toggle.add_argument("entity_id", help="Entity ID")

    # Services
    call_service = subparsers.add_parser("call-service", help="Call a service")
    call_service.add_argument("domain", help="Service domain")
    call_service.add_argument("service", help="Service name")
    call_service.add_argument("--entity", help="Entity ID")
    call_service.add_argument("--data", help="JSON data")

    # Automations
    subparsers.add_parser("list-automations", help="List automations")

    trigger = subparsers.add_parser("trigger", help="Trigger automation")
    trigger.add_argument("automation_id", help="Automation ID")

    enable_auto = subparsers.add_parser("enable", help="Enable automation")
    enable_auto.add_argument("automation_id", help="Automation ID")

    disable_auto = subparsers.add_parser("disable", help="Disable automation")
    disable_auto.add_argument("automation_id", help="Automation ID")

    subparsers.add_parser("reload-automations", help="Reload automations")

    # Scenes
    subparsers.add_parser("list-scenes", help="List scenes")

    activate = subparsers.add_parser("activate-scene", help="Activate scene")
    activate.add_argument("scene_id", help="Scene ID")

    # Scripts
    subparsers.add_parser("list-scripts", help="List scripts")

    run_script = subparsers.add_parser("run-script", help="Run script")
    run_script.add_argument("script_id", help="Script ID")

    stop_script = subparsers.add_parser("stop-script", help="Stop script")
    stop_script.add_argument("script_id", help="Script ID")

    # History
    history = subparsers.add_parser("history", help="Get history")
    history.add_argument("entity_id", nargs="?", help="Entity ID")
    history.add_argument("--hours", type=int, default=24, help="Hours to look back")

    # Logbook
    logbook = subparsers.add_parser("logbook", help="Get logbook")
    logbook.add_argument("--hours", type=int, default=1, help="Hours to look back")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = HomeAssistantAPI()

    result = None

    # System commands
    if args.command == "status":
        status = api.get_status()
        config = api.get_config()
        if args.json:
            result = {"status": status, "config": config}
        else:
            print(f"Home Assistant is running")
            print(f"Version: {config.get('version', 'unknown')}")
            print(f"Location: {config.get('location_name', 'unknown')}")
            return

    elif args.command == "config":
        result = api.get_config()

    elif args.command == "components":
        result = api.get_components()

    # Entity commands
    elif args.command == "entities":
        states = api.get_states()
        if args.domain:
            states = [s for s in states if s["entity_id"].startswith(f"{args.domain}.")]
        if args.state:
            states = [s for s in states if s["state"] == args.state]
        if args.area:
            states = [s for s in states if s.get("attributes", {}).get("area_id") == args.area]

        if args.json:
            result = states
        else:
            for state in states:
                entity_id = state["entity_id"]
                state_val = state["state"]
                friendly = state.get("attributes", {}).get("friendly_name", "")
                print(f"{entity_id}\t{state_val}\t{friendly}")
            return

    elif args.command == "get-state":
        state = api.get_state(args.entity_id)
        if args.json:
            result = state
        else:
            print(f"Entity: {state['entity_id']}")
            print(f"State: {state['state']}")
            print(f"Last changed: {state['last_changed']}")
            if state.get("attributes"):
                print("Attributes:")
                for key, value in state["attributes"].items():
                    print(f"  {key}: {value}")
            return

    # Control commands
    elif args.command == "turn-on":
        kwargs = {}
        if args.brightness is not None:
            kwargs["brightness"] = args.brightness
        if args.color_temp is not None:
            kwargs["color_temp"] = args.color_temp
        result = api.turn_on(args.entity_id, **kwargs)
        if not args.json:
            print(f"Turned on {args.entity_id}")
            return

    elif args.command == "turn-off":
        result = api.turn_off(args.entity_id)
        if not args.json:
            print(f"Turned off {args.entity_id}")
            return

    elif args.command == "toggle":
        result = api.toggle(args.entity_id)
        if not args.json:
            print(f"Toggled {args.entity_id}")
            return

    # Service commands
    elif args.command == "call-service":
        data = {}
        if args.entity:
            data["entity_id"] = args.entity
        if args.data:
            data.update(json.loads(args.data))
        result = api.call_service(args.domain, args.service, data)

    # Automation commands
    elif args.command == "list-automations":
        automations = api.list_automations()
        if args.json:
            result = automations
        else:
            for auto in automations:
                entity_id = auto["entity_id"]
                state = auto["state"]
                friendly = auto.get("attributes", {}).get("friendly_name", "")
                print(f"{entity_id}\t({state})\t{friendly}")
            return

    elif args.command == "trigger":
        result = api.trigger_automation(args.automation_id)
        if not args.json:
            print(f"Triggered {args.automation_id}")
            return

    elif args.command == "enable":
        result = api.turn_on(args.automation_id)
        if not args.json:
            print(f"Enabled {args.automation_id}")
            return

    elif args.command == "disable":
        result = api.turn_off(args.automation_id)
        if not args.json:
            print(f"Disabled {args.automation_id}")
            return

    elif args.command == "reload-automations":
        result = api.reload_automations()
        if not args.json:
            print("Reloaded automations")
            return

    # Scene commands
    elif args.command == "list-scenes":
        scenes = api.list_scenes()
        if args.json:
            result = scenes
        else:
            for scene in scenes:
                entity_id = scene["entity_id"]
                friendly = scene.get("attributes", {}).get("friendly_name", "")
                print(f"{entity_id}\t{friendly}")
            return

    elif args.command == "activate-scene":
        result = api.activate_scene(args.scene_id)
        if not args.json:
            print(f"Activated {args.scene_id}")
            return

    # Script commands
    elif args.command == "list-scripts":
        scripts = api.list_scripts()
        if args.json:
            result = scripts
        else:
            for script in scripts:
                entity_id = script["entity_id"]
                friendly = script.get("attributes", {}).get("friendly_name", "")
                print(f"{entity_id}\t{friendly}")
            return

    elif args.command == "run-script":
        result = api.run_script(args.script_id)
        if not args.json:
            print(f"Running {args.script_id}")
            return

    elif args.command == "stop-script":
        result = api.stop_script(args.script_id)
        if not args.json:
            print(f"Stopped {args.script_id}")
            return

    # History & Logbook
    elif args.command == "history":
        start_time = datetime.now() - timedelta(hours=args.hours)
        result = api.get_history(args.entity_id, start_time)

    elif args.command == "logbook":
        start_time = datetime.now() - timedelta(hours=args.hours)
        result = api.get_logbook(start_time)

    if result is not None:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
