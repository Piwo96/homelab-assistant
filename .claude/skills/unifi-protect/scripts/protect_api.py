#!/usr/bin/env python3
"""
UniFi Protect API Client

Camera and NVR management for UniFi Protect.
Uses same authentication as UniFi Controller.

Usage:
    python protect_api.py cameras
    python protect_api.py snapshot <camera-id>
    python protect_api.py events --last 24h --camera Einfahrt
    python protect_api.py detections --last 6h --camera Einfahrt
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

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

    def get_events(self, start: int = None, end: int = None, types: list = None, camera_id: str = None):
        """Get events, optionally filtered by camera."""
        params = []
        if start:
            params.append(f"start={start}")
        if end:
            params.append(f"end={end}")
        if types:
            params.append(f"types={','.join(types)}")
        query = f"?{'&'.join(params)}" if params else ""

        events = self._protect_request("GET", f"/events{query}")

        # Filter by camera if specified
        if camera_id:
            events = [e for e in events if e.get("camera") == camera_id]

        return events

    def resolve_camera_id(self, camera_ref: str) -> Optional[str]:
        """Resolve camera name to ID. Returns ID if already an ID."""
        cameras = self.get_cameras()
        for cam in cameras:
            if cam.get("id") == camera_ref or cam.get("name", "").lower() == camera_ref.lower():
                return cam.get("id")
        return None

    def get_detections(self, start: int = None, end: int = None, camera_id: str = None,
                       detection_type: str = None) -> list:
        """Get smart detections (license plates, faces, vehicles, persons).

        Args:
            start: Start timestamp in ms
            end: End timestamp in ms
            camera_id: Filter by camera ID
            detection_type: Filter by type (plate, face, vehicle, person)

        Returns:
            List of detection dicts with time, type, details
        """
        events = self.get_events(start, end, types=["smartDetectZone"], camera_id=camera_id)
        detections = []

        for event in events:
            ts = datetime.fromtimestamp(event["start"] / 1000)
            metadata = event.get("metadata", {})
            thumbnails = metadata.get("detectedThumbnails", [])

            for thumb in thumbnails:
                det_type = thumb.get("type")

                # Skip if filtering by type and doesn't match
                if detection_type:
                    if detection_type == "plate" and det_type != "vehicle":
                        continue
                    if detection_type == "face" and det_type != "face":
                        continue
                    if detection_type == "vehicle" and det_type != "vehicle":
                        continue
                    if detection_type == "person" and det_type != "person":
                        continue

                detection = {
                    "time": ts.strftime("%Y-%m-%d %H:%M"),
                    "type": det_type,
                    "confidence": thumb.get("confidence", 0),
                }

                # Extract license plate info
                if det_type == "vehicle" and thumb.get("name"):
                    detection["plate"] = thumb.get("name")
                    attrs = thumb.get("attributes", {})
                    detection["vehicle_type"] = attrs.get("vehicleType", {}).get("val", "unknown")
                    detection["color"] = attrs.get("color", {}).get("val", "unknown")
                    detections.append(detection)

                # Extract face info
                elif det_type == "face":
                    attrs = thumb.get("attributes", {})
                    detection["has_mask"] = attrs.get("faceMask", {}).get("val") == "mask"
                    detections.append(detection)

                # Extract person (only if not filtering for plates/faces)
                elif det_type == "person" and detection_type in (None, "person"):
                    detections.append(detection)

        return detections

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
    events.add_argument("--camera", help="Filter by camera name or ID")

    # Smart Detections
    detections = subparsers.add_parser("detections", help="List smart detections (plates, faces, vehicles)")
    detections.add_argument("--last", help="Last N hours (e.g., 24h, 1h)", default="6h")
    detections.add_argument("--camera", help="Filter by camera name or ID")
    detections.add_argument("--type", choices=["plate", "face", "vehicle", "person"],
                            help="Filter by detection type")

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
        camera_id = api.resolve_camera_id(args.camera) if args.camera else None
        if args.camera and not camera_id:
            print(f"Camera not found: {args.camera}", file=sys.stderr)
            sys.exit(1)
        result = api.get_events(start, end, types, camera_id)
    elif args.command == "detections":
        hours = int(args.last.replace("h", ""))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        camera_id = api.resolve_camera_id(args.camera) if args.camera else None
        if args.camera and not camera_id:
            print(f"Camera not found: {args.camera}", file=sys.stderr)
            sys.exit(1)
        detections = api.get_detections(start, end, camera_id, args.type)

        if args.json:
            result = detections
        else:
            # Pretty print detections
            if not detections:
                print("No detections found.")
                return

            # Group by type for display
            plates = [d for d in detections if d.get("plate")]
            faces = [d for d in detections if d.get("type") == "face"]
            persons = [d for d in detections if d.get("type") == "person" and "plate" not in d]

            if plates:
                print("\n=== License Plates ===")
                print(f"{'Time':<18} {'Plate':<12} {'Vehicle':<10} {'Color':<10} {'Conf':<6}")
                print("-" * 58)
                for d in plates:
                    print(f"{d['time']:<18} {d['plate']:<12} {d['vehicle_type']:<10} {d['color']:<10} {d['confidence']}%")

            if faces:
                print("\n=== Faces ===")
                print(f"{'Time':<18} {'Confidence':<12} {'Mask':<6}")
                print("-" * 38)
                for d in faces:
                    mask = "Yes" if d.get("has_mask") else "No"
                    print(f"{d['time']:<18} {d['confidence']}%{'':<10} {mask:<6}")

            if persons and not args.type:
                print(f"\n=== Persons ===")
                print(f"Found {len(persons)} person detections (use --type person for details)")

            return
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
