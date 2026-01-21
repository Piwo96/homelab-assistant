#!/usr/bin/env python3
"""
UniFi Protect API Client

Camera and NVR management for UniFi Protect.
Uses same authentication as UniFi Controller.

Usage:
    python protect_api.py cameras
    python protect_api.py snapshot <camera-id>
    python protect_api.py events --last 24h
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Reuse UniFi API client
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "unifi-network" / "scripts"))
try:
    from network_api import UniFiAPI, load_env
except ImportError:
    print("Error: Cannot import UniFi API. Ensure unifi_api.py exists.", file=sys.stderr)
    sys.exit(1)


class ProtectAPI(UniFiAPI):
    """UniFi Protect API client extending UniFi API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Override base URL for Protect
        self.protect_base = f"{self.base_url.replace('/proxy/network', '')}/proxy/protect/api"

    def _protect_request(self, method: str, endpoint: str, data: dict = None):
        """Make Protect API request."""
        url = f"{self.protect_base}{endpoint}"
        headers = {}
        if self.csrf_token and method in ["POST", "PUT", "DELETE", "PATCH"]:
            headers["X-CSRF-Token"] = self.csrf_token

        try:
            response = self.session.request(
                method, url, headers=headers, json=data, timeout=30
            )
            response.raise_for_status()
            return response.json() if response.text else {}
        except Exception as e:
            print(f"Protect API error: {e}", file=sys.stderr)
            sys.exit(1)

    def get_cameras(self):
        """Get all cameras."""
        return self._protect_request("GET", "/cameras")

    def get_camera(self, camera_id: str):
        """Get camera details."""
        return self._protect_request("GET", f"/cameras/{camera_id}")

    def update_camera(self, camera_id: str, settings: dict):
        """Update camera settings."""
        return self._protect_request("PATCH", f"/cameras/{camera_id}", settings)

    def get_snapshot(self, camera_id: str, width: int = None, height: int = None):
        """Get camera snapshot (returns binary data)."""
        params = []
        if width:
            params.append(f"w={width}")
        if height:
            params.append(f"h={height}")
        query = f"?{'&'.join(params)}" if params else ""

        url = f"{self.protect_base}/cameras/{camera_id}/snapshot{query}"
        response = self.session.get(url, timeout=10)
        return response.content

    def get_events(self, start: int = None, end: int = None, types: list = None):
        """Get events."""
        params = []
        if start:
            params.append(f"start={start}")
        if end:
            params.append(f"end={end}")
        if types:
            params.append(f"types={','.join(types)}")
        query = f"?{'&'.join(params)}" if params else ""

        return self._protect_request("GET", f"/events{query}")

    def get_nvr(self):
        """Get NVR information."""
        return self._protect_request("GET", "/nvr")

    def get_sensors(self):
        """Get all sensors."""
        return self._protect_request("GET", "/sensors")

    def get_lights(self):
        """Get all lights."""
        return self._protect_request("GET", "/lights")

    def control_light(self, light_id: str, on: bool):
        """Turn light on/off."""
        return self._protect_request("PATCH", f"/lights/{light_id}", {"lightOnSettings": {"isLedForceOn": on}})


def main():
    parser = argparse.ArgumentParser(description="UniFi Protect API Client")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Cameras
    subparsers.add_parser("cameras", help="List all cameras")

    camera = subparsers.add_parser("camera", help="Get camera details")
    camera.add_argument("id", help="Camera ID")

    snapshot = subparsers.add_parser("snapshot", help="Get camera snapshot")
    snapshot.add_argument("id", help="Camera ID")
    snapshot.add_argument("--output", "-o", help="Output file (default: snapshot.jpg)")
    snapshot.add_argument("--width", type=int, help="Width")
    snapshot.add_argument("--height", type=int, help="Height")

    # Events
    events = subparsers.add_parser("events", help="List events")
    events.add_argument("--last", help="Last N hours (e.g., 24h, 1h)")
    events.add_argument("--types", help="Event types (comma-separated: motion,ring)")

    # Devices
    subparsers.add_parser("nvr", help="NVR information")
    subparsers.add_parser("sensors", help="List sensors")
    subparsers.add_parser("lights", help="List lights")

    light_on = subparsers.add_parser("light-on", help="Turn light on")
    light_on.add_argument("id", help="Light ID")

    light_off = subparsers.add_parser("light-off", help="Turn light off")
    light_off.add_argument("id", help="Light ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = ProtectAPI()
    print(f"Connected to Protect ({api.controller_type})", file=sys.stderr)

    result = None

    if args.command == "cameras":
        result = api.get_cameras()
    elif args.command == "camera":
        result = api.get_camera(args.id)
    elif args.command == "snapshot":
        data = api.get_snapshot(args.id, args.width, args.height)
        output = args.output or f"snapshot_{args.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        with open(output, "wb") as f:
            f.write(data)
        print(f"Snapshot saved to {output}")
        return
    elif args.command == "events":
        start = end = None
        if args.last:
            hours = int(args.last.replace("h", ""))
            end = int(datetime.now().timestamp() * 1000)
            start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        types = args.types.split(",") if args.types else None
        result = api.get_events(start, end, types)
    elif args.command == "nvr":
        result = api.get_nvr()
    elif args.command == "sensors":
        result = api.get_sensors()
    elif args.command == "lights":
        result = api.get_lights()
    elif args.command == "light-on":
        api.control_light(args.id, True)
        print(f"Light {args.id} turned on")
        return
    elif args.command == "light-off":
        api.control_light(args.id, False)
        print(f"Light {args.id} turned off")
        return

    if result:
        print(json.dumps(result, indent=2) if args.json else json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
