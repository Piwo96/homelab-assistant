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
        
        # Camera not found - show available cameras
        available = [cam.get("name", "Unnamed") for cam in cameras]
        print(f"Camera not found: {camera_ref}", file=sys.stderr)
        print(f"Available cameras: {', '.join(available)}", file=sys.stderr)
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


def execute(action: str, args: dict):
    """Execute a UniFi Protect action directly (no CLI).

    Args:
        action: Command name (e.g. "cameras", "events", "snapshot")
        args: Dict of arguments (e.g. {"id": "camera_id", "last": "24h"})

    Returns:
        Raw Python data (dict/list/bytes)

    Raises:
        ValueError: Unknown action
        KeyError: Missing required argument
    """
    api = ProtectAPI()

    if action == "cameras":
        return api.get_cameras()
    elif action == "camera":
        return api.get_camera(args["id"])
    elif action == "snapshot":
        data = api.get_snapshot(args["id"], args.get("width"), args.get("height"))
        output = args.get("output") or f"snapshot_{args['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        with open(output, "wb") as f:
            f.write(data)
        return {"file": output, "size": len(data)}
    elif action == "events":
        hours = int(args.get("last", "24h").replace("h", ""))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        types = args.get("types", "").split(",") if args.get("types") else None
        camera_id = None
        if args.get("camera"):
            camera_id = api.resolve_camera_id(args["camera"])
            if not camera_id:
                raise ValueError(f"Camera not found: {args['camera']}")
        events = api.get_events(start, end, types, camera_id)
        if args.get("limit"):
            events = events[:int(args["limit"])]
        return events
    elif action == "detections":
        hours = int(args.get("last", "6h").replace("h", ""))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        camera_id = None
        if args.get("camera"):
            camera_id = api.resolve_camera_id(args["camera"])
            if not camera_id:
                raise ValueError(f"Camera not found: {args['camera']}")
        return api.get_detections(start, end, camera_id, args.get("type"))
    elif action == "nvr":
        return api.get_nvr()
    elif action == "sensors":
        return api.get_sensors()
    elif action == "lights":
        return api.get_lights()
    elif action == "light-on":
        return api.control_light(args["id"], True)
    elif action == "light-off":
        return api.control_light(args["id"], False)
    else:
        raise ValueError(f"Unknown action: {action}")


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
    events.add_argument("--last", help="Last N hours (e.g., 24h, 1h)", default="24h")
    events.add_argument("--types", help="Event types (comma-separated: motion,ring)")
    events.add_argument("--camera", help="Filter by camera name or ID")
    events.add_argument("--limit", type=int, help="Limit number of events returned")

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
        cameras = api.get_cameras()
        if args.json:
            result = cameras
        else:
            if not cameras:
                print("Keine Kameras gefunden.")
                return

            print(f"📹 **Kameras** ({len(cameras)} Geräte)\n")
            for cam in cameras:
                name = cam.get("name", "Unbekannt")
                state = cam.get("state", "unknown")
                is_recording = cam.get("isRecording", False)
                is_connected = state == "CONNECTED"

                status_icon = "🟢" if is_connected else "🔴"
                rec_icon = "⏺️" if is_recording else ""

                # Get resolution
                channels = cam.get("channels", [])
                resolution = ""
                if channels:
                    ch = channels[0]
                    resolution = f"{ch.get('width', '?')}x{ch.get('height', '?')}"

                print(f"{status_icon} **{name}** {rec_icon}")
                print(f"   Modell: {cam.get('type', 'Unbekannt')}")
                if resolution:
                    print(f"   Auflösung: {resolution}")
                print()
            return

    elif args.command == "camera":
        cam = api.get_camera(args.id)
        if args.json:
            result = cam
        else:
            name = cam.get("name", "Unbekannt")
            state = cam.get("state", "unknown")
            is_connected = state == "CONNECTED"
            status_icon = "🟢" if is_connected else "🔴"

            print(f"{status_icon} **{name}**")
            print(f"   ID: {cam.get('id')}")
            print(f"   Modell: {cam.get('type', 'Unbekannt')}")
            print(f"   Status: {state}")
            print(f"   Aufnahme: {'Ja' if cam.get('isRecording') else 'Nein'}")
            print(f"   Mikrofon: {'An' if cam.get('isMicEnabled') else 'Aus'}")
            print(f"   IP: {cam.get('host', 'Unbekannt')}")
            return
    elif args.command == "snapshot":
        data = api.get_snapshot(args.id, args.width, args.height)
        output = args.output or f"snapshot_{args.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        with open(output, "wb") as f:
            f.write(data)
        print(f"Snapshot saved to {output}")
        return
    elif args.command == "events":
        hours = int(args.last.replace("h", ""))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        types = args.types.split(",") if args.types else None
        camera_id = api.resolve_camera_id(args.camera) if args.camera else None
        if args.camera and not camera_id:
            print(f"Camera not found: {args.camera}", file=sys.stderr)
            sys.exit(1)
        events = api.get_events(start, end, types, camera_id)

        if args.json:
            result = events
        else:
            # Pretty print events
            if not events:
                print(f"Keine Ereignisse in den letzten {hours} Stunden.")
                return

            # Build camera ID to name mapping
            cameras = {c["id"]: c.get("name", "Unknown") for c in api.get_cameras()}

            # Event type icons
            type_icons = {
                "motion": "🏃",
                "smartDetectZone": "🔍",
                "ring": "🔔",
                "sensorMotion": "📡",
                "sensorContact": "🚪",
            }

            # Smart detect type translations
            smart_types = {
                "person": "Person",
                "vehicle": "Fahrzeug",
                "animal": "Tier",
                "package": "Paket",
                "licensePlate": "Kennzeichen",
                "face": "Gesicht",
            }

            print(f"📹 **Kamera-Ereignisse** (letzte {hours}h)\n")

            # Group events by camera
            by_camera = {}
            for e in events:
                cam_id = e.get("camera")
                cam_name = cameras.get(cam_id, "Unbekannt")
                if cam_name not in by_camera:
                    by_camera[cam_name] = []
                by_camera[cam_name].append(e)

            for cam_name, cam_events in by_camera.items():
                print(f"**{cam_name}** ({len(cam_events)} Ereignisse)")

                # Show last 5 events per camera
                for e in cam_events[:5]:
                    ts = datetime.fromtimestamp(e["start"] / 1000)
                    time_str = ts.strftime("%H:%M")
                    event_type = e.get("type", "unknown")
                    icon = type_icons.get(event_type, "📷")

                    # For smart detections, show what was detected
                    if event_type == "smartDetectZone":
                        detected = e.get("smartDetectTypes", [])
                        detected_str = ", ".join(smart_types.get(d, d) for d in detected)
                        print(f"  {icon} {time_str} - {detected_str}")
                    else:
                        print(f"  {icon} {time_str} - {event_type}")

                if len(cam_events) > 5:
                    print(f"  ... und {len(cam_events) - 5} weitere")
                print()

            return
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
        nvr = api.get_nvr()
        if args.json:
            result = nvr
        else:
            print("🖥️ **NVR Status**\n")
            print(f"   Name: {nvr.get('name', 'Unbekannt')}")
            print(f"   Version: {nvr.get('version', 'Unbekannt')}")
            print(f"   Uptime: {nvr.get('uptime', 0) // 86400} Tage")

            # Storage info
            storage = nvr.get("storageInfo", {})
            used_gb = storage.get("usedSpace", 0) / (1024**3)
            total_gb = storage.get("totalSpace", 0) / (1024**3)
            if total_gb > 0:
                pct = (used_gb / total_gb) * 100
                print(f"   Speicher: {used_gb:.0f} GB / {total_gb:.0f} GB ({pct:.0f}%)")

            # Recording stats
            print(f"   Kameras: {nvr.get('deviceCount', {}).get('cameras', 0)}")
            return

    elif args.command == "sensors":
        sensors = api.get_sensors()
        if args.json:
            result = sensors
        else:
            if not sensors:
                print("Keine Sensoren gefunden.")
                return

            print(f"📡 **Sensoren** ({len(sensors)} Geräte)\n")
            for sensor in sensors:
                name = sensor.get("name", "Unbekannt")
                is_open = sensor.get("isOpened", False)
                battery = sensor.get("batteryStatus", {}).get("percentage", 0)
                state = sensor.get("state", "unknown")

                status_icon = "🟢" if state == "CONNECTED" else "🔴"
                open_icon = "🚪" if is_open else "🔒"

                print(f"{status_icon} **{name}** {open_icon}")
                print(f"   Status: {'Offen' if is_open else 'Geschlossen'}")
                print(f"   Batterie: {battery}%")
                print()
            return

    elif args.command == "lights":
        lights = api.get_lights()
        if args.json:
            result = lights
        else:
            if not lights:
                print("Keine Lichter gefunden.")
                return

            print(f"💡 **Lichter** ({len(lights)} Geräte)\n")
            for light in lights:
                name = light.get("name", "Unbekannt")
                is_on = light.get("isLightOn", False)
                state = light.get("state", "unknown")

                status_icon = "🟢" if state == "CONNECTED" else "🔴"
                light_icon = "💡" if is_on else "🌑"

                print(f"{status_icon} **{name}** {light_icon}")
                print(f"   Status: {'An' if is_on else 'Aus'}")
                print()
            return

    elif args.command == "light-on":
        api.control_light(args.id, True)
        print(f"💡 Licht eingeschaltet")
        return
    elif args.command == "light-off":
        api.control_light(args.id, False)
        print(f"🌑 Licht ausgeschaltet")
        return

    if result:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
