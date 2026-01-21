#!/usr/bin/env python3
"""
Home Assistant Dashboard API Client

Create and update Lovelace dashboards via WebSocket API.

Usage:
    python dashboard_api.py get                    # Get current dashboard
    python dashboard_api.py set dashboard.yaml     # Set dashboard from YAML
    python dashboard_api.py set dashboard.json     # Set dashboard from JSON
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    import websockets
except ImportError:
    print("Error: 'websockets' library required. Install with: pip install websockets", file=sys.stderr)
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None


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


class DashboardAPI:
    """Home Assistant Dashboard WebSocket API client."""

    def __init__(self):
        load_env()

        self.host = os.environ.get("HOMEASSISTANT_HOST", "homeassistant.local")
        self.token = os.environ.get("HOMEASSISTANT_TOKEN")
        self.port = int(os.environ.get("HOMEASSISTANT_PORT", "8123"))
        self.ssl = os.environ.get("HOMEASSISTANT_SSL", "false").lower() == "true"

        if not self.token:
            print("Error: HOMEASSISTANT_TOKEN required", file=sys.stderr)
            sys.exit(1)

        self.host = self.host.replace("http://", "").replace("https://", "")
        protocol = "wss" if self.ssl else "ws"
        self.ws_url = f"{protocol}://{self.host}:{self.port}/api/websocket"
        self.msg_id = 0

    def _next_id(self):
        self.msg_id += 1
        return self.msg_id

    async def _connect_and_auth(self, websocket):
        """Authenticate with Home Assistant."""
        # Receive auth_required
        msg = await websocket.recv()
        data = json.loads(msg)

        if data.get("type") != "auth_required":
            raise Exception(f"Expected auth_required, got: {data}")

        # Send auth
        await websocket.send(json.dumps({
            "type": "auth",
            "access_token": self.token
        }))

        # Receive auth result
        msg = await websocket.recv()
        data = json.loads(msg)

        if data.get("type") != "auth_ok":
            raise Exception(f"Authentication failed: {data}")

        print(f"Connected to Home Assistant {data.get('ha_version', 'unknown')}", file=sys.stderr)

    async def get_config(self, url_path: str = None) -> dict:
        """Get current lovelace configuration."""
        async with websockets.connect(self.ws_url) as ws:
            await self._connect_and_auth(ws)

            msg = {
                "id": self._next_id(),
                "type": "lovelace/config",
            }
            if url_path:
                msg["url_path"] = url_path

            await ws.send(json.dumps(msg))
            response = await ws.recv()
            data = json.loads(response)

            if not data.get("success"):
                raise Exception(f"Failed to get config: {data.get('error', data)}")

            return data.get("result", {})

    async def save_config(self, config: dict, url_path: str = None) -> bool:
        """Save lovelace configuration."""
        async with websockets.connect(self.ws_url) as ws:
            await self._connect_and_auth(ws)

            msg = {
                "id": self._next_id(),
                "type": "lovelace/config/save",
                "config": config,
            }
            if url_path:
                msg["url_path"] = url_path

            await ws.send(json.dumps(msg))
            response = await ws.recv()
            data = json.loads(response)

            if not data.get("success"):
                raise Exception(f"Failed to save config: {data.get('error', data)}")

            return True

    async def get_dashboards(self) -> list:
        """List all dashboards."""
        async with websockets.connect(self.ws_url) as ws:
            await self._connect_and_auth(ws)

            await ws.send(json.dumps({
                "id": self._next_id(),
                "type": "lovelace/dashboards/list",
            }))
            response = await ws.recv()
            data = json.loads(response)

            if not data.get("success"):
                raise Exception(f"Failed to list dashboards: {data.get('error', data)}")

            return data.get("result", [])


def load_dashboard_file(filepath: str) -> dict:
    """Load dashboard config from YAML or JSON file."""
    path = Path(filepath)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    content = path.read_text()

    if path.suffix in [".yaml", ".yml"]:
        if yaml is None:
            print("Error: 'pyyaml' library required for YAML. Install with: pip install pyyaml", file=sys.stderr)
            sys.exit(1)
        return yaml.safe_load(content)
    else:
        return json.loads(content)


async def main():
    parser = argparse.ArgumentParser(description="Home Assistant Dashboard API")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Get config
    get_cmd = subparsers.add_parser("get", help="Get dashboard configuration")
    get_cmd.add_argument("--dashboard", "-d", help="Dashboard URL path (default: main dashboard)")
    get_cmd.add_argument("--output", "-o", help="Output file (default: stdout)")

    # Set config
    set_cmd = subparsers.add_parser("set", help="Set dashboard configuration")
    set_cmd.add_argument("file", help="YAML or JSON file with dashboard config")
    set_cmd.add_argument("--dashboard", "-d", help="Dashboard URL path (default: main dashboard)")

    # List dashboards
    subparsers.add_parser("list", help="List all dashboards")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = DashboardAPI()

    if args.command == "get":
        config = await api.get_config(args.dashboard)
        output = json.dumps(config, indent=2)

        if args.output:
            Path(args.output).write_text(output)
            print(f"Dashboard saved to {args.output}")
        else:
            print(output)

    elif args.command == "set":
        config = load_dashboard_file(args.file)
        await api.save_config(config, args.dashboard)
        print(f"Dashboard updated successfully!")

    elif args.command == "list":
        dashboards = await api.get_dashboards()
        print("Dashboards:")
        for db in dashboards:
            url = db.get("url_path", "lovelace")
            title = db.get("title", "Untitled")
            mode = db.get("mode", "storage")
            print(f"  - {url}: {title} ({mode})")


if __name__ == "__main__":
    asyncio.run(main())
