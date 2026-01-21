#!/usr/bin/env python3
"""
Pi-hole API Client

CLI tool for managing Pi-hole DNS and ad-blocking.
Supports both v6 (REST API) and v5 (legacy PHP API).

Usage:
    python pihole_api.py summary
    python pihole_api.py disable --duration 300
    python pihole_api.py block example.com
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

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


class PiHoleAPI:
    """Pi-hole API client supporting v5 (legacy) and v6 (REST)."""

    def __init__(
        self,
        host: str = None,
        password: str = None,
        api_key: str = None,
        verify_ssl: bool = True,
    ):
        load_env()

        self.host = host or os.environ.get("PIHOLE_HOST", "pihole.local")
        self.password = password or os.environ.get("PIHOLE_PASSWORD")
        self.api_key = api_key or os.environ.get("PIHOLE_API_KEY")
        self.verify_ssl = verify_ssl

        # Remove http:// or https:// if present
        self.host = self.host.replace("http://", "").replace("https://", "")

        self.base_url = f"http://{self.host}"
        self.session_id: Optional[str] = None
        self.csrf_token: Optional[str] = None

        # Detect API version
        self.api_version = self._detect_version()

    def _detect_version(self) -> str:
        """Detect Pi-hole API version (v5 or v6)."""
        try:
            # Try v6 endpoint (no auth required for stats)
            response = requests.get(
                f"{self.base_url}/api/stats/summary",
                timeout=5,
                verify=self.verify_ssl,
            )
            if response.status_code == 200:
                return "v6"
        except:
            pass

        # Fall back to v5
        try:
            response = requests.get(
                f"{self.base_url}/admin/api.php?summary",
                timeout=5,
                verify=self.verify_ssl,
            )
            if response.status_code == 200:
                return "v5"
        except:
            pass

        print(f"Error: Cannot connect to Pi-hole at {self.host}", file=sys.stderr)
        sys.exit(1)

    def _login_v6(self) -> bool:
        """Login to v6 API and get session ID."""
        if not self.password:
            print("Error: PIHOLE_PASSWORD required for authentication", file=sys.stderr)
            sys.exit(1)

        try:
            response = requests.post(
                f"{self.base_url}/api/auth",
                json={"password": self.password},
                timeout=10,
                verify=self.verify_ssl,
            )
            if response.status_code == 200:
                data = response.json()
                session = data.get("session", {})
                self.session_id = session.get("sid")
                self.csrf_token = session.get("csrf")
                return True
            else:
                print(f"Login failed: {response.status_code}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"Login error: {e}", file=sys.stderr)
            return False

    def _request_v6(self, method: str, endpoint: str, data: dict = None, auth: bool = True) -> Any:
        """Make v6 API request."""
        if auth and not self.session_id:
            if not self._login_v6():
                sys.exit(1)

        url = f"{self.base_url}/api{endpoint}"
        headers = {}
        if auth and self.session_id:
            headers["X-FTL-SID"] = self.session_id
        if method != "GET" and self.csrf_token:
            headers["X-FTL-CSRF"] = self.csrf_token

        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                json=data,
                timeout=30,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                # Session expired, retry once
                self.session_id = None
                if auth:
                    self._login_v6()
                    return self._request_v6(method, endpoint, data, auth)
            print(f"Error: {response.status_code} - {response.text}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

    def _request_v5(self, params: dict) -> Any:
        """Make v5 API request."""
        if "auth" not in params and self.api_key:
            params["auth"] = self.api_key

        try:
            response = requests.get(
                f"{self.base_url}/admin/api.php",
                params=params,
                timeout=30,
                verify=self.verify_ssl,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Request error: {e}", file=sys.stderr)
            sys.exit(1)

    # Public API methods
    def get_summary(self) -> dict:
        """Get summary statistics."""
        if self.api_version == "v6":
            return self._request_v6("GET", "/stats/summary", auth=False)
        else:
            return self._request_v5({"summary": ""})

    def get_status(self) -> dict:
        """Get blocking status."""
        if self.api_version == "v6":
            return self._request_v6("GET", "/dns/blocking", auth=False)
        else:
            return self._request_v5({"status": ""})

    def enable_blocking(self) -> dict:
        """Enable blocking."""
        if self.api_version == "v6":
            return self._request_v6("POST", "/dns/blocking", {"blocking": True})
        else:
            return self._request_v5({"enable": ""})

    def disable_blocking(self, duration: int = 0) -> dict:
        """Disable blocking (optionally for duration in seconds)."""
        if self.api_version == "v6":
            data = {"blocking": False}
            if duration > 0:
                data["timer"] = duration
            return self._request_v6("POST", "/dns/blocking", data)
        else:
            params = {"disable": str(duration) if duration > 0 else ""}
            return self._request_v5(params)

    def get_top_domains(self, count: int = 10) -> dict:
        """Get top domains."""
        if self.api_version == "v6":
            return self._request_v6("GET", f"/stats/top_domains?count={count}")
        else:
            return self._request_v5({"topItems": str(count)})

    def get_top_clients(self, count: int = 10) -> dict:
        """Get top clients."""
        if self.api_version == "v6":
            return self._request_v6("GET", f"/stats/top_clients?count={count}")
        else:
            return self._request_v5({"getQuerySources": str(count)})

    def get_queries(self, domain: str = None, client: str = None) -> dict:
        """Get recent queries."""
        if self.api_version == "v6":
            endpoint = "/queries"
            params = []
            if domain:
                params.append(f"domain={domain}")
            if client:
                params.append(f"client={client}")
            if params:
                endpoint += "?" + "&".join(params)
            return self._request_v6("GET", endpoint)
        else:
            return self._request_v5({"getAllQueries": ""})

    def add_to_blocklist(self, domain: str, comment: str = "") -> dict:
        """Add domain to blocklist."""
        if self.api_version == "v6":
            return self._request_v6(
                "POST",
                "/domains",
                {"domain": domain, "kind": "block", "comment": comment},
            )
        else:
            print("Blocklist management requires web interface in v5", file=sys.stderr)
            sys.exit(1)

    def add_to_allowlist(self, domain: str, comment: str = "") -> dict:
        """Add domain to allowlist."""
        if self.api_version == "v6":
            return self._request_v6(
                "POST",
                "/domains",
                {"domain": domain, "kind": "allow", "comment": comment},
            )
        else:
            print("Allowlist management requires web interface in v5", file=sys.stderr)
            sys.exit(1)

    def get_lists(self) -> dict:
        """Get all lists."""
        if self.api_version == "v6":
            return self._request_v6("GET", "/lists")
        else:
            print("List management via API requires v6", file=sys.stderr)
            sys.exit(1)

    def update_gravity(self) -> dict:
        """Update gravity (pull blocklists)."""
        if self.api_version == "v6":
            return self._request_v6("POST", "/gravity")
        else:
            print("Gravity update via API requires v6", file=sys.stderr)
            sys.exit(1)

    def get_info(self) -> dict:
        """Get Pi-hole version and system info."""
        if self.api_version == "v6":
            return self._request_v6("GET", "/info", auth=False)
        else:
            return self._request_v5({"version": ""})


def format_output(data: Any, format_type: str = "table") -> str:
    """Format output for display."""
    if format_type == "json":
        return json.dumps(data, indent=2)

    if isinstance(data, dict):
        # Extract actual data if wrapped
        if "data" in data:
            data = data["data"]

        lines = []
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    return str(data)


def main():
    parser = argparse.ArgumentParser(description="Pi-hole API Client")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--host", help="Pi-hole hostname or IP")
    parser.add_argument("--password", help="Pi-hole password")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Info commands
    subparsers.add_parser("info", help="Pi-hole version and system info")
    subparsers.add_parser("summary", help="Summary statistics")
    subparsers.add_parser("status", help="Blocking status")

    # Blocking control
    subparsers.add_parser("enable", help="Enable blocking")
    disable = subparsers.add_parser("disable", help="Disable blocking")
    disable.add_argument("--duration", type=int, default=0, help="Duration in seconds")

    # Statistics
    top_domains = subparsers.add_parser("top-domains", help="Top domains")
    top_domains.add_argument("--count", type=int, default=10, help="Number of results")

    top_clients = subparsers.add_parser("top-clients", help="Top clients")
    top_clients.add_argument("--count", type=int, default=10, help="Number of results")

    # Queries
    queries = subparsers.add_parser("queries", help="Recent queries")
    queries.add_argument("--domain", help="Filter by domain")
    queries.add_argument("--client", help="Filter by client IP")

    # List management (v6 only)
    block = subparsers.add_parser("block", help="Add domain to blocklist")
    block.add_argument("domain", help="Domain to block")
    block.add_argument("--comment", default="", help="Optional comment")

    allow = subparsers.add_parser("allow", help="Add domain to allowlist")
    allow.add_argument("domain", help="Domain to allow")
    allow.add_argument("--comment", default="", help="Optional comment")

    subparsers.add_parser("lists", help="Show all lists")
    subparsers.add_parser("gravity-update", help="Update gravity (pull blocklists)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize API
    api = PiHoleAPI(host=args.host, password=args.password)
    print(f"Connected to Pi-hole ({api.api_version})", file=sys.stderr)

    output_format = "json" if args.json else "table"
    result = None

    # Execute command
    if args.command == "info":
        result = api.get_info()
    elif args.command == "summary":
        result = api.get_summary()
    elif args.command == "status":
        result = api.get_status()
    elif args.command == "enable":
        result = api.enable_blocking()
        print("Blocking enabled")
        return
    elif args.command == "disable":
        result = api.disable_blocking(args.duration)
        if args.duration > 0:
            print(f"Blocking disabled for {args.duration} seconds")
        else:
            print("Blocking disabled")
        return
    elif args.command == "top-domains":
        result = api.get_top_domains(args.count)
    elif args.command == "top-clients":
        result = api.get_top_clients(args.count)
    elif args.command == "queries":
        result = api.get_queries(domain=args.domain, client=args.client)
    elif args.command == "block":
        result = api.add_to_blocklist(args.domain, args.comment)
        print(f"Added {args.domain} to blocklist")
        return
    elif args.command == "allow":
        result = api.add_to_allowlist(args.domain, args.comment)
        print(f"Added {args.domain} to allowlist")
        return
    elif args.command == "lists":
        result = api.get_lists()
    elif args.command == "gravity-update":
        result = api.update_gravity()
        print("Gravity update initiated")
        return

    if result is not None:
        print(format_output(result, output_format))


if __name__ == "__main__":
    main()
