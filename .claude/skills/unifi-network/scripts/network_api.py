#!/usr/bin/env python3
"""
UniFi Controller API Client

CLI tool for managing UniFi networks, clients, and devices.
Supports: Standard Controllers, UDM, UCG, Cloud Key.

Usage:
    python unifi_api.py clients
    python unifi_api.py kick aa:bb:cc:dd:ee:ff
    python unifi_api.py devices
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timedelta

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


class UniFiAPI:
    """UniFi Controller API client with auto-detection for UDM/UCG."""

    def __init__(
        self,
        host: str = None,
        username: str = None,
        password: str = None,
        site: str = "default",
        verify_ssl: bool = None,
    ):
        load_env()

        self.host = host or os.environ.get("UNIFI_HOST", "unifi.local")
        self.username = username or os.environ.get("UNIFI_USERNAME")
        self.password = password or os.environ.get("UNIFI_PASSWORD")
        self.site = site or os.environ.get("UNIFI_SITE", "default")

        verify_env = os.environ.get("UNIFI_VERIFY_SSL", "false").lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"

        if not self.username or not self.password:
            raise RuntimeError("UNIFI_USERNAME and UNIFI_PASSWORD required")

        # Remove http/https prefix
        self.host = self.host.replace("http://", "").replace("https://", "")

        # Detect controller type and set base URL
        self.controller_type, self.base_url = self._detect_controller()
        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self.csrf_token: Optional[str] = None
        self.session_expires: Optional[datetime] = None

        # Session cache file
        self.cache_dir = Path.home() / ".cache" / "homelab"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.cache_dir / f"unifi_session_{self.host}.pkl"

        # Try to load cached session, otherwise login
        if not self._load_session():
            self._login()
            self._save_session()

    def _detect_controller(self) -> tuple[str, str]:
        """Detect controller type (Standard, UDM/UCG) and return base URL."""
        # Try UCG/UDM first (port 443, /proxy/network)
        try:
            response = requests.get(
                f"https://{self.host}/proxy/network/api/self",
                timeout=3,
                verify=self.verify_ssl,
            )
            if response.status_code in [200, 401]:
                return ("UCG/UDM", f"https://{self.host}/proxy/network")
        except (requests.RequestException, Exception):
            pass

        # Try standard controller (port 8443)
        try:
            response = requests.get(
                f"https://{self.host}:8443/api/self",
                timeout=3,
                verify=self.verify_ssl,
            )
            if response.status_code in [200, 401]:
                return ("Standard", f"https://{self.host}:8443")
        except (requests.RequestException, Exception):
            pass

        raise RuntimeError(f"Cannot connect to UniFi Controller at {self.host}")

    def _save_session(self):
        """Save session cookies and CSRF token to cache file."""
        try:
            session_data = {
                "cookies": self.session.cookies.get_dict(),
                "csrf_token": self.csrf_token,
                "expires": self.session_expires.isoformat() if self.session_expires else None,
                "controller_type": self.controller_type,
                "base_url": self.base_url,
            }
            with open(self.session_file, "w") as f:
                json.dump(session_data, f)
        except Exception as e:
            # Non-fatal error, just log it
            print(f"Warning: Could not save session: {e}", file=sys.stderr)

    def _load_session(self) -> bool:
        """Load session from cache file if valid."""
        if not self.session_file.exists():
            return False

        try:
            with open(self.session_file, "r") as f:
                session_data = json.load(f)

            # Check if session expired
            expires_str = session_data.get("expires")
            if expires_str:
                expires = datetime.fromisoformat(expires_str)
                if datetime.now() > expires:
                    self.session_file.unlink()
                    return False
                self.session_expires = expires
            else:
                # No expiry means session is invalid
                self.session_file.unlink()
                return False

            # Restore session
            for name, value in session_data.get("cookies", {}).items():
                self.session.cookies.set(name, value)
            self.csrf_token = session_data.get("csrf_token")

            # Verify session is still valid
            if self._verify_session():
                return True
            else:
                self.session_file.unlink()
                return False

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            # Invalid cache file, remove it
            if self.session_file.exists():
                self.session_file.unlink()
            return False

    def _verify_session(self) -> bool:
        """Verify that current session is still valid."""
        try:
            # Try a simple API call
            response = self.session.get(
                f"{self.base_url}/api/self",
                timeout=5,
            )
            return response.status_code == 200
        except (requests.RequestException, Exception):
            return False

    def _login(self) -> bool:
        """Login to controller and get session."""
        # UCG/UDM login is at root /api/auth/login, not under /proxy/network
        if self.controller_type == "UCG/UDM":
            login_url = f"https://{self.host}/api/auth/login"
        else:
            login_url = f"{self.base_url}/api/login"

        try:
            response = self.session.post(
                login_url,
                json={"username": self.username, "password": self.password},
                timeout=10,
            )
            if response.status_code == 200:
                # Extract CSRF token from headers or response
                self.csrf_token = response.headers.get("X-CSRF-Token") or response.headers.get("x-csrf-token")

                # Calculate session expiry (UCG sessions typically last 2 hours)
                # Set expiry to 1.5 hours to be safe
                self.session_expires = datetime.now() + timedelta(hours=1, minutes=30)

                return True
            else:
                raise RuntimeError(f"Login failed: {response.status_code}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Login error: {e}") from e

    def _request(self, method: str, endpoint: str, data: dict = None) -> Any:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"
        headers = {}
        if self.csrf_token and method in ["POST", "PUT", "DELETE"]:
            headers["X-CSRF-Token"] = self.csrf_token

        response = None
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=data,
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()

            # UniFi returns data in { "meta": {...}, "data": [...] }
            if isinstance(result, dict) and "data" in result:
                return result["data"]
            return result
        except requests.exceptions.HTTPError as e:
            if response and response.status_code == 401:
                # Session expired, retry login
                self._login()
                return self._request(method, endpoint, data)
            error_msg = f"API error: {response.status_code}" if response else "API error"
            raise RuntimeError(error_msg) from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Request error: {e}") from e

    def get(self, endpoint: str) -> Any:
        return self._request("GET", endpoint)

    def post(self, endpoint: str, data: dict = None) -> Any:
        return self._request("POST", endpoint, data)

    # Clients
    def get_clients(self, active_only: bool = True) -> list:
        """Get clients (active or all)."""
        endpoint = f"/api/s/{self.site}/stat/sta" if active_only else f"/api/s/{self.site}/rest/user"
        return self.get(endpoint)

    def kick_client(self, mac: str) -> dict:
        """Disconnect client."""
        return self.post(f"/api/s/{self.site}/cmd/stamgr", {"cmd": "kick-sta", "mac": mac})

    def block_client(self, mac: str) -> dict:
        """Block client."""
        return self.post(f"/api/s/{self.site}/cmd/stamgr", {"cmd": "block-sta", "mac": mac})

    def unblock_client(self, mac: str) -> dict:
        """Unblock client."""
        return self.post(f"/api/s/{self.site}/cmd/stamgr", {"cmd": "unblock-sta", "mac": mac})

    # Devices
    def get_devices(self) -> list:
        """Get all devices."""
        return self.get(f"/api/s/{self.site}/stat/device")

    def restart_device(self, mac: str) -> dict:
        """Restart device."""
        return self.post(f"/api/s/{self.site}/cmd/devmgr", {"cmd": "restart", "mac": mac})

    def adopt_device(self, mac: str) -> dict:
        """Adopt device."""
        return self.post(f"/api/s/{self.site}/cmd/devmgr", {"cmd": "adopt", "mac": mac})

    # Statistics
    def get_health(self) -> list:
        """Get site health."""
        return self.get(f"/api/s/{self.site}/stat/health")

    def get_sysinfo(self) -> list:
        """Get system info."""
        return self.get(f"/api/s/{self.site}/stat/sysinfo")

    def get_dpi_stats(self) -> list:
        """Get DPI statistics."""
        return self.get(f"/api/s/{self.site}/stat/sitedpi")

    # Networks
    def get_networks(self) -> list:
        """Get all networks."""
        return self.get(f"/api/s/{self.site}/rest/networkconf")

    def get_wifis(self) -> list:
        """Get WiFi networks."""
        return self.get(f"/api/s/{self.site}/rest/wlanconf")

    # Port Forwarding
    def get_port_forwards(self) -> list:
        """Get all port forwarding rules."""
        return self.get(f"/api/s/{self.site}/rest/portforward")

    def create_port_forward(
        self,
        name: str,
        dst_port: int,
        fwd_ip: str,
        fwd_port: int,
        proto: str = "tcp_udp",
        enabled: bool = True,
    ) -> dict:
        """Create a port forwarding rule."""
        data = {
            "name": name,
            "dst_port": str(dst_port),
            "fwd": fwd_ip,
            "fwd_port": str(fwd_port),
            "proto": proto,  # tcp, udp, tcp_udp
            "enabled": enabled,
            "src": "any",
            "log": False,
        }
        return self.post(f"/api/s/{self.site}/rest/portforward", data)

    def delete_port_forward(self, rule_id: str) -> dict:
        """Delete a port forwarding rule."""
        return self._request("DELETE", f"/api/s/{self.site}/rest/portforward/{rule_id}")

    # Firewall Rules
    def get_firewall_rules(self) -> list:
        """Get all firewall rules."""
        return self.get(f"/api/s/{self.site}/rest/firewallrule")

    def get_firewall_groups(self) -> list:
        """Get firewall groups (IP groups, port groups)."""
        return self.get(f"/api/s/{self.site}/rest/firewallgroup")


class IntegrationAPI:
    """UniFi Integration API v1 client using API key authentication.

    Official REST API with pagination, filtering, and UUID-based identifiers.
    Base URL: https://{host}/proxy/network/integration/v1
    Auth: X-API-Key header
    """

    def __init__(
        self,
        host: str = None,
        api_key: str = None,
        site: str = "default",
        verify_ssl: bool = None,
    ):
        load_env()

        self.host = host or os.environ.get("UNIFI_HOST", "unifi.local")
        self.api_key = api_key or os.environ.get("UNIFI_API_KEY")
        self.site_name = site or os.environ.get("UNIFI_SITE", "default")

        verify_env = os.environ.get("UNIFI_VERIFY_SSL", "false").lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"

        if not self.api_key:
            raise RuntimeError("UNIFI_API_KEY required for Integration API v1")

        self.host = self.host.replace("http://", "").replace("https://", "")
        self.base_url = f"https://{self.host}/proxy/network/integration/v1"

        self.session = requests.Session()
        self.session.verify = self.verify_ssl
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
        })

        self._site_id: Optional[str] = None

    @property
    def site_id(self) -> str:
        """Lazy-resolved site UUID."""
        if not self._site_id:
            self._site_id = self._resolve_site_id()
        return self._site_id

    def _resolve_site_id(self) -> str:
        """Resolve UNIFI_SITE name to UUID via GET /v1/sites."""
        result = self._request("GET", "/sites")
        sites = result.get("data", []) if isinstance(result, dict) else result
        for site in sites:
            if site.get("name", "").lower() == self.site_name.lower():
                return site["id"]
            # Also match internalReference for "default" site
            if site.get("internalReference", "").lower() == self.site_name.lower():
                return site["id"]
        available = [s.get("name", "unknown") for s in sites]
        raise RuntimeError(
            f"Site '{self.site_name}' not found. Available: {', '.join(available)}. "
            f"Set UNIFI_SITE to match one of these names."
        )

    def _request(self, method: str, endpoint: str, data: dict = None,
                 params: dict = None) -> Any:
        """Make Integration API v1 request."""
        url = f"{self.base_url}{endpoint}"
        kwargs: dict[str, Any] = {"timeout": 30}
        if data is not None:
            kwargs["json"] = data
        if params:
            kwargs["params"] = params

        response = None
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            if not response.text:
                return {}
            return response.json()
        except requests.exceptions.HTTPError:
            status = response.status_code if response is not None else 0
            error_msg = "Unknown error"

            if response is not None:
                try:
                    err = response.json()
                    # Only include safe error message, not full response
                    error_msg = err.get("message", "API error")
                except Exception:
                    error_msg = "API error"

            if status == 401:
                raise RuntimeError(f"Integration API: Invalid API key (401)")
            elif status == 403:
                raise RuntimeError(f"Integration API: Forbidden (403)")
            elif status == 404:
                raise RuntimeError(f"Integration API: Not found (404) - {endpoint}")
            elif status == 429:
                raise RuntimeError("Integration API: Rate limit exceeded (429)")
            else:
                raise RuntimeError(f"Integration API error {status}: {error_msg}")
        except requests.exceptions.ConnectionError:
            raise RuntimeError(f"Cannot connect to Integration API at {self.base_url}")
        except Exception as e:
            raise RuntimeError(f"Integration API request error: {e}") from e

    def _paginated_get(self, endpoint: str, limit: int = 50,
                       offset: int = 0, filter_str: str = None,
                       max_pages: int = 100) -> tuple[list, int]:
        """Paginated GET request. Returns (data_list, totalCount).

        Args:
            endpoint: API endpoint
            limit: Results per page (max 100)
            offset: Starting offset
            filter_str: Optional filter string
            max_pages: Maximum pages to prevent infinite loops (default 100)
        """
        # Validate pagination parameters
        if limit < 1 or limit > 1000:
            raise ValueError("Limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Offset must be non-negative")
        if max_pages < 1:
            raise ValueError("max_pages must be positive")

        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if filter_str:
            params["filter"] = filter_str
        result = self._request("GET", endpoint, params=params)
        if isinstance(result, dict):
            return result.get("data", []), result.get("totalCount", 0)
        return result if isinstance(result, list) else [], 0

    # --- Info ---

    def get_info(self) -> dict:
        """GET /v1/info - application version."""
        return self._request("GET", "/info")

    def get_sites(self) -> list:
        """GET /v1/sites - list all sites."""
        data, _ = self._paginated_get("/sites", limit=100)
        return data

    # --- Devices ---

    def get_devices(self, limit: int = 50, offset: int = 0) -> tuple[list, int]:
        """GET /v1/sites/{siteId}/devices (paginated)."""
        return self._paginated_get(f"/sites/{self.site_id}/devices", limit, offset)

    def get_device(self, device_id: str) -> dict:
        """GET /v1/sites/{siteId}/devices/{deviceId}."""
        return self._request("GET", f"/sites/{self.site_id}/devices/{device_id}")

    def get_device_statistics(self, device_id: str) -> dict:
        """GET /v1/sites/{siteId}/devices/{deviceId}/statistics/latest."""
        return self._request("GET", f"/sites/{self.site_id}/devices/{device_id}/statistics/latest")

    def restart_device(self, device_id: str) -> dict:
        """POST /v1/sites/{siteId}/devices/{deviceId}/actions - RESTART."""
        return self._request("POST", f"/sites/{self.site_id}/devices/{device_id}/actions",
                             data={"action": "RESTART"})

    def adopt_device(self, mac: str) -> dict:
        """POST /v1/sites/{siteId}/devices - adopt by MAC."""
        return self._request("POST", f"/sites/{self.site_id}/devices",
                             data={"macAddress": mac, "ignoreDeviceLimit": False})

    def power_cycle_port(self, device_id: str, port_idx: int) -> dict:
        """POST .../ports/{portIdx}/actions - POWER_CYCLE."""
        return self._request(
            "POST",
            f"/sites/{self.site_id}/devices/{device_id}/interfaces/ports/{port_idx}/actions",
            data={"action": "POWER_CYCLE"},
        )

    def get_pending_devices(self, limit: int = 50, offset: int = 0) -> tuple[list, int]:
        """GET /v1/pending-devices (paginated)."""
        return self._paginated_get("/pending-devices", limit, offset)

    # --- Clients ---

    def get_clients(self, limit: int = 50, offset: int = 0) -> tuple[list, int]:
        """GET /v1/sites/{siteId}/clients (paginated)."""
        return self._paginated_get(f"/sites/{self.site_id}/clients", limit, offset)

    def get_client(self, client_id: str) -> dict:
        """GET /v1/sites/{siteId}/clients/{clientId}."""
        return self._request("GET", f"/sites/{self.site_id}/clients/{client_id}")

    def authorize_guest(self, client_id: str, time_limit: int = None,
                        data_limit: int = None) -> dict:
        """POST /v1/sites/{siteId}/clients/{clientId}/actions - AUTHORIZE_GUEST_ACCESS."""
        body: dict[str, Any] = {"action": "AUTHORIZE_GUEST_ACCESS"}
        if time_limit is not None:
            body["timeLimitMinutes"] = time_limit
        if data_limit is not None:
            body["dataUsageLimitMBytes"] = data_limit
        return self._request("POST", f"/sites/{self.site_id}/clients/{client_id}/actions",
                             data=body)

    def unauthorize_guest(self, client_id: str) -> dict:
        """POST /v1/sites/{siteId}/clients/{clientId}/actions - UNAUTHORIZE_GUEST_ACCESS."""
        return self._request("POST", f"/sites/{self.site_id}/clients/{client_id}/actions",
                             data={"action": "UNAUTHORIZE_GUEST_ACCESS"})

    # --- Networks ---

    def get_networks(self, limit: int = 50, offset: int = 0) -> tuple[list, int]:
        """GET /v1/sites/{siteId}/networks (paginated)."""
        return self._paginated_get(f"/sites/{self.site_id}/networks", limit, offset)

    def get_network(self, network_id: str) -> dict:
        """GET /v1/sites/{siteId}/networks/{networkId}."""
        return self._request("GET", f"/sites/{self.site_id}/networks/{network_id}")

    def create_network(self, config: dict) -> dict:
        """POST /v1/sites/{siteId}/networks."""
        return self._request("POST", f"/sites/{self.site_id}/networks", data=config)

    def update_network(self, network_id: str, config: dict) -> dict:
        """PUT /v1/sites/{siteId}/networks/{networkId}."""
        return self._request("PUT", f"/sites/{self.site_id}/networks/{network_id}", data=config)

    def delete_network(self, network_id: str) -> dict:
        """DELETE /v1/sites/{siteId}/networks/{networkId}."""
        return self._request("DELETE", f"/sites/{self.site_id}/networks/{network_id}")

    def get_network_references(self, network_id: str) -> dict:
        """GET /v1/sites/{siteId}/networks/{networkId}/references."""
        return self._request("GET", f"/sites/{self.site_id}/networks/{network_id}/references")

    # --- WiFi Broadcasts ---

    def get_wifi_broadcasts(self, limit: int = 50, offset: int = 0) -> tuple[list, int]:
        """GET /v1/sites/{siteId}/wifi/broadcasts (paginated)."""
        return self._paginated_get(f"/sites/{self.site_id}/wifi/broadcasts", limit, offset)

    def get_wifi_broadcast(self, broadcast_id: str) -> dict:
        """GET /v1/sites/{siteId}/wifi/broadcasts/{id}."""
        return self._request("GET", f"/sites/{self.site_id}/wifi/broadcasts/{broadcast_id}")

    def create_wifi_broadcast(self, config: dict) -> dict:
        """POST /v1/sites/{siteId}/wifi/broadcasts."""
        return self._request("POST", f"/sites/{self.site_id}/wifi/broadcasts", data=config)

    def update_wifi_broadcast(self, broadcast_id: str, config: dict) -> dict:
        """PUT /v1/sites/{siteId}/wifi/broadcasts/{id}."""
        return self._request("PUT", f"/sites/{self.site_id}/wifi/broadcasts/{broadcast_id}",
                             data=config)

    def delete_wifi_broadcast(self, broadcast_id: str) -> dict:
        """DELETE /v1/sites/{siteId}/wifi/broadcasts/{id}."""
        return self._request("DELETE", f"/sites/{self.site_id}/wifi/broadcasts/{broadcast_id}")


class UniFiDualAPI:
    """Dual-API facade: Integration API v1 (primary) + Legacy (fallback).

    Credential routing:
    - UNIFI_API_KEY only              -> Integration API only
    - UNIFI_USERNAME + UNIFI_PASSWORD -> Legacy only (current behavior)
    - Both                            -> Integration primary, legacy fallback
    """

    def __init__(
        self,
        host: str = None,
        username: str = None,
        password: str = None,
        api_key: str = None,
        site: str = "default",
        verify_ssl: bool = None,
    ):
        load_env()

        self.host = host or os.environ.get("UNIFI_HOST", "unifi.local")
        _api_key = api_key or os.environ.get("UNIFI_API_KEY")
        _username = username or os.environ.get("UNIFI_USERNAME")
        _password = password or os.environ.get("UNIFI_PASSWORD")
        _site = site or os.environ.get("UNIFI_SITE", "default")

        verify_env = os.environ.get("UNIFI_VERIFY_SSL", "false").lower()
        _verify = verify_ssl if verify_ssl is not None else verify_env == "true"

        self._integration: Optional[IntegrationAPI] = None
        self._legacy: Optional[UniFiAPI] = None
        self._last_source: str = ""  # "integration" or "legacy" - set by _dual_route

        if _api_key:
            self._integration = IntegrationAPI(
                host=self.host, api_key=_api_key,
                site=_site, verify_ssl=_verify,
            )

        if _username and _password:
            self._legacy = UniFiAPI(
                host=self.host, username=_username,
                password=_password, site=_site, verify_ssl=_verify,
            )

        if not self._integration and not self._legacy:
            raise RuntimeError(
                "No UniFi credentials configured. Set either:\n"
                "  UNIFI_API_KEY (Integration API v1) or\n"
                "  UNIFI_USERNAME + UNIFI_PASSWORD (Legacy API) or\n"
                "  All three (Dual mode)"
            )

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

    def _require_legacy(self, feature: str) -> UniFiAPI:
        if not self._legacy:
            raise RuntimeError(
                f"'{feature}' requires Legacy API (UNIFI_USERNAME + UNIFI_PASSWORD)"
            )
        return self._legacy

    def _require_integration(self, feature: str) -> IntegrationAPI:
        if not self._integration:
            raise RuntimeError(
                f"'{feature}' requires Integration API v1 (UNIFI_API_KEY)"
            )
        return self._integration

    # --- Dual-routed (prefer Integration, fallback Legacy) ---

    def _dual_route(self, integration_fn, legacy_fn, feature: str):
        """Try Integration API first, fall back to Legacy on error.

        Sets self._last_source to "integration" or "legacy" to indicate
        which API actually served the request (for display formatting).
        """
        if self.has_integration:
            try:
                result = integration_fn()
                self._last_source = "integration"
                return result
            except RuntimeError:
                if self.has_legacy:
                    print(f"Integration API failed for '{feature}', falling back to Legacy",
                          file=sys.stderr)
                    result = legacy_fn()
                    self._last_source = "legacy"
                    return result
                raise
        if self.has_legacy:
            result = legacy_fn()
            self._last_source = "legacy"
            return result
        raise RuntimeError(f"No API available for '{feature}'")

    def get_clients(self, active_only: bool = True,
                    limit: int = 50, offset: int = 0) -> list:
        def via_integration():
            data, _ = self._integration.get_clients(limit, offset)
            return data
        def via_legacy():
            return self._legacy.get_clients(active_only)[offset:offset + limit]
        return self._dual_route(via_integration, via_legacy, "clients")

    def get_devices(self, limit: int = 50, offset: int = 0) -> list:
        def via_integration():
            data, _ = self._integration.get_devices(limit, offset)
            return data
        def via_legacy():
            return self._legacy.get_devices()[offset:offset + limit]
        return self._dual_route(via_integration, via_legacy, "devices")

    def get_networks(self, limit: int = 50, offset: int = 0) -> list:
        def via_integration():
            data, _ = self._integration.get_networks(limit, offset)
            return data
        def via_legacy():
            return self._legacy.get_networks()[offset:offset + limit]
        return self._dual_route(via_integration, via_legacy, "networks")

    def get_wifis(self, limit: int = 50, offset: int = 0) -> list:
        def via_integration():
            data, _ = self._integration.get_wifi_broadcasts(limit, offset)
            return data
        def via_legacy():
            return self._legacy.get_wifis()[offset:offset + limit]
        return self._dual_route(via_integration, via_legacy, "wifis")

    def restart_device(self, id_or_mac: str) -> dict:
        return self._dual_route(
            lambda: self._integration.restart_device(id_or_mac),
            lambda: self._legacy.restart_device(id_or_mac),
            "restart-device",
        )

    def adopt_device(self, mac: str) -> dict:
        return self._dual_route(
            lambda: self._integration.adopt_device(mac),
            lambda: self._legacy.adopt_device(mac),
            "adopt",
        )

    # --- Integration-only ---

    def get_info(self) -> dict:
        return self._require_integration("info").get_info()

    def get_sites(self) -> list:
        return self._require_integration("sites").get_sites()

    def get_device_detail(self, device_id: str) -> dict:
        return self._require_integration("device-detail").get_device(device_id)

    def get_device_stats(self, device_id: str) -> dict:
        return self._require_integration("device-stats").get_device_statistics(device_id)

    def get_client_detail(self, client_id: str) -> dict:
        return self._require_integration("client-detail").get_client(client_id)

    def get_pending_devices(self, limit: int = 50, offset: int = 0) -> list:
        data, _ = self._require_integration("pending-devices").get_pending_devices(limit, offset)
        return data

    def power_cycle_port(self, device_id: str, port_idx: int) -> dict:
        return self._require_integration("power-cycle-port").power_cycle_port(device_id, port_idx)

    def authorize_guest(self, client_id: str, time_limit: int = None,
                        data_limit: int = None) -> dict:
        return self._require_integration("authorize-guest").authorize_guest(
            client_id, time_limit, data_limit)

    def unauthorize_guest(self, client_id: str) -> dict:
        return self._require_integration("unauthorize-guest").unauthorize_guest(client_id)

    def get_network_detail(self, network_id: str) -> dict:
        return self._require_integration("network-detail").get_network(network_id)

    def create_network(self, config: dict) -> dict:
        return self._require_integration("create-network").create_network(config)

    def update_network(self, network_id: str, config: dict) -> dict:
        return self._require_integration("update-network").update_network(network_id, config)

    def delete_network(self, network_id: str) -> dict:
        return self._require_integration("delete-network").delete_network(network_id)

    def get_network_references(self, network_id: str) -> dict:
        return self._require_integration("network-references").get_network_references(network_id)

    def get_wifi_detail(self, broadcast_id: str) -> dict:
        return self._require_integration("wifi-detail").get_wifi_broadcast(broadcast_id)

    def create_wifi(self, config: dict) -> dict:
        return self._require_integration("create-wifi").create_wifi_broadcast(config)

    def update_wifi(self, broadcast_id: str, config: dict) -> dict:
        return self._require_integration("update-wifi").update_wifi_broadcast(broadcast_id, config)

    def delete_wifi(self, broadcast_id: str) -> dict:
        return self._require_integration("delete-wifi").delete_wifi_broadcast(broadcast_id)

    # --- Legacy-only ---

    def kick_client(self, mac: str) -> dict:
        return self._require_legacy("kick").kick_client(mac)

    def block_client(self, mac: str) -> dict:
        return self._require_legacy("block").block_client(mac)

    def unblock_client(self, mac: str) -> dict:
        return self._require_legacy("unblock").unblock_client(mac)

    def get_health(self) -> list:
        return self._require_legacy("health").get_health()

    def get_sysinfo(self) -> list:
        return self._require_legacy("sysinfo").get_sysinfo()

    def get_dpi_stats(self) -> list:
        return self._require_legacy("dpi-stats").get_dpi_stats()

    def get_port_forwards(self) -> list:
        return self._require_legacy("port-forwards").get_port_forwards()

    def create_port_forward(self, name: str, dst_port: int, fwd_ip: str,
                            fwd_port: int, proto: str = "tcp_udp") -> dict:
        return self._require_legacy("create-port-forward").create_port_forward(
            name=name, dst_port=dst_port, fwd_ip=fwd_ip,
            fwd_port=fwd_port, proto=proto,
        )

    def delete_port_forward(self, rule_id: str) -> dict:
        return self._require_legacy("delete-port-forward").delete_port_forward(rule_id)

    def get_firewall_rules(self) -> list:
        return self._require_legacy("firewall-rules").get_firewall_rules()

    def get_firewall_groups(self) -> list:
        return self._require_legacy("firewall-groups").get_firewall_groups()


# ---------------------------------------------------------------------------
# Human-readable formatting (used by agent pipeline)
# ---------------------------------------------------------------------------


def format_agent_output(action: str, data: Any) -> Optional[str]:
    """Format raw data into human-readable text for Telegram/agent output.

    Called by skill_executor when available, producing compact text
    instead of raw JSON that would overwhelm the LLM formatter.

    Args:
        action: The action that produced the data (e.g. "clients", "devices")
        data: Raw Python data returned by execute()

    Returns:
        Formatted string, or None if no formatter available (falls back to JSON)
    """
    if action == "clients":
        return _format_clients(data)
    elif action == "devices":
        return _format_devices(data)
    elif action == "networks":
        return _format_networks(data)
    elif action == "wifis":
        return _format_wifis(data)
    elif action == "health":
        return _format_health(data)
    elif action == "port-forwards":
        return _format_port_forwards(data)
    elif action == "firewall-rules":
        return _format_firewall_rules(data)
    return None


def _format_clients(clients: list) -> str:
    """Format clients list into human-readable text."""
    if not clients:
        return "Keine Clients gefunden."

    # Detect API source from field names
    is_integration = bool(clients[0].get("type") in ("WIRED", "WIRELESS", "VPN"))

    if is_integration:
        wired = [c for c in clients if c.get("type") == "WIRED"]
        wireless = [c for c in clients if c.get("type") == "WIRELESS"]
        vpn = [c for c in clients if c.get("type") == "VPN"]
    else:
        wired = [c for c in clients if not c.get("essid")]
        wireless = [c for c in clients if c.get("essid")]
        vpn = []

    lines = [f"Netzwerk-Clients ({len(clients)} Geräte)\n"]

    for label, group, icon in [("Kabelgebunden", wired, "📡"), ("WLAN", wireless, "📶"), ("VPN", vpn, "🔒")]:
        if not group:
            continue
        lines.append(f"{label} ({len(group)})")
        for c in group[:15]:
            if is_integration:
                name = c.get("name", c.get("macAddress", "?"))
                ip = c.get("ipAddress", "?")
            else:
                name = c.get("name") or c.get("hostname") or c.get("mac", "?")
                ip = c.get("ip", "?")
            lines.append(f"  {icon} {name} ({ip})")
        if len(group) > 15:
            lines.append(f"  ... und {len(group) - 15} weitere")
        lines.append("")

    return "\n".join(lines).strip()


def _format_devices(devices: list) -> str:
    """Format devices list into human-readable text."""
    if not devices:
        return "Keine Geräte gefunden."

    is_integration = isinstance(devices[0].get("state"), str)

    lines = [f"Netzwerk-Geräte ({len(devices)} Geräte)\n"]
    for dev in devices:
        if is_integration:
            name = dev.get("name", dev.get("macAddress", "?"))
            model = dev.get("model", "?")
            state = dev.get("state", "?")
            icon = "🟢" if state == "ONLINE" else "🔴"
            features = dev.get("features", [])
            if "accessPoint" in features:
                t = "📡"
            elif "switching" in features:
                t = "🔀"
            elif "gateway" in features:
                t = "🌐"
            else:
                t = "📦"
            ip = dev.get("ipAddress", "?")
            lines.append(f"{icon} {t} {name} ({model}) - {ip}")
        else:
            name = dev.get("name", dev.get("mac", "?"))
            model = dev.get("model", "?")
            state = dev.get("state", 0)
            icon = "🟢" if state == 1 else "🔴"
            dev_type = dev.get("type", "unknown")
            type_icons = {"ugw": "🌐", "usw": "🔀", "uap": "📡"}
            t = type_icons.get(dev_type, "📦")
            lines.append(f"{icon} {t} {name} ({model})")

    return "\n".join(lines).strip()


def _format_networks(networks: list) -> str:
    """Format networks list into human-readable text."""
    if not networks:
        return "Keine Netzwerke gefunden."

    lines = [f"Netzwerke ({len(networks)})\n"]
    for net in networks:
        name = net.get("name", "?")
        vlan = net.get("vlanId", net.get("vlan", ""))
        enabled = net.get("enabled", True)
        icon = "🟢" if enabled else "⚫"
        vlan_str = f" (VLAN {vlan})" if vlan else ""
        lines.append(f"{icon} {name}{vlan_str}")

    return "\n".join(lines).strip()


def _format_wifis(wifis: list) -> str:
    """Format WiFi broadcasts list into human-readable text."""
    if not wifis:
        return "Keine WLANs gefunden."

    lines = [f"WLAN-Netzwerke ({len(wifis)})\n"]
    for wifi in wifis:
        name = wifi.get("name", "?")
        enabled = wifi.get("enabled", False)
        icon = "🟢" if enabled else "⚫"
        sec_config = wifi.get("securityConfiguration", {})
        security = sec_config.get("type", wifi.get("security", "?")) if isinstance(sec_config, dict) else wifi.get("security", "?")
        lines.append(f"{icon} {name} ({security})")

    return "\n".join(lines).strip()


def _format_health(health: list) -> str:
    """Format health data into human-readable text."""
    if not health:
        return "Keine Gesundheitsdaten."

    lines = ["Netzwerk-Gesundheit\n"]
    for item in health:
        subsystem = item.get("subsystem", "?")
        status = item.get("status", "unknown")
        icon = "🟢" if status == "ok" else "🟡" if status == "warning" else "🔴"
        lines.append(f"{icon} {subsystem}: {status}")

    return "\n".join(lines).strip()


def _format_port_forwards(rules: list) -> str:
    """Format port forwarding rules into human-readable text."""
    if not rules:
        return "Keine Port-Forwarding-Regeln."

    lines = [f"Port-Forwarding ({len(rules)} Regeln)\n"]
    for r in rules:
        name = r.get("name", "?")
        enabled = r.get("enabled", True)
        icon = "🟢" if enabled else "⚫"
        dst_port = r.get("dst_port", "?")
        fwd_ip = r.get("fwd", "?")
        fwd_port = r.get("fwd_port", "?")
        proto = r.get("proto", "tcp_udp")
        lines.append(f"{icon} {name}: :{dst_port} -> {fwd_ip}:{fwd_port} ({proto})")

    return "\n".join(lines).strip()


def _format_firewall_rules(rules: list) -> str:
    """Format firewall rules into human-readable text."""
    if not rules:
        return "Keine Firewall-Regeln."

    lines = [f"Firewall-Regeln ({len(rules)})\n"]
    for rule in rules:
        name = rule.get("name", "?")
        enabled = rule.get("enabled", True)
        action = rule.get("action", "?")
        icon = "🟢" if enabled else "⚫"
        action_icon = "✅" if action == "accept" else "🚫" if action in ("drop", "reject") else "❓"
        ruleset = rule.get("ruleset", "?")
        lines.append(f"{icon} {action_icon} {name} ({ruleset})")

    return "\n".join(lines).strip()


def format_output(data: Any, format_type: str = "table") -> str:
    """Format output for display."""
    if format_type == "json":
        return json.dumps(data, indent=2)

    if isinstance(data, list):
        if not data:
            return "No results"
        if isinstance(data[0], dict):
            # Table format
            keys = list(data[0].keys())[:5]  # Show first 5 columns
            lines = ["\t".join(keys)]
            for item in data:
                lines.append("\t".join(str(item.get(k, "")) for k in keys))
            return "\n".join(lines)
    elif isinstance(data, dict):
        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v)[:100]
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    return str(data)


def execute(action: str, args: dict) -> Any:
    """Execute a UniFi Network action directly (no CLI).

    Args:
        action: Command name (e.g. "clients", "devices", "kick")
        args: Dict of arguments (e.g. {"mac": "aa:bb:cc:dd:ee:ff"})

    Returns:
        Raw Python data (dict/list)

    Raises:
        ValueError: Unknown action or invalid arguments
        KeyError: Missing required argument
        RuntimeError: API unavailable for this action
    """
    api = UniFiDualAPI()

    # Validate and sanitize pagination parameters
    try:
        limit = int(args.get("limit", 50))
        offset = int(args.get("offset", 0))
    except (ValueError, TypeError):
        raise ValueError("limit and offset must be valid integers")

    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be non-negative")

    # --- Dual-routed (Integration preferred, Legacy fallback) ---
    if action == "detect":
        result = {"api_mode": api.api_mode}
        if api.has_legacy:
            result["controller_type"] = api._legacy.controller_type
            result["base_url"] = api._legacy.base_url
        if api.has_integration:
            result["integration_base"] = api._integration.base_url
        return result
    elif action == "clients":
        return api.get_clients(
            active_only=not args.get("all", False),
            limit=limit, offset=offset,
        )
    elif action == "devices":
        return api.get_devices(limit=limit, offset=offset)
    elif action == "networks":
        return api.get_networks(limit=limit, offset=offset)
    elif action == "wifis":
        return api.get_wifis(limit=limit, offset=offset)
    elif action == "restart-device":
        return api.restart_device(args.get("id") or args.get("mac"))
    elif action == "adopt":
        return api.adopt_device(args["mac"])

    # --- Integration-only ---
    elif action == "info":
        return api.get_info()
    elif action == "sites":
        return api.get_sites()
    elif action == "device-detail":
        return api.get_device_detail(args["id"])
    elif action == "device-stats":
        return api.get_device_stats(args["id"])
    elif action == "pending-devices":
        return api.get_pending_devices(limit=limit, offset=offset)
    elif action == "power-cycle-port":
        return api.power_cycle_port(args["device_id"], int(args["port_idx"]))
    elif action == "client-detail":
        return api.get_client_detail(args["id"])
    elif action == "authorize-guest":
        return api.authorize_guest(
            args["id"],
            time_limit=int(args["time_limit"]) if args.get("time_limit") else None,
            data_limit=int(args["data_limit"]) if args.get("data_limit") else None,
        )
    elif action == "unauthorize-guest":
        return api.unauthorize_guest(args["id"])
    elif action == "network-detail":
        return api.get_network_detail(args["id"])
    elif action == "create-network":
        config = {
            "name": args["name"],
            "management": args.get("management", "GATEWAY"),
            "enabled": True,
            "vlanId": int(args["vlan"]) if args.get("vlan") else 1,
        }
        return api.create_network(config)
    elif action == "update-network":
        config = {}
        if args.get("name"):
            config["name"] = args["name"]
        if args.get("vlan"):
            config["vlanId"] = int(args["vlan"])
        if args.get("enabled") is not None:
            config["enabled"] = args["enabled"]
        return api.update_network(args["id"], config)
    elif action == "delete-network":
        return api.delete_network(args["id"])
    elif action == "network-references":
        return api.get_network_references(args["id"])
    elif action == "wifi-detail":
        return api.get_wifi_detail(args["id"])
    elif action == "create-wifi":
        config = {
            "type": args.get("type", "STANDARD"),
            "name": args["name"],
            "enabled": True,
            "securityConfiguration": {"type": args.get("security", "WPA2")},
            "multicastToUnicastConversionEnabled": True,
            "clientIsolationEnabled": False,
            "hideName": False,
            "uapsdEnabled": True,
        }
        return api.create_wifi(config)
    elif action == "update-wifi":
        config = {}
        if args.get("name"):
            config["name"] = args["name"]
        if args.get("enabled") is not None:
            config["enabled"] = args["enabled"]
        return api.update_wifi(args["id"], config)
    elif action == "delete-wifi":
        return api.delete_wifi(args["id"])

    # --- Legacy-only ---
    elif action == "health":
        return api.get_health()
    elif action == "sysinfo":
        return api.get_sysinfo()
    elif action == "kick":
        return api.kick_client(args["mac"])
    elif action == "block":
        return api.block_client(args["mac"])
    elif action == "unblock":
        return api.unblock_client(args["mac"])
    elif action == "dpi-stats":
        return api.get_dpi_stats()
    elif action == "port-forwards":
        return api.get_port_forwards()
    elif action == "create-port-forward":
        return api.create_port_forward(
            name=args["name"],
            dst_port=int(args["dst_port"]),
            fwd_ip=args["fwd_ip"],
            fwd_port=int(args["fwd_port"]),
            proto=args.get("proto", "tcp_udp"),
        )
    elif action == "delete-port-forward":
        return api.delete_port_forward(args["rule_id"])
    elif action == "firewall-rules":
        return api.get_firewall_rules()
    elif action == "firewall-groups":
        return api.get_firewall_groups()
    else:
        raise ValueError(f"Unknown action: {action}")


def main():
    # Common parent parser for --json and --site flags (inherited by all subcommands)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Output as JSON")
    common.add_argument("--site", help="Site name (default: default)")

    parser = argparse.ArgumentParser(description="UniFi Network API Client (Dual-Mode)")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # --- Info / Detection ---
    subparsers.add_parser("detect", parents=[common], help="Detect API mode and controller type")
    subparsers.add_parser("info", parents=[common], help="Application version (Integration API)")
    subparsers.add_parser("sites", parents=[common], help="List sites with UUIDs (Integration API)")
    subparsers.add_parser("health", parents=[common], help="Site health (Legacy API)")
    subparsers.add_parser("sysinfo", parents=[common], help="System info (Legacy API)")

    # --- Clients ---
    clients_p = subparsers.add_parser("clients", parents=[common], help="List clients")
    clients_p.add_argument("--all", action="store_true", help="Include inactive (Legacy only)")
    clients_p.add_argument("--limit", type=int, default=50, help="Max results")
    clients_p.add_argument("--offset", type=int, default=0, help="Pagination offset")

    client_detail = subparsers.add_parser("client-detail", parents=[common], help="Client details (Integration API)")
    client_detail.add_argument("id", help="Client UUID")

    kick = subparsers.add_parser("kick", parents=[common], help="Kick client (Legacy API)")
    kick.add_argument("mac", help="Client MAC address")

    block = subparsers.add_parser("block", parents=[common], help="Block client (Legacy API)")
    block.add_argument("mac", help="Client MAC address")

    unblock = subparsers.add_parser("unblock", parents=[common], help="Unblock client (Legacy API)")
    unblock.add_argument("mac", help="Client MAC address")

    auth_guest = subparsers.add_parser("authorize-guest", parents=[common], help="Authorize guest (Integration API)")
    auth_guest.add_argument("id", help="Client UUID")
    auth_guest.add_argument("--time-limit", type=int, help="Time limit in minutes")
    auth_guest.add_argument("--data-limit", type=int, help="Data limit in MB")

    unauth_guest = subparsers.add_parser("unauthorize-guest", parents=[common], help="Unauthorize guest (Integration API)")
    unauth_guest.add_argument("id", help="Client UUID")

    # --- Devices ---
    devices_p = subparsers.add_parser("devices", parents=[common], help="List devices")
    devices_p.add_argument("--limit", type=int, default=50, help="Max results")
    devices_p.add_argument("--offset", type=int, default=0, help="Pagination offset")

    device_detail = subparsers.add_parser("device-detail", parents=[common], help="Device details (Integration API)")
    device_detail.add_argument("id", help="Device UUID")

    device_stats = subparsers.add_parser("device-stats", parents=[common], help="Device statistics (Integration API)")
    device_stats.add_argument("id", help="Device UUID")

    restart = subparsers.add_parser("restart-device", parents=[common], help="Restart device")
    restart.add_argument("id_or_mac", help="Device UUID (Integration) or MAC (Legacy)")

    adopt = subparsers.add_parser("adopt", parents=[common], help="Adopt device")
    adopt.add_argument("mac", help="Device MAC address")

    subparsers.add_parser("pending-devices", parents=[common], help="List pending devices (Integration API)")

    power_cycle = subparsers.add_parser("power-cycle-port", parents=[common], help="Power cycle port (Integration API)")
    power_cycle.add_argument("device_id", help="Device UUID")
    power_cycle.add_argument("port_idx", type=int, help="Port index")

    # --- Networks ---
    networks_p = subparsers.add_parser("networks", parents=[common], help="List networks")
    networks_p.add_argument("--limit", type=int, default=50, help="Max results")
    networks_p.add_argument("--offset", type=int, default=0, help="Pagination offset")

    net_detail = subparsers.add_parser("network-detail", parents=[common], help="Network details (Integration API)")
    net_detail.add_argument("id", help="Network UUID")

    net_refs = subparsers.add_parser("network-references", parents=[common], help="Network references (Integration API)")
    net_refs.add_argument("id", help="Network UUID")

    create_net = subparsers.add_parser("create-network", parents=[common], help="Create network (Integration API)")
    create_net.add_argument("name", help="Network name")
    create_net.add_argument("--vlan", type=int, default=1, help="VLAN ID")
    create_net.add_argument("--management", default="GATEWAY", choices=["GATEWAY", "SWITCH", "UNMANAGED"])

    update_net = subparsers.add_parser("update-network", parents=[common], help="Update network (Integration API)")
    update_net.add_argument("id", help="Network UUID")
    update_net.add_argument("--name", help="New name")
    update_net.add_argument("--vlan", type=int, help="VLAN ID")
    update_net.add_argument("--enabled", type=bool, help="Enable/disable")

    delete_net = subparsers.add_parser("delete-network", parents=[common], help="Delete network (Integration API)")
    delete_net.add_argument("id", help="Network UUID")

    # --- WiFi ---
    wifis_p = subparsers.add_parser("wifis", parents=[common], help="List WiFi broadcasts")
    wifis_p.add_argument("--limit", type=int, default=50, help="Max results")
    wifis_p.add_argument("--offset", type=int, default=0, help="Pagination offset")

    wifi_detail = subparsers.add_parser("wifi-detail", parents=[common], help="WiFi details (Integration API)")
    wifi_detail.add_argument("id", help="WiFi broadcast UUID")

    create_wifi = subparsers.add_parser("create-wifi", parents=[common], help="Create WiFi (Integration API)")
    create_wifi.add_argument("name", help="SSID name")
    create_wifi.add_argument("--security", default="WPA2", help="Security type")

    update_wifi = subparsers.add_parser("update-wifi", parents=[common], help="Update WiFi (Integration API)")
    update_wifi.add_argument("id", help="WiFi broadcast UUID")
    update_wifi.add_argument("--name", help="New SSID name")
    update_wifi.add_argument("--enabled", type=bool, help="Enable/disable")

    delete_wifi = subparsers.add_parser("delete-wifi", parents=[common], help="Delete WiFi (Integration API)")
    delete_wifi.add_argument("id", help="WiFi broadcast UUID")

    # --- Legacy: Stats ---
    subparsers.add_parser("dpi-stats", parents=[common], help="DPI statistics (Legacy API)")

    # --- Legacy: Port Forwarding ---
    subparsers.add_parser("port-forwards", parents=[common], help="List port forwarding rules (Legacy API)")

    pf_create = subparsers.add_parser("create-port-forward", parents=[common], help="Create port forward (Legacy API)")
    pf_create.add_argument("name", help="Rule name")
    pf_create.add_argument("dst_port", type=int, help="External port")
    pf_create.add_argument("fwd_ip", help="Forward to IP address")
    pf_create.add_argument("fwd_port", type=int, help="Forward to port")
    pf_create.add_argument("--proto", default="tcp_udp", choices=["tcp", "udp", "tcp_udp"])

    pf_delete = subparsers.add_parser("delete-port-forward", parents=[common], help="Delete port forward (Legacy API)")
    pf_delete.add_argument("rule_id", help="Rule ID")

    # --- Legacy: Firewall ---
    subparsers.add_parser("firewall-rules", parents=[common], help="List firewall rules (Legacy API)")
    subparsers.add_parser("firewall-groups", parents=[common], help="List firewall groups (Legacy API)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # --- Detect command (special: doesn't need full API init) ---
    if args.command == "detect":
        load_env()
        api_key = os.environ.get("UNIFI_API_KEY")
        username = os.environ.get("UNIFI_USERNAME")
        host = os.environ.get("UNIFI_HOST", "unifi.local").replace("http://", "").replace("https://", "")

        print(f"Host: {host}")
        print(f"API Key: {'configured' if api_key else 'not set'}")
        print(f"Username: {'configured' if username else 'not set'}")

        if api_key:
            print(f"Integration API: https://{host}/proxy/network/integration/v1")

        if username:
            try:
                requests.get(f"https://{host}/proxy/network/api/self", timeout=3, verify=False)
                print("Legacy Controller: UCG/UDM detected")
                print(f"Legacy Base URL: https://{host}/proxy/network")
            except Exception:
                try:
                    requests.get(f"https://{host}:8443/api/self", timeout=3, verify=False)
                    print("Legacy Controller: Standard detected")
                    print(f"Legacy Base URL: https://{host}:8443")
                except Exception:
                    print("Legacy Controller: not reachable")

        mode = "dual" if api_key and username else "integration" if api_key else "legacy" if username else "none"
        print(f"API Mode: {mode}")
        return

    # --- Initialize Dual API ---
    api = UniFiDualAPI(site=args.site)
    print(f"Connected to UniFi (mode: {api.api_mode})", file=sys.stderr)

    output_format = "json" if args.json else "table"
    result = None

    # === Info commands ===
    if args.command == "info":
        info = api.get_info()
        if args.json:
            result = info
        else:
            print(f"UniFi Network v{info.get('applicationVersion', '?')}")
            return

    elif args.command == "sites":
        sites = api.get_sites()
        if args.json:
            result = sites
        else:
            print(f"📍 **Sites** ({len(sites)})\n")
            for s in sites:
                print(f"  {s.get('name', '?')} (ID: {s.get('id', '?')})")
            return

    elif args.command == "health":
        health = api.get_health()
        if args.json:
            result = health
        else:
            print("🌐 **Netzwerk-Gesundheit**\n")
            for item in health:
                subsystem = item.get("subsystem", "?")
                status = item.get("status", "unknown")
                icon = "🟢" if status == "ok" else "🟡" if status == "warning" else "🔴"
                print(f"   {icon} {subsystem}: {status}")
            return

    elif args.command == "sysinfo":
        result = api.get_sysinfo()

    # === Client commands ===
    elif args.command == "clients":
        limit = getattr(args, "limit", 50)
        offset = getattr(args, "offset", 0)
        clients_data = api.get_clients(active_only=not args.all, limit=limit, offset=offset)
        if args.json:
            result = clients_data
        else:
            if not clients_data:
                print("Keine Clients gefunden.")
                return

            print(f"💻 **Netzwerk-Clients** ({len(clients_data)} Geräte)\n")

            if api._last_source == "integration":
                # Integration API format
                wired = [c for c in clients_data if c.get("type") == "WIRED"]
                wireless = [c for c in clients_data if c.get("type") == "WIRELESS"]
                vpn = [c for c in clients_data if c.get("type") == "VPN"]

                if wired:
                    print(f"**Kabelgebunden** ({len(wired)})")
                    for c in wired[:10]:
                        name = c.get("name", "?")
                        ip = c.get("ipAddress", "?")
                        print(f"  📡 {name} ({ip})")
                    if len(wired) > 10:
                        print(f"  ... und {len(wired) - 10} weitere")
                    print()

                if wireless:
                    print(f"**WLAN** ({len(wireless)})")
                    for c in wireless[:10]:
                        name = c.get("name", "?")
                        ip = c.get("ipAddress", "?")
                        print(f"  📶 {name} ({ip})")
                    if len(wireless) > 10:
                        print(f"  ... und {len(wireless) - 10} weitere")
                    print()

                if vpn:
                    print(f"**VPN** ({len(vpn)})")
                    for c in vpn[:10]:
                        name = c.get("name", "?")
                        ip = c.get("ipAddress", "?")
                        print(f"  🔒 {name} ({ip})")
                    print()
            else:
                # Legacy API format
                wired = [c for c in clients_data if not c.get("is_wired") == False and not c.get("essid")]
                wireless = [c for c in clients_data if c.get("essid")]

                if wired:
                    print(f"**Kabelgebunden** ({len(wired)})")
                    for c in wired[:10]:
                        name = c.get("name") or c.get("hostname") or c.get("mac", "?")
                        ip = c.get("ip", "?")
                        print(f"  📡 {name} ({ip})")
                    if len(wired) > 10:
                        print(f"  ... und {len(wired) - 10} weitere")
                    print()

                if wireless:
                    print(f"**WLAN** ({len(wireless)})")
                    for c in wireless[:10]:
                        name = c.get("name") or c.get("hostname") or c.get("mac", "?")
                        ip = c.get("ip", "?")
                        ssid = c.get("essid", "?")
                        print(f"  📶 {name} ({ip}) - {ssid}")
                    if len(wireless) > 10:
                        print(f"  ... und {len(wireless) - 10} weitere")
            return

    elif args.command == "client-detail":
        detail = api.get_client_detail(args.id)
        if args.json:
            result = detail
        else:
            print(f"👤 **{detail.get('name', '?')}**")
            print(f"   Typ: {detail.get('type', '?')}")
            print(f"   IP: {detail.get('ipAddress', '?')}")
            print(f"   MAC: {detail.get('macAddress', '?')}")
            print(f"   Verbunden seit: {detail.get('connectedAt', '?')}")
            return

    elif args.command == "kick":
        api.kick_client(args.mac)
        print(f"🚫 Client {args.mac} getrennt")
        return

    elif args.command == "block":
        api.block_client(args.mac)
        print(f"🔒 Client {args.mac} blockiert")
        return

    elif args.command == "unblock":
        api.unblock_client(args.mac)
        print(f"🔓 Client {args.mac} entsperrt")
        return

    elif args.command == "authorize-guest":
        api.authorize_guest(
            args.id,
            time_limit=getattr(args, "time_limit", None),
            data_limit=getattr(args, "data_limit", None),
        )
        print(f"✅ Gast {args.id} autorisiert")
        return

    elif args.command == "unauthorize-guest":
        api.unauthorize_guest(args.id)
        print(f"🚫 Gast {args.id} deautorisiert")
        return

    # === Device commands ===
    elif args.command == "devices":
        limit = getattr(args, "limit", 50)
        offset = getattr(args, "offset", 0)
        devices_data = api.get_devices(limit=limit, offset=offset)
        if args.json:
            result = devices_data
        else:
            if not devices_data:
                print("Keine Geräte gefunden.")
                return

            print(f"🔌 **Netzwerk-Geräte** ({len(devices_data)} Geräte)\n")

            if api._last_source == "integration":
                # Integration API format
                for dev in devices_data:
                    name = dev.get("name", dev.get("macAddress", "?"))
                    model = dev.get("model", "?")
                    state = dev.get("state", "?")
                    icon = "🟢" if state == "ONLINE" else "🔴"
                    features = dev.get("features", [])
                    dev_id = dev.get("id", "?")

                    if "accessPoint" in features:
                        type_icon = "📡"
                    elif "switching" in features:
                        type_icon = "🔀"
                    elif "gateway" in features:
                        type_icon = "🌐"
                    else:
                        type_icon = "📦"

                    print(f"{icon} {type_icon} **{name}**")
                    print(f"   Modell: {model} | ID: {dev_id}")
                    print(f"   IP: {dev.get('ipAddress', '?')} | MAC: {dev.get('macAddress', '?')}")
                    print()
            else:
                # Legacy API format
                for dev in devices_data:
                    name = dev.get("name", dev.get("mac", "?"))
                    model = dev.get("model", "?")
                    state = dev.get("state", 0)
                    icon = "🟢" if state == 1 else "🔴"
                    dev_type = dev.get("type", "unknown")

                    type_icons = {"ugw": "🌐", "usw": "🔀", "uap": "📡"}
                    type_icon = type_icons.get(dev_type, "📦")

                    print(f"{icon} {type_icon} **{name}**")
                    print(f"   Modell: {model}")

                    if dev_type == "uap":
                        num_clients = dev.get("num_sta", 0)
                        print(f"   Clients: {num_clients}")
                    print()
            return

    elif args.command == "device-detail":
        detail = api.get_device_detail(args.id)
        if args.json:
            result = detail
        else:
            state = detail.get("state", "?")
            icon = "🟢" if state == "ONLINE" else "🔴"
            print(f"{icon} **{detail.get('name', '?')}**")
            print(f"   Modell: {detail.get('model', '?')}")
            print(f"   MAC: {detail.get('macAddress', '?')}")
            print(f"   IP: {detail.get('ipAddress', '?')}")
            print(f"   Firmware: {detail.get('firmwareVersion', '?')}")
            print(f"   Update verfügbar: {detail.get('firmwareUpdatable', False)}")
            print(f"   Adoptiert: {detail.get('adoptedAt', '?')}")
            return

    elif args.command == "device-stats":
        stats = api.get_device_stats(args.id)
        if args.json:
            result = stats
        else:
            uptime_sec = stats.get("uptimeSec", 0)
            uptime_h = uptime_sec // 3600 if uptime_sec else 0
            uptime_d = uptime_h // 24
            print(f"📊 **Geräte-Statistiken**\n")
            print(f"   Uptime: {uptime_d}d {uptime_h % 24}h")
            print(f"   CPU: {stats.get('cpuUtilizationPct', '?')}%")
            print(f"   RAM: {stats.get('memoryUtilizationPct', '?')}%")
            print(f"   Load (1/5/15 min): {stats.get('loadAverage1Min', '?')} / {stats.get('loadAverage5Min', '?')} / {stats.get('loadAverage15Min', '?')}")
            print(f"   Letzter Heartbeat: {stats.get('lastHeartbeatAt', '?')}")
            uplink = stats.get("uplink", {})
            if uplink:
                tx = uplink.get("txRateBps", 0)
                rx = uplink.get("rxRateBps", 0)
                print(f"   Uplink TX: {tx / 1_000_000:.1f} Mbps | RX: {rx / 1_000_000:.1f} Mbps")
            return

    elif args.command == "restart-device":
        api.restart_device(args.id_or_mac)
        print(f"🔄 Gerät {args.id_or_mac} wird neugestartet")
        return

    elif args.command == "adopt":
        api.adopt_device(args.mac)
        print(f"✅ Gerät {args.mac} wird adoptiert")
        return

    elif args.command == "pending-devices":
        pending = api.get_pending_devices()
        if args.json:
            result = pending
        else:
            if not pending:
                print("Keine ausstehenden Geräte.")
                return
            print(f"⏳ **Ausstehende Geräte** ({len(pending)})\n")
            for dev in pending:
                model = dev.get("model", "?")
                mac = dev.get("macAddress", "?")
                ip = dev.get("ipAddress", "?")
                print(f"  📦 {model} ({mac}) - {ip}")
            return

    elif args.command == "power-cycle-port":
        api.power_cycle_port(args.device_id, args.port_idx)
        print(f"⚡ Port {args.port_idx} an Gerät {args.device_id} wird neugestartet")
        return

    # === Network commands ===
    elif args.command == "networks":
        limit = getattr(args, "limit", 50)
        offset = getattr(args, "offset", 0)
        networks_data = api.get_networks(limit=limit, offset=offset)
        if args.json:
            result = networks_data
        else:
            if not networks_data:
                print("Keine Netzwerke gefunden.")
                return

            print(f"🌐 **Netzwerke** ({len(networks_data)} Netzwerke)\n")
            for net in networks_data:
                name = net.get("name", "?")
                # Integration API uses vlanId, Legacy uses vlan
                vlan = net.get("vlanId", net.get("vlan", ""))
                subnet = net.get("ip_subnet", "")
                net_id = net.get("id", "")
                enabled = net.get("enabled", True)
                icon = "🟢" if enabled else "⚫"

                print(f"  {icon} **{name}**")
                if subnet:
                    print(f"     Subnet: {subnet}")
                if vlan:
                    print(f"     VLAN: {vlan}")
                if net_id:
                    print(f"     ID: {net_id}")
                print()
            return

    elif args.command == "network-detail":
        detail = api.get_network_detail(args.id)
        if args.json:
            result = detail
        else:
            enabled = detail.get("enabled", True)
            icon = "🟢" if enabled else "⚫"
            print(f"{icon} **{detail.get('name', '?')}**")
            print(f"   Management: {detail.get('management', '?')}")
            print(f"   VLAN: {detail.get('vlanId', '?')}")
            print(f"   Isolation: {detail.get('isolationEnabled', False)}")
            print(f"   Internet: {detail.get('internetAccessEnabled', True)}")
            print(f"   mDNS: {detail.get('mdnsForwardingEnabled', False)}")
            return

    elif args.command == "network-references":
        refs = api.get_network_references(args.id)
        if args.json:
            result = refs
        else:
            resources = refs.get("referenceResources", [])
            print(f"🔗 **Netzwerk-Referenzen** ({len(resources)} Ressourcen)\n")
            for res in resources:
                rtype = res.get("resourceType", "?")
                count = res.get("referenceCount", 0)
                print(f"  {rtype}: {count} Referenzen")
            return

    elif args.command == "create-network":
        config = {
            "name": args.name,
            "management": args.management,
            "enabled": True,
            "vlanId": args.vlan,
        }
        result_data = api.create_network(config)
        print(f"✅ Netzwerk '{args.name}' erstellt (ID: {result_data.get('id', '?')})")
        return

    elif args.command == "update-network":
        config = {}
        if args.name:
            config["name"] = args.name
        if args.vlan is not None:
            config["vlanId"] = args.vlan
        if args.enabled is not None:
            config["enabled"] = args.enabled
        api.update_network(args.id, config)
        print(f"✅ Netzwerk {args.id} aktualisiert")
        return

    elif args.command == "delete-network":
        api.delete_network(args.id)
        print(f"🗑️ Netzwerk {args.id} gelöscht")
        return

    # === WiFi commands ===
    elif args.command == "wifis":
        limit = getattr(args, "limit", 50)
        offset = getattr(args, "offset", 0)
        wifis_data = api.get_wifis(limit=limit, offset=offset)
        if args.json:
            result = wifis_data
        else:
            if not wifis_data:
                print("Keine WLANs gefunden.")
                return

            print(f"📶 **WLAN-Netzwerke** ({len(wifis_data)} Netzwerke)\n")
            for wifi in wifis_data:
                name = wifi.get("name", "?")
                enabled = wifi.get("enabled", False)
                icon = "🟢" if enabled else "⚫"
                # Integration API uses securityConfiguration.type, Legacy uses security
                sec_config = wifi.get("securityConfiguration", {})
                security = sec_config.get("type", wifi.get("security", "?")) if isinstance(sec_config, dict) else wifi.get("security", "?")
                wifi_id = wifi.get("id", "")

                print(f"{icon} **{name}**")
                print(f"   Sicherheit: {security}")
                if wifi_id:
                    print(f"   ID: {wifi_id}")
                print()
            return

    elif args.command == "wifi-detail":
        detail = api.get_wifi_detail(args.id)
        if args.json:
            result = detail
        else:
            enabled = detail.get("enabled", False)
            icon = "🟢" if enabled else "⚫"
            sec = detail.get("securityConfiguration", {})
            print(f"{icon} **{detail.get('name', '?')}**")
            print(f"   Typ: {detail.get('type', '?')}")
            print(f"   Sicherheit: {sec.get('type', '?')}")
            print(f"   Client-Isolation: {detail.get('clientIsolationEnabled', False)}")
            print(f"   Versteckt: {detail.get('hideName', False)}")
            return

    elif args.command == "create-wifi":
        config = {
            "type": "STANDARD",
            "name": args.name,
            "enabled": True,
            "securityConfiguration": {"type": args.security},
            "multicastToUnicastConversionEnabled": True,
            "clientIsolationEnabled": False,
            "hideName": False,
            "uapsdEnabled": True,
        }
        result_data = api.create_wifi(config)
        print(f"✅ WLAN '{args.name}' erstellt (ID: {result_data.get('id', '?')})")
        return

    elif args.command == "update-wifi":
        config = {}
        if args.name:
            config["name"] = args.name
        if args.enabled is not None:
            config["enabled"] = args.enabled
        api.update_wifi(args.id, config)
        print(f"✅ WLAN {args.id} aktualisiert")
        return

    elif args.command == "delete-wifi":
        api.delete_wifi(args.id)
        print(f"🗑️ WLAN {args.id} gelöscht")
        return

    # === Legacy-only commands ===
    elif args.command == "dpi-stats":
        result = api.get_dpi_stats()

    elif args.command == "port-forwards":
        result = api.get_port_forwards()

    elif args.command == "create-port-forward":
        api.create_port_forward(
            name=args.name,
            dst_port=args.dst_port,
            fwd_ip=args.fwd_ip,
            fwd_port=args.fwd_port,
            proto=args.proto,
        )
        print(f"✅ Port-Forward '{args.name}' erstellt ({args.dst_port} -> {args.fwd_ip}:{args.fwd_port})")
        return

    elif args.command == "delete-port-forward":
        api.delete_port_forward(args.rule_id)
        print(f"🗑️ Port-Forward {args.rule_id} gelöscht")
        return

    elif args.command == "firewall-rules":
        rules = api.get_firewall_rules()
        if args.json:
            result = rules
        else:
            if not rules:
                print("Keine Firewall-Regeln gefunden.")
                return

            print(f"🔥 **Firewall-Regeln** ({len(rules)} Regeln)\n")
            for rule in rules:
                name = rule.get("name", "Unnamed")
                enabled = rule.get("enabled", False)
                action = rule.get("action", "?")
                ruleset = rule.get("ruleset", "?")
                icon = "🟢" if enabled else "⚫"
                action_icon = "✅" if action == "accept" else "🚫" if action in ["drop", "reject"] else "❓"

                print(f"{icon} {action_icon} **{name}**")
                print(f"   Aktion: {action} | Ruleset: {ruleset}")

                src = rule.get("src_address", rule.get("src_networkconf_id", "any"))
                dst = rule.get("dst_address", rule.get("dst_networkconf_id", "any"))
                print(f"   Von: {src} → Nach: {dst}")

                proto = rule.get("protocol", "all")
                dst_port = rule.get("dst_port", "")
                if dst_port:
                    print(f"   Protokoll: {proto} Port: {dst_port}")
                print()
            return

    elif args.command == "firewall-groups":
        groups = api.get_firewall_groups()
        if args.json:
            result = groups
        else:
            if not groups:
                print("Keine Firewall-Gruppen gefunden.")
                return

            print(f"📋 **Firewall-Gruppen** ({len(groups)} Gruppen)\n")
            for group in groups:
                name = group.get("name", "?")
                group_type = group.get("group_type", "?")
                members = group.get("group_members", [])

                type_icon = "🌐" if group_type == "address-group" else "🔌" if group_type == "port-group" else "📦"
                print(f"{type_icon} **{name}** ({group_type})")
                if members:
                    print(f"   Mitglieder: {', '.join(members[:5])}")
                    if len(members) > 5:
                        print(f"   ... und {len(members) - 5} weitere")
                print()
            return

    if result is not None:
        print(format_output(result, output_format))


if __name__ == "__main__":
    main()
