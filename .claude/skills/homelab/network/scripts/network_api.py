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
import pickle
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
            print("Error: UNIFI_USERNAME and UNIFI_PASSWORD required", file=sys.stderr)
            sys.exit(1)

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
        except:
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
        except:
            pass

        print(f"Error: Cannot connect to UniFi Controller at {self.host}", file=sys.stderr)
        sys.exit(1)

    def _save_session(self):
        """Save session cookies and CSRF token to cache file."""
        try:
            session_data = {
                "cookies": self.session.cookies.get_dict(),
                "csrf_token": self.csrf_token,
                "expires": self.session_expires,
                "controller_type": self.controller_type,
                "base_url": self.base_url,
            }
            with open(self.session_file, "wb") as f:
                pickle.dump(session_data, f)
        except Exception as e:
            # Non-fatal error, just log it
            print(f"Warning: Could not save session: {e}", file=sys.stderr)

    def _load_session(self) -> bool:
        """Load session from cache file if valid."""
        if not self.session_file.exists():
            return False

        try:
            with open(self.session_file, "rb") as f:
                session_data = pickle.load(f)

            # Check if session expired
            expires = session_data.get("expires")
            if expires and datetime.now() > expires:
                self.session_file.unlink()
                return False

            # Restore session
            for name, value in session_data.get("cookies", {}).items():
                self.session.cookies.set(name, value)
            self.csrf_token = session_data.get("csrf_token")
            self.session_expires = session_data.get("expires")

            # Verify session is still valid
            if self._verify_session():
                return True
            else:
                self.session_file.unlink()
                return False

        except Exception as e:
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
        except:
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
                print(f"Login failed: {response.status_code}", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Login error: {e}", file=sys.stderr)
            sys.exit(1)

    def _request(self, method: str, endpoint: str, data: dict = None) -> Any:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"
        headers = {}
        if self.csrf_token and method in ["POST", "PUT", "DELETE"]:
            headers["X-CSRF-Token"] = self.csrf_token

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
            if response.status_code == 401:
                # Session expired, retry login
                self._login()
                return self._request(method, endpoint, data)
            print(f"Error: {response.status_code} - {response.text}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

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


def main():
    parser = argparse.ArgumentParser(description="UniFi Controller API Client")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--site", help="Site name (default: default)")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Info
    subparsers.add_parser("detect", help="Detect controller type")
    subparsers.add_parser("health", help="Site health")
    subparsers.add_parser("sysinfo", help="System info")

    # Clients
    clients = subparsers.add_parser("clients", help="List clients")
    clients.add_argument("--all", action="store_true", help="Include inactive clients")

    kick = subparsers.add_parser("kick", help="Kick (disconnect) client")
    kick.add_argument("mac", help="Client MAC address")

    block = subparsers.add_parser("block", help="Block client")
    block.add_argument("mac", help="Client MAC address")

    unblock = subparsers.add_parser("unblock", help="Unblock client")
    unblock.add_argument("mac", help="Client MAC address")

    # Devices
    subparsers.add_parser("devices", help="List devices")

    restart = subparsers.add_parser("restart-device", help="Restart device")
    restart.add_argument("mac", help="Device MAC address")

    adopt = subparsers.add_parser("adopt", help="Adopt device")
    adopt.add_argument("mac", help="Device MAC address")

    # Networks
    subparsers.add_parser("networks", help="List all networks")
    subparsers.add_parser("wifis", help="List WiFi networks")

    # Stats
    subparsers.add_parser("dpi-stats", help="DPI statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Special case: detect
    if args.command == "detect":
        load_env()
        host = os.environ.get("UNIFI_HOST", "unifi.local")
        host = host.replace("http://", "").replace("https://", "")

        # Try UCG/UDM
        try:
            requests.get(f"https://{host}/proxy/network/api/self", timeout=3, verify=False)
            print("UCG/UDM detected")
            print(f"Base URL: https://{host}/proxy/network")
            return
        except:
            pass

        # Try standard
        try:
            requests.get(f"https://{host}:8443/api/self", timeout=3, verify=False)
            print("Standard Controller detected")
            print(f"Base URL: https://{host}:8443")
            return
        except:
            pass

        print("Could not detect controller type")
        return

    api = UniFiAPI(site=args.site)
    print(f"Connected to UniFi ({api.controller_type})", file=sys.stderr)

    output_format = "json" if args.json else "table"
    result = None

    # Execute commands
    if args.command == "health":
        result = api.get_health()
    elif args.command == "sysinfo":
        result = api.get_sysinfo()
    elif args.command == "clients":
        result = api.get_clients(active_only=not args.all)
    elif args.command == "kick":
        api.kick_client(args.mac)
        print(f"Kicked client {args.mac}")
        return
    elif args.command == "block":
        api.block_client(args.mac)
        print(f"Blocked client {args.mac}")
        return
    elif args.command == "unblock":
        api.unblock_client(args.mac)
        print(f"Unblocked client {args.mac}")
        return
    elif args.command == "devices":
        result = api.get_devices()
    elif args.command == "restart-device":
        api.restart_device(args.mac)
        print(f"Restarting device {args.mac}")
        return
    elif args.command == "adopt":
        api.adopt_device(args.mac)
        print(f"Adopting device {args.mac}")
        return
    elif args.command == "networks":
        result = api.get_networks()
    elif args.command == "wifis":
        result = api.get_wifis()
    elif args.command == "dpi-stats":
        result = api.get_dpi_stats()

    if result is not None:
        print(format_output(result, output_format))


if __name__ == "__main__":
    main()
