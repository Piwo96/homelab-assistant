#!/usr/bin/env python3
"""
UniFi Protect API Client

Camera, NVR, sensor, light, chime, and PTZ management for UniFi Protect.
Supports official Integration API v1 (API key) and Legacy API (session auth).

Usage:
    python protect_api.py cameras
    python protect_api.py snapshot <camera-id>
    python protect_api.py events --last 24h --camera Einfahrt
    python protect_api.py detections --last 6h --camera Einfahrt
    python protect_api.py chimes
    python protect_api.py ptz-goto <camera> <slot>
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

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


# Lazy import for Legacy API parent class (only needed for events fallback)
_UniFiAPI = None


def _get_unifi_api_class():
    """Lazy-load UniFiAPI from network_api.py (only for Legacy fallback)."""
    global _UniFiAPI
    if _UniFiAPI is None:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "unifi-network" / "scripts"))
        from network_api import UniFiAPI
        _UniFiAPI = UniFiAPI
    return _UniFiAPI


# ---------------------------------------------------------------------------
# Integration API v1 (official, API key auth)
# ---------------------------------------------------------------------------

class ProtectIntegrationAPI:
    """UniFi Protect Integration API v1 client.

    Official REST API with API key authentication.
    Base URL: https://{host}/proxy/protect/integration/v1
    Auth: X-API-Key header
    """

    def __init__(self, host: str = None, api_key: str = None, verify_ssl: bool = None):
        load_env()

        self.host = (host
                     or os.environ.get("PROTECT_HOST")
                     or os.environ.get("UNIFI_HOST", "unifi.local"))
        self.api_key = api_key or os.environ.get("PROTECT_API_KEY")

        verify_env = os.environ.get(
            "PROTECT_VERIFY_SSL",
            os.environ.get("UNIFI_VERIFY_SSL", "false"),
        ).lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"

        if not self.api_key:
            raise RuntimeError("PROTECT_API_KEY required for Protect Integration API v1")

        self.host = self.host.replace("http://", "").replace("https://", "")
        self.base_url = f"https://{self.host}/proxy/protect/integration/v1"

        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        })

    def _request(self, method: str, endpoint: str, data: dict = None,
                 params: dict = None) -> Any:
        """Make Integration API v1 request."""
        url = f"{self.base_url}{endpoint}"
        kwargs: dict[str, Any] = {"timeout": 30}
        if data is not None:
            kwargs["json"] = data
        if params:
            kwargs["params"] = params

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            if response.status_code == 204:
                return {}
            if not response.text:
                return {}
            content_type = response.headers.get("content-type", "")
            if "image" in content_type or "octet-stream" in content_type:
                return response.content
            return response.json()
        except requests.exceptions.HTTPError:
            status = response.status_code
            try:
                err = response.json()
                msg = err.get("error", err.get("message", response.text))
            except Exception:
                msg = response.text
            if status == 401:
                raise RuntimeError(f"Protect Integration API: Invalid API key (401)")
            elif status == 403:
                raise RuntimeError(f"Protect Integration API: Forbidden (403)")
            elif status == 404:
                raise RuntimeError(f"Protect Integration API: Not found (404) - {endpoint}")
            elif status == 429:
                raise RuntimeError("Protect Integration API: Rate limit exceeded (429)")
            else:
                raise RuntimeError(f"Protect Integration API error {status}: {msg}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot connect to Protect Integration API at {self.base_url}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Protect Integration API request error: {e}") from e

    # --- Meta ---

    def get_meta_info(self) -> dict:
        """GET /v1/meta/info - Application version info."""
        return self._request("GET", "/meta/info")

    # --- Cameras ---

    def get_cameras(self) -> list:
        """GET /v1/cameras - List all cameras."""
        result = self._request("GET", "/cameras")
        return result if isinstance(result, list) else []

    def get_camera(self, camera_id: str) -> dict:
        """GET /v1/cameras/{id} - Camera details."""
        return self._request("GET", f"/cameras/{camera_id}")

    def update_camera(self, camera_id: str, settings: dict) -> dict:
        """PATCH /v1/cameras/{id} - Update camera settings."""
        return self._request("PATCH", f"/cameras/{camera_id}", data=settings)

    def get_snapshot(self, camera_id: str, high_quality: bool = True) -> bytes:
        """GET /v1/cameras/{id}/snapshot - Get camera snapshot."""
        params = {}
        if high_quality:
            params["highQuality"] = "true"
        url = f"{self.base_url}/cameras/{camera_id}/snapshot"
        response = self.session.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.content

    # --- PTZ ---

    def ptz_goto(self, camera_id: str, slot: int) -> dict:
        """POST /v1/cameras/{id}/ptz/goto/{slot} - Move PTZ to preset."""
        return self._request("POST", f"/cameras/{camera_id}/ptz/goto/{slot}")

    def ptz_patrol_start(self, camera_id: str, slot: int) -> dict:
        """POST /v1/cameras/{id}/ptz/patrol/start/{slot} - Start PTZ patrol."""
        return self._request("POST", f"/cameras/{camera_id}/ptz/patrol/start/{slot}")

    def ptz_patrol_stop(self, camera_id: str) -> dict:
        """POST /v1/cameras/{id}/ptz/patrol/stop - Stop PTZ patrol."""
        return self._request("POST", f"/cameras/{camera_id}/ptz/patrol/stop")

    # --- RTSPS Streams ---

    def create_rtsps_stream(self, camera_id: str, qualities: list = None) -> dict:
        """POST /v1/cameras/{id}/rtsps-stream - Create RTSPS streams."""
        data = {"qualities": qualities or ["high"]}
        return self._request("POST", f"/cameras/{camera_id}/rtsps-stream", data=data)

    def get_rtsps_streams(self, camera_id: str) -> dict:
        """GET /v1/cameras/{id}/rtsps-stream - Get existing streams."""
        return self._request("GET", f"/cameras/{camera_id}/rtsps-stream")

    def delete_rtsps_stream(self, camera_id: str, qualities: list = None) -> dict:
        """DELETE /v1/cameras/{id}/rtsps-stream - Delete streams."""
        params = {}
        if qualities:
            params["qualities"] = ",".join(qualities)
        return self._request("DELETE", f"/cameras/{camera_id}/rtsps-stream", params=params)

    # --- Talkback (API only) ---

    def create_talkback_session(self, camera_id: str) -> dict:
        """POST /v1/cameras/{id}/talkback-session - Create talkback session."""
        return self._request("POST", f"/cameras/{camera_id}/talkback-session")

    # --- NVR ---

    def get_nvrs(self) -> Any:
        """GET /v1/nvrs - NVR details (returns object, not list)."""
        return self._request("GET", "/nvrs")

    # --- Sensors ---

    def get_sensors(self) -> list:
        """GET /v1/sensors - List all sensors."""
        result = self._request("GET", "/sensors")
        return result if isinstance(result, list) else []

    def get_sensor(self, sensor_id: str) -> dict:
        """GET /v1/sensors/{id} - Sensor details."""
        return self._request("GET", f"/sensors/{sensor_id}")

    def update_sensor(self, sensor_id: str, settings: dict) -> dict:
        """PATCH /v1/sensors/{id} - Update sensor settings."""
        return self._request("PATCH", f"/sensors/{sensor_id}", data=settings)

    # --- Lights ---

    def get_lights(self) -> list:
        """GET /v1/lights - List all lights."""
        result = self._request("GET", "/lights")
        return result if isinstance(result, list) else []

    def get_light(self, light_id: str) -> dict:
        """GET /v1/lights/{id} - Light details."""
        return self._request("GET", f"/lights/{light_id}")

    def control_light(self, light_id: str, on: bool) -> dict:
        """PATCH /v1/lights/{id} - Turn light on/off."""
        return self._request("PATCH", f"/lights/{light_id}",
                             data={"isLightForceEnabled": on})

    def update_light(self, light_id: str, settings: dict) -> dict:
        """PATCH /v1/lights/{id} - Update light settings."""
        return self._request("PATCH", f"/lights/{light_id}", data=settings)

    # --- Chimes ---

    def get_chimes(self) -> list:
        """GET /v1/chimes - List all chimes."""
        result = self._request("GET", "/chimes")
        return result if isinstance(result, list) else []

    def get_chime(self, chime_id: str) -> dict:
        """GET /v1/chimes/{id} - Chime details."""
        return self._request("GET", f"/chimes/{chime_id}")

    def update_chime(self, chime_id: str, settings: dict) -> dict:
        """PATCH /v1/chimes/{id} - Update chime settings."""
        return self._request("PATCH", f"/chimes/{chime_id}", data=settings)

    # --- Viewers ---

    def get_viewers(self) -> list:
        """GET /v1/viewers - List all viewers."""
        result = self._request("GET", "/viewers")
        return result if isinstance(result, list) else []

    def get_viewer(self, viewer_id: str) -> dict:
        """GET /v1/viewers/{id} - Viewer details."""
        return self._request("GET", f"/viewers/{viewer_id}")

    def update_viewer(self, viewer_id: str, settings: dict) -> dict:
        """PATCH /v1/viewers/{id} - Update viewer settings."""
        return self._request("PATCH", f"/viewers/{viewer_id}", data=settings)

    # --- Liveviews ---

    def get_liveviews(self) -> list:
        """GET /v1/liveviews - List all live views."""
        result = self._request("GET", "/liveviews")
        return result if isinstance(result, list) else []

    def get_liveview(self, liveview_id: str) -> dict:
        """GET /v1/liveviews/{id} - Live view details."""
        return self._request("GET", f"/liveviews/{liveview_id}")

    def create_liveview(self, config: dict) -> dict:
        """POST /v1/liveviews - Create a new live view."""
        return self._request("POST", "/liveviews", data=config)

    def update_liveview(self, liveview_id: str, settings: dict) -> dict:
        """PATCH /v1/liveviews/{id} - Update live view configuration."""
        return self._request("PATCH", f"/liveviews/{liveview_id}", data=settings)

    # --- Alarm ---

    def trigger_alarm(self, webhook_id: str) -> dict:
        """POST /v1/alarm-manager/webhook/{id} - Trigger alarm webhook."""
        return self._request("POST", f"/alarm-manager/webhook/{webhook_id}")

    # --- Files (API only) ---

    def get_files(self, file_type: str) -> list:
        """GET /v1/files/{fileType} - List device asset files."""
        result = self._request("GET", f"/files/{file_type}")
        return result if isinstance(result, list) else []


# ---------------------------------------------------------------------------
# Legacy API (internal, session/cookie auth) - for events/detections
# ---------------------------------------------------------------------------

class ProtectLegacyAPI:
    """UniFi Protect Legacy API client (internal API, session auth).

    Used as fallback for events/detections which are not available
    in the official Integration API v1.

    Base URL: https://{host}/proxy/protect/api
    Auth: Cookie-based session + CSRF token (via UniFiAPI parent)
    """

    def __init__(self, host: str = None, username: str = None,
                 password: str = None, verify_ssl: bool = None):
        UniFiAPI = _get_unifi_api_class()
        load_env()

        _host = (host
                 or os.environ.get("PROTECT_HOST")
                 or os.environ.get("UNIFI_HOST", "unifi.local"))
        _username = username or os.environ.get("UNIFI_USERNAME")
        _password = password or os.environ.get("UNIFI_PASSWORD")

        verify_env = os.environ.get(
            "PROTECT_VERIFY_SSL",
            os.environ.get("UNIFI_VERIFY_SSL", "false"),
        ).lower()
        _verify = verify_ssl if verify_ssl is not None else verify_env == "true"

        # Initialize parent UniFiAPI for session management
        self._api = UniFiAPI(
            host=_host, username=_username,
            password=_password, verify_ssl=_verify,
        )
        self.protect_base = f"{self._api.base_url.replace('/proxy/network', '')}/proxy/protect/api"
        self.controller_type = self._api.controller_type

    def _protect_request(self, method: str, endpoint: str, data: dict = None):
        """Make Protect Legacy API request."""
        url = f"{self.protect_base}{endpoint}"
        headers = {}
        if self._api.csrf_token and method in ["POST", "PUT", "DELETE", "PATCH"]:
            headers["X-CSRF-Token"] = self._api.csrf_token

        try:
            response = self._api.session.request(
                method, url, headers=headers, json=data, timeout=30
            )
            response.raise_for_status()
            return response.json() if response.text else {}
        except Exception as e:
            raise RuntimeError(f"Protect Legacy API error: {e}") from e

    def get_cameras(self) -> list:
        """Get all cameras."""
        result = self._protect_request("GET", "/cameras")
        return result if isinstance(result, list) else []

    def get_camera(self, camera_id: str) -> dict:
        """Get camera details."""
        return self._protect_request("GET", f"/cameras/{camera_id}")

    def update_camera(self, camera_id: str, settings: dict) -> dict:
        """Update camera settings."""
        return self._protect_request("PATCH", f"/cameras/{camera_id}", settings)

    def get_snapshot(self, camera_id: str, width: int = None, height: int = None) -> bytes:
        """Get camera snapshot (returns binary data)."""
        params = []
        if width:
            params.append(f"w={width}")
        if height:
            params.append(f"h={height}")
        query = f"?{'&'.join(params)}" if params else ""

        url = f"{self.protect_base}/cameras/{camera_id}/snapshot{query}"
        response = self._api.session.get(url, timeout=10)
        return response.content

    def get_events(self, start: int = None, end: int = None,
                   types: list = None, camera_id: str = None) -> list:
        """Get events, optionally filtered by camera."""
        params = []
        if start:
            params.append(f"start={start}")
        if end:
            params.append(f"end={end}")
        if types:
            params.append(f"types={','.join(types)}")
        query = f"?{'&'.join(params)}" if params else ""

        result = self._protect_request("GET", f"/events{query}")

        if isinstance(result, list):
            events = result
            logger.debug("get_events: API returned list with %d items", len(events))
        elif isinstance(result, dict) and "data" in result and isinstance(result["data"], list):
            events = result["data"]
            logger.debug("get_events: API returned dict with data list (%d items)", len(events))
        else:
            logger.warning(
                "get_events: unexpected response type=%s, keys=%s, preview=%s",
                type(result).__name__,
                list(result.keys()) if isinstance(result, dict) else "N/A",
                str(result)[:300],
            )
            return []

        if camera_id:
            before = len(events)
            events = [e for e in events if isinstance(e, dict) and e.get("camera") == camera_id]
            logger.debug("get_events: filtered by camera %s: %d -> %d", camera_id, before, len(events))

        return events

    def get_nvr(self) -> dict:
        """Get NVR information."""
        return self._protect_request("GET", "/nvr")

    def get_sensors(self) -> list:
        """Get all sensors."""
        result = self._protect_request("GET", "/sensors")
        return result if isinstance(result, list) else []

    def get_lights(self) -> list:
        """Get all lights."""
        result = self._protect_request("GET", "/lights")
        return result if isinstance(result, list) else []

    def control_light(self, light_id: str, on: bool) -> dict:
        """Turn light on/off (legacy payload)."""
        return self._protect_request("PATCH", f"/lights/{light_id}",
                                     {"lightOnSettings": {"isLedForceOn": on}})


# Backward compatibility alias
ProtectAPI = ProtectLegacyAPI


# ---------------------------------------------------------------------------
# Dual API facade (Integration primary, Legacy fallback for events)
# ---------------------------------------------------------------------------

class ProtectDualAPI:
    """Dual-API facade: Integration API v1 (primary) + Legacy (fallback for events).

    Credential routing:
    - PROTECT_API_KEY only                     -> Integration only (no events)
    - UNIFI_USERNAME + UNIFI_PASSWORD only      -> Legacy only (current behavior)
    - Both                                      -> Integration primary, Legacy for events
    """

    def __init__(self, host: str = None, username: str = None, password: str = None,
                 api_key: str = None, verify_ssl: bool = None):
        load_env()

        self.host = (host
                     or os.environ.get("PROTECT_HOST")
                     or os.environ.get("UNIFI_HOST", "unifi.local"))
        _api_key = api_key or os.environ.get("PROTECT_API_KEY")
        _username = username or os.environ.get("UNIFI_USERNAME")
        _password = password or os.environ.get("UNIFI_PASSWORD")

        verify_env = os.environ.get(
            "PROTECT_VERIFY_SSL",
            os.environ.get("UNIFI_VERIFY_SSL", "false"),
        ).lower()
        _verify = verify_ssl if verify_ssl is not None else verify_env == "true"

        self._integration: Optional[ProtectIntegrationAPI] = None
        self._legacy: Optional[ProtectLegacyAPI] = None

        if _api_key:
            self._integration = ProtectIntegrationAPI(
                host=self.host, api_key=_api_key, verify_ssl=_verify)

        if _username and _password:
            self._legacy = ProtectLegacyAPI(
                host=self.host, username=_username,
                password=_password, verify_ssl=_verify)

        if not self._integration and not self._legacy:
            raise RuntimeError(
                "No Protect credentials configured. Set either:\n"
                "  PROTECT_API_KEY (Integration API v1) or\n"
                "  UNIFI_USERNAME + UNIFI_PASSWORD (Legacy API) or\n"
                "  Both (Dual mode - recommended)")

        if self._integration and self._legacy:
            self.api_mode = "dual"
        elif self._integration:
            self.api_mode = "integration"
        else:
            self.api_mode = "legacy"

    @property
    def has_integration(self) -> bool:
        return self._integration is not None

    @property
    def has_legacy(self) -> bool:
        return self._legacy is not None

    def _require_legacy(self, feature: str) -> ProtectLegacyAPI:
        if not self._legacy:
            raise RuntimeError(
                f"'{feature}' requires Legacy API (UNIFI_USERNAME + UNIFI_PASSWORD). "
                f"Events/Detections are not available in the Integration API v1.")
        return self._legacy

    def _require_integration(self, feature: str) -> ProtectIntegrationAPI:
        if not self._integration:
            raise RuntimeError(
                f"'{feature}' requires Integration API v1 (PROTECT_API_KEY)")
        return self._integration

    # --- Dual-routed (prefer Integration) ---

    def get_cameras(self) -> list:
        if self.has_integration:
            return self._integration.get_cameras()
        return self._legacy.get_cameras()

    def get_camera(self, camera_id: str) -> dict:
        if self.has_integration:
            return self._integration.get_camera(camera_id)
        return self._legacy.get_camera(camera_id)

    def update_camera(self, camera_id: str, settings: dict) -> dict:
        if self.has_integration:
            return self._integration.update_camera(camera_id, settings)
        return self._legacy.update_camera(camera_id, settings)

    def get_snapshot(self, camera_id: str, width: int = None, height: int = None,
                     high_quality: bool = True) -> bytes:
        if self.has_integration:
            return self._integration.get_snapshot(camera_id, high_quality)
        return self._legacy.get_snapshot(camera_id, width, height)

    def get_nvr(self) -> dict:
        """Route to nvrs (Integration) or nvr (Legacy)."""
        if self.has_integration:
            result = self._integration.get_nvrs()
            if isinstance(result, list):
                return result[0] if result else {}
            return result if isinstance(result, dict) else {}
        return self._legacy.get_nvr()

    def get_sensors(self) -> list:
        if self.has_integration:
            return self._integration.get_sensors()
        return self._legacy.get_sensors()

    def get_lights(self) -> list:
        if self.has_integration:
            return self._integration.get_lights()
        return self._legacy.get_lights()

    def control_light(self, light_id: str, on: bool) -> dict:
        if self.has_integration:
            return self._integration.control_light(light_id, on)
        return self._legacy.control_light(light_id, on)

    # --- Legacy-only (events not in Integration API) ---

    def get_events(self, start: int = None, end: int = None,
                   types: list = None, camera_id: str = None) -> list:
        return self._require_legacy("events").get_events(start, end, types, camera_id)

    def get_detections(self, start: int = None, end: int = None,
                       camera_id: str = None, detection_type: str = None) -> list:
        """Get smart detections (license plates, faces, vehicles, persons)."""
        legacy = self._require_legacy("detections")
        events = legacy.get_events(start, end, types=["smartDetectZone"], camera_id=camera_id)
        detections = []

        for event in events:
            if not isinstance(event, dict) or "start" not in event:
                continue
            ts = datetime.fromtimestamp(event["start"] / 1000)
            metadata = event.get("metadata", {})
            thumbnails = metadata.get("detectedThumbnails", [])

            for thumb in thumbnails:
                det_type = thumb.get("type")

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

                if det_type == "vehicle" and thumb.get("name"):
                    detection["plate"] = thumb.get("name")
                    attrs = thumb.get("attributes", {})
                    detection["vehicle_type"] = attrs.get("vehicleType", {}).get("val", "unknown")
                    detection["color"] = attrs.get("color", {}).get("val", "unknown")
                    detections.append(detection)
                elif det_type == "face":
                    attrs = thumb.get("attributes", {})
                    detection["has_mask"] = attrs.get("faceMask", {}).get("val") == "mask"
                    detections.append(detection)
                elif det_type == "person" and detection_type in (None, "person"):
                    detections.append(detection)

        return detections

    # --- Integration-only (new features) ---

    def get_meta_info(self) -> dict:
        return self._require_integration("meta").get_meta_info()

    def get_chimes(self) -> list:
        return self._require_integration("chimes").get_chimes()

    def get_chime(self, chime_id: str) -> dict:
        return self._require_integration("chime").get_chime(chime_id)

    def update_chime(self, chime_id: str, settings: dict) -> dict:
        return self._require_integration("chime").update_chime(chime_id, settings)

    def ptz_goto(self, camera_id: str, slot: int) -> dict:
        return self._require_integration("ptz").ptz_goto(camera_id, slot)

    def ptz_patrol_start(self, camera_id: str, slot: int) -> dict:
        return self._require_integration("ptz").ptz_patrol_start(camera_id, slot)

    def ptz_patrol_stop(self, camera_id: str) -> dict:
        return self._require_integration("ptz").ptz_patrol_stop(camera_id)

    def create_rtsps_stream(self, camera_id: str, qualities: list = None) -> dict:
        return self._require_integration("rtsps").create_rtsps_stream(camera_id, qualities)

    def get_rtsps_streams(self, camera_id: str) -> dict:
        return self._require_integration("rtsps").get_rtsps_streams(camera_id)

    def delete_rtsps_stream(self, camera_id: str, qualities: list = None) -> dict:
        return self._require_integration("rtsps").delete_rtsps_stream(camera_id, qualities)

    def get_viewers(self) -> list:
        return self._require_integration("viewers").get_viewers()

    def get_viewer(self, viewer_id: str) -> dict:
        return self._require_integration("viewer").get_viewer(viewer_id)

    def get_liveviews(self) -> list:
        return self._require_integration("liveviews").get_liveviews()

    def get_liveview(self, liveview_id: str) -> dict:
        return self._require_integration("liveview").get_liveview(liveview_id)

    def trigger_alarm(self, webhook_id: str) -> dict:
        return self._require_integration("alarm").trigger_alarm(webhook_id)

    def get_sensor(self, sensor_id: str) -> dict:
        return self._require_integration("sensor").get_sensor(sensor_id)

    def update_sensor(self, sensor_id: str, settings: dict) -> dict:
        return self._require_integration("sensor").update_sensor(sensor_id, settings)

    def get_light(self, light_id: str) -> dict:
        return self._require_integration("light").get_light(light_id)

    def update_light(self, light_id: str, settings: dict) -> dict:
        return self._require_integration("light").update_light(light_id, settings)

    # --- Fuzzy camera name matching ---

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a camera name for fuzzy comparison."""
        name = name.lower()
        name = re.sub(r"[_\-'`\u00b4\u2019]", " ", name)
        return " ".join(name.split())

    def resolve_camera_id(self, camera_ref: str) -> Optional[str]:
        """Resolve camera name to ID with fuzzy matching.

        Matching priority:
        1. Exact ID match
        2. Exact name match (case-insensitive)
        3. Normalized name match (ignoring underscores, hyphens, apostrophes)
        4. Substring match (camera_ref contained in name or vice versa)
        5. difflib close match (typo tolerance)
        """
        from difflib import get_close_matches

        cameras = self.get_cameras()
        ref_normalized = self._normalize_name(camera_ref)

        id_map = {}
        exact_map = {}
        norm_map = {}
        name_list = []

        for cam in cameras:
            cam_id = cam.get("id", "")
            cam_name = cam.get("name", "")

            id_map[cam_id] = cam_id
            exact_map[cam_name.lower()] = cam_id
            norm = self._normalize_name(cam_name)
            norm_map[norm] = cam_id
            name_list.append(norm)

        # 1. Exact ID
        if camera_ref in id_map:
            return camera_ref

        # 2. Exact name (case-insensitive)
        if camera_ref.lower() in exact_map:
            return exact_map[camera_ref.lower()]

        # 3. Normalized name
        if ref_normalized in norm_map:
            return norm_map[ref_normalized]

        # 4. Substring match (either direction)
        for norm, cam_id in norm_map.items():
            if ref_normalized in norm or norm in ref_normalized:
                return cam_id

        # 5. difflib fuzzy match
        close = get_close_matches(ref_normalized, name_list, n=1, cutoff=0.6)
        if close:
            return norm_map[close[0]]

        available = [cam.get("name", "Unnamed") for cam in cameras]
        print(f"Camera not found: {camera_ref}", file=sys.stderr)
        print(f"Available cameras: {', '.join(available)}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Human-readable formatting (used by agent pipeline)
# ---------------------------------------------------------------------------

_TYPE_ICONS = {
    "motion": "🏃",
    "smartDetectZone": "🔍",
    "smartAudioDetect": "🔊",
    "ring": "🔔",
    "sensorMotion": "📡",
    "sensorContact": "🚪",
    "access": "🔑",
}

_SMART_TYPES = {
    "person": "Person",
    "vehicle": "Fahrzeug",
    "animal": "Tier",
    "package": "Paket",
    "licensePlate": "Kennzeichen",
    "face": "Gesicht",
    "alrmSpeak": "Sprechen",
    "alrmSmoke": "Rauchmelder",
    "alrmCmonx": "CO-Melder",
    "alrmBark": "Bellen",
    "alrmCry": "Weinen",
    "alrmSiren": "Sirene",
    "alrmGlass": "Glasbruch",
    "alrmBabyCry": "Baby weint",
}


def format_agent_output(action: str, data: Any) -> Optional[str]:
    """Format raw data into human-readable text for Telegram/agent output.

    Called by skill_executor when available, producing compact text
    instead of raw JSON that would overwhelm the LLM formatter.

    Args:
        action: The action that produced the data (e.g. "events", "cameras")
        data: Raw Python data returned by execute()

    Returns:
        Formatted string, or None if no formatter available (falls back to JSON)
    """
    if action == "events":
        return _format_events(data)
    elif action == "detections":
        return _format_detections(data)
    elif action == "cameras":
        return _format_cameras(data)
    elif action == "sensors":
        return _format_sensors(data)
    elif action == "lights":
        return _format_lights(data)
    elif action == "nvr":
        return _format_nvr(data)
    return None


def _format_events(events: list) -> str:
    """Format events list into human-readable text."""
    if not events:
        return "Keine Ereignisse gefunden."

    # Resolve camera names
    try:
        api = ProtectDualAPI()
        cameras = {c["id"]: c.get("name", "Unbekannt") for c in api.get_cameras()}
    except Exception:
        cameras = {}

    # Group by camera (or "System" for non-camera events)
    by_camera: dict[str, list] = {}
    for e in events:
        cam_id = e.get("camera")
        if cam_id:
            cam_name = cameras.get(cam_id, "Unbekannt")
        else:
            cam_name = "System"
        by_camera.setdefault(cam_name, []).append(e)

    lines = [f"📹 Kamera-Ereignisse ({len(events)} Einträge)\n"]

    for cam_name, cam_events in by_camera.items():
        lines.append(f"{cam_name} ({len(cam_events)} Ereignisse)")

        for e in cam_events[:10]:
            ts = datetime.fromtimestamp(e["start"] / 1000)
            time_str = ts.strftime("%d.%m. %H:%M")
            event_type = e.get("type", "unknown")
            icon = _TYPE_ICONS.get(event_type, "📷")

            if event_type in ("smartDetectZone", "smartAudioDetect"):
                detected = e.get("smartDetectTypes", [])
                detected_str = ", ".join(_SMART_TYPES.get(d, d) for d in detected)
                lines.append(f"  {icon} {time_str} - {detected_str}")
            elif event_type == "access":
                desc = e.get("description", {})
                msg_raw = desc.get("messageRaw", "")
                # Strip template keys like {userLink}
                msg = re.sub(r"\{(\w+)\}", lambda m: _resolve_msg_key(m, e), msg_raw) if msg_raw else "Zugriff"
                lines.append(f"  {icon} {time_str} - {msg}")
            else:
                lines.append(f"  {icon} {time_str} - {event_type}")

        if len(cam_events) > 10:
            lines.append(f"  ... und {len(cam_events) - 10} weitere")
        lines.append("")

    return "\n".join(lines).strip()


def _resolve_msg_key(match: re.Match, event: dict) -> str:
    """Resolve template keys in event messageRaw (e.g. {userLink})."""
    key = match.group(1)
    msg_keys = event.get("description", {}).get("messageKeys", [])
    if isinstance(msg_keys, list):
        for mk in msg_keys:
            if mk.get("key") == key:
                return mk.get("text", key)
    return key


def _format_detections(detections: list) -> str:
    """Format detections list into human-readable text."""
    if not detections:
        return "Keine Erkennungen gefunden."

    plates = [d for d in detections if d.get("plate")]
    faces = [d for d in detections if d.get("type") == "face"]
    persons = [d for d in detections if d.get("type") == "person" and "plate" not in d]

    lines = [f"🔍 Erkennungen ({len(detections)} Einträge)\n"]

    if plates:
        lines.append(f"Kennzeichen ({len(plates)})")
        for d in plates[:10]:
            lines.append(f"  🚗 {d.get('time', '?')} - {d.get('plate', '?')} ({d.get('vehicle_type', '?')}, {d.get('color', '?')}, {d.get('confidence', '?')}%)")
        if len(plates) > 10:
            lines.append(f"  ... und {len(plates) - 10} weitere")
        lines.append("")

    if faces:
        lines.append(f"Gesichter ({len(faces)})")
        for d in faces[:10]:
            mask = "mit Maske" if d.get("has_mask") else ""
            lines.append(f"  👤 {d.get('time', '?')} - {d.get('confidence', '?')}% {mask}")
        if len(faces) > 10:
            lines.append(f"  ... und {len(faces) - 10} weitere")
        lines.append("")

    if persons:
        lines.append(f"Personen: {len(persons)} Erkennungen")

    return "\n".join(lines).strip()


def _format_cameras(cameras: list) -> str:
    """Format cameras list into human-readable text."""
    if not cameras:
        return "Keine Kameras gefunden."

    lines = [f"📹 Kameras ({len(cameras)} Geräte)\n"]
    for cam in cameras:
        name = cam.get("name", "Unbekannt")
        state = cam.get("state", "unknown")
        icon = "🟢" if state == "CONNECTED" else "🔴"
        model = cam.get("modelKey", cam.get("type", "Unbekannt"))

        smart = cam.get("featureFlags", {}).get("smartDetectTypes", [])
        smart_str = f" | Smart: {', '.join(smart)}" if smart else ""
        lines.append(f"{icon} {name} ({model}{smart_str})")

    return "\n".join(lines).strip()


def _format_sensors(sensors: list) -> str:
    """Format sensors list into human-readable text."""
    if not sensors:
        return "Keine Sensoren gefunden."

    lines = [f"📡 Sensoren ({len(sensors)})\n"]
    for s in sensors:
        name = s.get("name", "Unbekannt")
        state = s.get("state", "unknown")
        icon = "🟢" if state == "CONNECTED" else "🔴"
        stats = s.get("stats", {})
        temp = stats.get("temperature", {}).get("value")
        humidity = stats.get("humidity", {}).get("value")

        info = []
        if temp is not None:
            info.append(f"{temp}°C")
        if humidity is not None:
            info.append(f"{humidity}%")
        info_str = f" ({', '.join(info)})" if info else ""
        lines.append(f"{icon} {name}{info_str}")

    return "\n".join(lines).strip()


def _format_lights(lights: list) -> str:
    """Format lights list into human-readable text."""
    if not lights:
        return "Keine Lichter gefunden."

    lines = [f"💡 Lichter ({len(lights)})\n"]
    for light in lights:
        name = light.get("name", "Unbekannt")
        is_on = light.get("isLightOn", False)
        icon = "💡" if is_on else "⚫"
        state = light.get("state", "unknown")
        online = "🟢" if state == "CONNECTED" else "🔴"
        lines.append(f"{online} {icon} {name}")

    return "\n".join(lines).strip()


def _format_nvr(nvr: dict) -> str:
    """Format NVR info into human-readable text."""
    lines = ["🖥️ NVR Status\n"]
    lines.append(f"  Name: {nvr.get('name', 'Unbekannt')}")

    version = nvr.get("version", nvr.get("applicationVersion", "Unbekannt"))
    if version != "Unbekannt":
        lines.append(f"  Version: {version}")

    uptime_ms = nvr.get("uptime", 0)
    if uptime_ms:
        days = uptime_ms // 86_400_000
        hours = (uptime_ms % 86_400_000) // 3_600_000
        lines.append(f"  Uptime: {days} Tage, {hours} Stunden")

    storage = nvr.get("storageInfo", {})
    used_gb = storage.get("usedSpace", 0) / (1024**3)
    total_gb = storage.get("totalSpace", 0) / (1024**3)
    if total_gb > 0:
        pct = (used_gb / total_gb) * 100
        lines.append(f"  Speicher: {used_gb:.0f} GB / {total_gb:.0f} GB ({pct:.0f}%)")

    device_count = nvr.get("deviceCount", {})
    if isinstance(device_count, dict) and device_count.get("cameras"):
        lines.append(f"  Kameras: {device_count['cameras']}")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Programmatic API (execute function)
# ---------------------------------------------------------------------------

def execute(action: str, args: dict) -> Any:
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
    api = ProtectDualAPI()

    # --- Camera commands ---
    if action == "cameras":
        return api.get_cameras()
    elif action == "camera":
        return api.get_camera(args["id"])
    elif action == "snapshot":
        data = api.get_snapshot(args["id"], args.get("width"), args.get("height"),
                                high_quality=args.get("high_quality", True))
        output = args.get("output") or f"snapshot_{args['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        with open(output, "wb") as f:
            f.write(data)
        return {"file": output, "size": len(data)}

    # --- Event commands (Legacy API) ---
    elif action == "events":
        hours = _parse_duration(str(args.get("last", "24h")))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        logger.info("events: querying %dh window (start=%d, end=%d)", hours, start, end)
        types = args.get("types", "").split(",") if args.get("types") else None
        camera_id = None
        if args.get("camera"):
            camera_id = api.resolve_camera_id(args["camera"])
            if not camera_id:
                raise ValueError(f"Camera not found: {args['camera']}")
        events = api.get_events(start, end, types, camera_id)
        limit = int(args["limit"]) if args.get("limit") else 20
        logger.info("events: found %d events (returning max %d)", len(events), limit)
        return events[:limit]
    elif action == "detections":
        hours = _parse_duration(str(args.get("last", "6h")))
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        camera_id = None
        if args.get("camera"):
            camera_id = api.resolve_camera_id(args["camera"])
            if not camera_id:
                raise ValueError(f"Camera not found: {args['camera']}")
        detections = api.get_detections(start, end, camera_id, args.get("type"))
        limit = int(args["limit"]) if args.get("limit") else 20
        return detections[:limit]

    # --- Device commands ---
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

    # --- New Integration API commands ---
    elif action == "meta":
        return api.get_meta_info()
    elif action == "chimes":
        return api.get_chimes()
    elif action == "chime":
        return api.get_chime(args["id"])
    elif action == "ptz-goto":
        camera_id = api.resolve_camera_id(args["camera"]) if not args.get("camera", "").startswith("6") else args["camera"]
        if args.get("camera") and not camera_id:
            camera_id = api.resolve_camera_id(args["camera"])
        if not camera_id:
            raise ValueError(f"Camera not found: {args.get('camera')}")
        return api.ptz_goto(camera_id, int(args["slot"]))
    elif action == "ptz-patrol-start":
        camera_id = api.resolve_camera_id(args["camera"])
        if not camera_id:
            raise ValueError(f"Camera not found: {args['camera']}")
        return api.ptz_patrol_start(camera_id, int(args["slot"]))
    elif action == "ptz-patrol-stop":
        camera_id = api.resolve_camera_id(args["camera"])
        if not camera_id:
            raise ValueError(f"Camera not found: {args['camera']}")
        return api.ptz_patrol_stop(camera_id)
    elif action == "rtsps-stream":
        return api.create_rtsps_stream(args["id"])
    elif action == "rtsps-streams":
        return api.get_rtsps_streams(args["id"])
    elif action == "rtsps-stream-delete":
        return api.delete_rtsps_stream(args["id"])
    elif action == "viewers":
        return api.get_viewers()
    elif action == "liveviews":
        return api.get_liveviews()
    elif action == "alarm":
        return api.trigger_alarm(args["id"])
    elif action == "detect":
        return {"api_mode": api.api_mode,
                "has_integration": api.has_integration,
                "has_legacy": api.has_legacy}
    else:
        raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# CLI (main function)
# ---------------------------------------------------------------------------

def _parse_duration(duration_str: str) -> int:
    """Parse duration string like '24h', '7d', '30m' into hours."""
    s = duration_str.strip().lower()
    if s.endswith("d"):
        return int(s[:-1]) * 24
    elif s.endswith("m"):
        return max(1, int(s[:-1]) // 60)
    else:
        return int(s.rstrip("h"))


def main():
    # Shared parent parser so --json works before or after subcommand
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", action="store_true", help="Output as JSON")

    parser = argparse.ArgumentParser(description="UniFi Protect API Client", parents=[json_parent])

    subparsers = parser.add_subparsers(dest="command", help="Commands")
    _p = lambda *a, **kw: subparsers.add_parser(*a, parents=[json_parent], **kw)

    # --- Info ---
    _p("detect", help="Show API mode and connection status")
    _p("meta", help="Application version info")

    # --- Cameras ---
    _p("cameras", help="List all cameras")

    camera = _p("camera", help="Get camera details")
    camera.add_argument("id", help="Camera ID")

    snapshot = _p("snapshot", help="Get camera snapshot")
    snapshot.add_argument("id", help="Camera ID")
    snapshot.add_argument("--output", "-o", help="Output file (default: snapshot.jpg)")
    snapshot.add_argument("--width", type=int, help="Width (legacy API)")
    snapshot.add_argument("--height", type=int, help="Height (legacy API)")

    # --- Events ---
    events = _p("events", help="List events (requires Legacy API)")
    events.add_argument("--last", help="Last N hours (e.g., 24h, 1h)", default="24h")
    events.add_argument("--types", help="Event types (comma-separated: motion,ring)")
    events.add_argument("--camera", help="Filter by camera name or ID")
    events.add_argument("--limit", type=int, help="Limit number of events returned")

    # --- Smart Detections ---
    detections = _p("detections", help="Smart detections (requires Legacy API)")
    detections.add_argument("--last", help="Last N hours (e.g., 24h, 1h)", default="6h")
    detections.add_argument("--camera", help="Filter by camera name or ID")
    detections.add_argument("--type", choices=["plate", "face", "vehicle", "person"],
                            help="Filter by detection type")

    # --- Devices ---
    _p("nvr", help="NVR information")
    _p("sensors", help="List sensors")
    _p("lights", help="List lights")

    light_on = _p("light-on", help="Turn light on")
    light_on.add_argument("id", help="Light ID")

    light_off = _p("light-off", help="Turn light off")
    light_off.add_argument("id", help="Light ID")

    # --- Chimes ---
    _p("chimes", help="List chimes/doorbells")

    chime = _p("chime", help="Get chime details")
    chime.add_argument("id", help="Chime ID")

    # --- PTZ ---
    ptz_goto = _p("ptz-goto", help="Move PTZ camera to preset")
    ptz_goto.add_argument("camera", help="Camera name or ID")
    ptz_goto.add_argument("slot", type=int, help="Preset slot (0-4)")

    ptz_start = _p("ptz-patrol-start", help="Start PTZ patrol")
    ptz_start.add_argument("camera", help="Camera name or ID")
    ptz_start.add_argument("slot", type=int, help="Patrol slot (0-4)")

    ptz_stop = _p("ptz-patrol-stop", help="Stop PTZ patrol")
    ptz_stop.add_argument("camera", help="Camera name or ID")

    # --- RTSPS Streams ---
    rtsps = _p("rtsps-stream", help="Create RTSPS stream")
    rtsps.add_argument("id", help="Camera ID")

    rtsps_list = _p("rtsps-streams", help="Get RTSPS streams")
    rtsps_list.add_argument("id", help="Camera ID")

    rtsps_del = _p("rtsps-stream-delete", help="Delete RTSPS stream")
    rtsps_del.add_argument("id", help="Camera ID")

    # --- Viewers & Liveviews ---
    _p("viewers", help="List viewers")
    _p("liveviews", help="List live views")

    # --- Alarm ---
    alarm = _p("alarm", help="Trigger alarm webhook")
    alarm.add_argument("id", help="Webhook ID")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = ProtectDualAPI()
    mode_label = {
        "dual": "Dual (Integration + Legacy)",
        "integration": "Integration API v1",
        "legacy": "Legacy API",
    }
    print(f"Connected to Protect ({mode_label.get(api.api_mode, api.api_mode)})", file=sys.stderr)

    result = None

    # --- detect ---
    if args.command == "detect":
        print(f"API Mode: {api.api_mode}")
        print(f"Integration API: {'Ja' if api.has_integration else 'Nein'}")
        print(f"Legacy API: {'Ja' if api.has_legacy else 'Nein'}")
        return

    # --- meta ---
    elif args.command == "meta":
        info = api.get_meta_info()
        if args.json:
            result = info
        else:
            print("ℹ️  **Protect Info**\n")
            print(f"   Version: {info.get('applicationVersion', 'Unbekannt')}")
            return

    # --- cameras ---
    elif args.command == "cameras":
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
                is_connected = state == "CONNECTED"
                status_icon = "🟢" if is_connected else "🔴"

                print(f"{status_icon} **{name}**")
                print(f"   ID: {cam.get('id', '?')}")
                print(f"   Modell: {cam.get('modelKey', cam.get('type', 'Unbekannt'))}")

                # Show smart detect types if available
                features = cam.get("featureFlags", {})
                smart_types = features.get("smartDetectTypes", [])
                if smart_types:
                    print(f"   Smart-Erkennung: {', '.join(smart_types)}")
                print()
            return

    # --- camera ---
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
            print(f"   Modell: {cam.get('modelKey', cam.get('type', 'Unbekannt'))}")
            print(f"   Status: {state}")
            print(f"   MAC: {cam.get('mac', 'Unbekannt')}")
            print(f"   Mikrofon: {'An' if cam.get('isMicEnabled') else 'Aus'}")
            print(f"   Video-Modus: {cam.get('videoMode', 'default')}")
            print(f"   HDR: {cam.get('hdrType', 'unbekannt')}")

            # Smart detection settings
            smart = cam.get("smartDetectSettings", {})
            obj_types = smart.get("objectTypes", [])
            audio_types = smart.get("audioTypes", [])
            if obj_types:
                print(f"   Smart-Objekte: {', '.join(obj_types)}")
            if audio_types:
                print(f"   Smart-Audio: {', '.join(audio_types)}")

            # Feature flags
            features = cam.get("featureFlags", {})
            if features:
                caps = []
                if features.get("hasMic"):
                    caps.append("Mikrofon")
                if features.get("hasSpeaker"):
                    caps.append("Lautsprecher")
                if features.get("hasHdr"):
                    caps.append("HDR")
                if features.get("hasLedStatus"):
                    caps.append("Status-LED")
                if caps:
                    print(f"   Features: {', '.join(caps)}")
            return

    # --- snapshot ---
    elif args.command == "snapshot":
        data = api.get_snapshot(args.id, args.width, args.height)
        output = args.output or f"snapshot_{args.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        with open(output, "wb") as f:
            f.write(data)
        print(f"Snapshot saved to {output}")
        return

    # --- events ---
    elif args.command == "events":
        hours = _parse_duration(args.last)
        end = int(datetime.now().timestamp() * 1000)
        start = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)
        types = args.types.split(",") if args.types else None
        camera_id = api.resolve_camera_id(args.camera) if args.camera else None
        if args.camera and not camera_id:
            print(f"Camera not found: {args.camera}", file=sys.stderr)
            sys.exit(1)
        events = api.get_events(start, end, types, camera_id)
        if args.limit and args.limit > 0:
            events = events[:args.limit]

        if args.json:
            result = events
        else:
            if not events:
                print(f"Keine Ereignisse in den letzten {hours} Stunden.")
                return

            cameras = {c["id"]: c.get("name", "Unknown") for c in api.get_cameras()}

            type_icons = {
                "motion": "🏃",
                "smartDetectZone": "🔍",
                "ring": "🔔",
                "sensorMotion": "📡",
                "sensorContact": "🚪",
            }

            smart_types = {
                "person": "Person",
                "vehicle": "Fahrzeug",
                "animal": "Tier",
                "package": "Paket",
                "licensePlate": "Kennzeichen",
                "face": "Gesicht",
            }

            duration_label = f"{hours // 24}d" if hours >= 24 and hours % 24 == 0 else f"{hours}h"
            print(f"📹 **Kamera-Ereignisse** (letzte {duration_label})\n")

            by_camera = {}
            for e in events:
                cam_id = e.get("camera")
                cam_name = cameras.get(cam_id, "Unbekannt")
                if cam_name not in by_camera:
                    by_camera[cam_name] = []
                by_camera[cam_name].append(e)

            for cam_name, cam_events in by_camera.items():
                print(f"**{cam_name}** ({len(cam_events)} Ereignisse)")

                for e in cam_events[:5]:
                    ts = datetime.fromtimestamp(e["start"] / 1000)
                    time_str = ts.strftime("%H:%M")
                    event_type = e.get("type", "unknown")
                    icon = type_icons.get(event_type, "📷")

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

    # --- detections ---
    elif args.command == "detections":
        hours = _parse_duration(args.last)
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
            if not detections:
                print("No detections found.")
                return

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

    # --- nvr ---
    elif args.command == "nvr":
        nvr = api.get_nvr()
        if args.json:
            result = nvr
        else:
            print("🖥️  **NVR Status**\n")
            print(f"   Name: {nvr.get('name', 'Unbekannt')}")
            # Integration API returns applicationVersion via meta, legacy returns version
            version = nvr.get("version", nvr.get("applicationVersion", "Unbekannt"))
            if version != "Unbekannt":
                print(f"   Version: {version}")

            # Legacy API has more detail
            uptime_ms = nvr.get("uptime", 0)
            if uptime_ms:
                days = uptime_ms // 86_400_000
                hours = (uptime_ms % 86_400_000) // 3_600_000
                print(f"   Uptime: {days} Tage, {hours} Stunden")

            storage = nvr.get("storageInfo", {})
            used_gb = storage.get("usedSpace", 0) / (1024**3)
            total_gb = storage.get("totalSpace", 0) / (1024**3)
            if total_gb > 0:
                pct = (used_gb / total_gb) * 100
                print(f"   Speicher: {used_gb:.0f} GB / {total_gb:.0f} GB ({pct:.0f}%)")

            device_count = nvr.get("deviceCount", {})
            if isinstance(device_count, dict) and device_count.get("cameras"):
                print(f"   Kameras: {device_count['cameras']}")

            # Doorbell settings (Integration API)
            doorbell = nvr.get("doorbellSettings", {})
            if doorbell.get("defaultMessageText"):
                print(f"   Klingel-Text: {doorbell['defaultMessageText']}")
            return

    # --- sensors ---
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
                state = sensor.get("state", "unknown")
                status_icon = "🟢" if state == "CONNECTED" else "🔴"

                print(f"{status_icon} **{name}**")
                print(f"   ID: {sensor.get('id', '?')}")
                print(f"   Typ: {sensor.get('mountType', 'Unbekannt')}")

                # Open/closed status
                is_open = sensor.get("isOpened")
                if is_open is not None:
                    print(f"   Status: {'Offen' if is_open else 'Geschlossen'}")

                # Battery
                battery = sensor.get("batteryStatus", {})
                pct = battery.get("percentage")
                if pct is not None:
                    print(f"   Batterie: {pct}%")
                elif battery.get("isLow"):
                    print(f"   Batterie: Niedrig!")

                # Stats (Integration API provides richer data)
                stats = sensor.get("stats", {})
                temp = stats.get("temperature", {})
                if temp.get("value") is not None:
                    print(f"   Temperatur: {temp['value']}°C")
                humidity = stats.get("humidity", {})
                if humidity.get("value") is not None:
                    print(f"   Feuchtigkeit: {humidity['value']}%")
                light = stats.get("light", {})
                if light.get("value") is not None:
                    print(f"   Licht: {light['value']} lux")

                # Motion
                if sensor.get("isMotionDetected"):
                    print(f"   Bewegung: Erkannt!")

                # Leak
                if sensor.get("leakDetectedAt"):
                    print(f"   Leck: Erkannt!")

                # Alarm
                if sensor.get("alarmTriggeredAt"):
                    print(f"   Alarm: Ausgelöst!")

                # Tampering
                if sensor.get("tamperingDetectedAt"):
                    print(f"   Manipulation: Erkannt!")

                print()
            return

    # --- lights ---
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
                print(f"   ID: {light.get('id', '?')}")
                print(f"   Status: {'An' if is_on else 'Aus'}")

                # Integration API provides more detail
                if light.get("isDark") is not None:
                    print(f"   Dunkel: {'Ja' if light['isDark'] else 'Nein'}")
                if light.get("isPirMotionDetected"):
                    print(f"   Bewegung: Erkannt!")
                if light.get("isLightForceEnabled"):
                    print(f"   Manuell aktiviert: Ja")

                # Mode settings
                mode = light.get("lightModeSettings", {})
                if mode.get("mode"):
                    print(f"   Modus: {mode['mode']}")

                print()
            return

    # --- light-on ---
    elif args.command == "light-on":
        api.control_light(args.id, True)
        print(f"💡 Licht eingeschaltet")
        return

    # --- light-off ---
    elif args.command == "light-off":
        api.control_light(args.id, False)
        print(f"🌑 Licht ausgeschaltet")
        return

    # --- chimes ---
    elif args.command == "chimes":
        chimes = api.get_chimes()
        if args.json:
            result = chimes
        else:
            if not chimes:
                print("Keine Klingeln gefunden.")
                return

            print(f"🔔 **Klingeln** ({len(chimes)} Geräte)\n")
            for chime in chimes:
                name = chime.get("name", "Unbekannt")
                state = chime.get("state", "unknown")
                status_icon = "🟢" if state == "CONNECTED" else "🔴"

                print(f"{status_icon} **{name}**")
                print(f"   ID: {chime.get('id', '?')}")
                print(f"   MAC: {chime.get('mac', '?')}")

                camera_ids = chime.get("cameraIds", [])
                if camera_ids:
                    print(f"   Kameras: {len(camera_ids)} verknüpft")

                ring_settings = chime.get("ringSettings", [])
                if ring_settings:
                    for rs in ring_settings:
                        vol = rs.get("volume", "?")
                        repeat = rs.get("repeatTimes", "?")
                        print(f"   Lautstärke: {vol}, Wiederholungen: {repeat}")
                print()
            return

    # --- chime ---
    elif args.command == "chime":
        chime = api.get_chime(args.id)
        if args.json:
            result = chime
        else:
            print(json.dumps(chime, indent=2))
            return

    # --- PTZ ---
    elif args.command == "ptz-goto":
        camera_id = api.resolve_camera_id(args.camera)
        if not camera_id:
            sys.exit(1)
        api.ptz_goto(camera_id, args.slot)
        print(f"🎯 PTZ-Kamera zu Preset {args.slot} bewegt")
        return

    elif args.command == "ptz-patrol-start":
        camera_id = api.resolve_camera_id(args.camera)
        if not camera_id:
            sys.exit(1)
        api.ptz_patrol_start(camera_id, args.slot)
        print(f"🔄 PTZ-Patrol {args.slot} gestartet")
        return

    elif args.command == "ptz-patrol-stop":
        camera_id = api.resolve_camera_id(args.camera)
        if not camera_id:
            sys.exit(1)
        api.ptz_patrol_stop(camera_id)
        print(f"⏹️  PTZ-Patrol gestoppt")
        return

    # --- RTSPS Streams ---
    elif args.command == "rtsps-stream":
        streams = api.create_rtsps_stream(args.id)
        if args.json:
            result = streams
        else:
            print("🎥 **RTSPS Streams erstellt**\n")
            for quality, url in streams.items():
                if url:
                    print(f"   {quality}: {url}")
            return

    elif args.command == "rtsps-streams":
        streams = api.get_rtsps_streams(args.id)
        if args.json:
            result = streams
        else:
            print("🎥 **RTSPS Streams**\n")
            for quality, url in streams.items():
                status = url if url else "nicht aktiv"
                print(f"   {quality}: {status}")
            return

    elif args.command == "rtsps-stream-delete":
        api.delete_rtsps_stream(args.id)
        print(f"🗑️  RTSPS Stream gelöscht")
        return

    # --- Viewers ---
    elif args.command == "viewers":
        viewers = api.get_viewers()
        if args.json:
            result = viewers
        else:
            if not viewers:
                print("Keine Viewer gefunden.")
                return

            print(f"📺 **Viewer** ({len(viewers)} Geräte)\n")
            for viewer in viewers:
                name = viewer.get("name", "Unbekannt")
                state = viewer.get("state", "unknown")
                status_icon = "🟢" if state == "CONNECTED" else "🔴"

                print(f"{status_icon} **{name}**")
                print(f"   ID: {viewer.get('id', '?')}")
                print(f"   Modell: {viewer.get('modelKey', '?')}")
                print(f"   Stream-Limit: {viewer.get('streamLimit', '?')}")
                print()
            return

    # --- Liveviews ---
    elif args.command == "liveviews":
        liveviews = api.get_liveviews()
        if args.json:
            result = liveviews
        else:
            if not liveviews:
                print("Keine Live-Views gefunden.")
                return

            print(f"📺 **Live-Views** ({len(liveviews)} Views)\n")
            for lv in liveviews:
                name = lv.get("name", "Unbekannt")
                is_default = lv.get("isDefault", False)
                is_global = lv.get("isGlobal", False)
                layout = lv.get("layout", 0)

                default_tag = " (Standard)" if is_default else ""
                global_tag = " [Global]" if is_global else ""

                print(f"   **{name}**{default_tag}{global_tag}")
                print(f"   ID: {lv.get('id', '?')}")
                print(f"   Layout: {layout} Slots")

                slots = lv.get("slots", [])
                for i, slot in enumerate(slots):
                    cam_count = len(slot.get("cameras", []))
                    cycle = slot.get("cycleMode", "none")
                    print(f"   Slot {i}: {cam_count} Kamera(s), Zyklus: {cycle}")
                print()
            return

    # --- Alarm ---
    elif args.command == "alarm":
        api.trigger_alarm(args.id)
        print(f"🚨 Alarm ausgelöst (Webhook: {args.id})")
        return

    if result:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
