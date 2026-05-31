#!/usr/bin/env python3
"""
Wake-on-LAN API Client

CLI tool for waking the Gaming PC via Magic Packet
and checking LM Studio availability.

Usage:
    python wol_api.py wake
    python wol_api.py wake --wait
    python wol_api.py status
    python wol_api.py models
    python wol_api.py ping
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

try:
    import requests
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


class WolAPI:
    """Wake-on-LAN and LM Studio client."""

    def __init__(
        self,
        mac: str = None,
        ip: str = None,
        lm_studio_url: str = None,
        wol_timeout: int = None,
    ):
        load_env()

        self.mac = mac or os.environ.get("GAMING_PC_MAC", "")
        self.ip = ip or os.environ.get("GAMING_PC_IP", "")
        try:
            self.wol_timeout = wol_timeout or int(os.environ.get("WOL_TIMEOUT", "360"))
        except ValueError:
            self.wol_timeout = 360

        if lm_studio_url:
            self.lm_studio_url = lm_studio_url
        elif os.environ.get("LM_STUDIO_URL"):
            self.lm_studio_url = os.environ["LM_STUDIO_URL"]
        elif self.ip:
            self.lm_studio_url = f"http://{self.ip}:1234"
        else:
            self.lm_studio_url = None

    def _send_magic_packet(self, mac: str, broadcast: str = None) -> None:
        """Send a Wake-on-LAN magic packet."""
        try:
            mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
        except ValueError:
            raise ValueError(f"Invalid MAC address (non-hex characters): {mac}")
        if len(mac_bytes) != 6:
            raise ValueError(f"Invalid MAC address (wrong length): {mac}")

        magic = b"\xff" * 6 + mac_bytes * 16

        # Determine broadcast address from local network
        if not broadcast:
            broadcast = self._get_subnet_broadcast()

        # Send to BOTH the subnet broadcast and the host's unicast IP. When the
        # sender sits in a different VLAN than the target (Rolly's LXC is on
        # VLAN10 192.168.10.x, the Gaming-PC on VLAN1 192.168.1.x), the gateway
        # does NOT forward a directed broadcast across the subnet — but it DOES
        # route the unicast packet, as long as it can resolve the target's MAC.
        # A DHCP fixed-IP reservation keeps that IP<->MAC binding alive while the
        # PC is off. On the same subnet the broadcast continues to do the job.
        targets = [broadcast]
        if self.ip and self.ip != broadcast:
            targets.append(self.ip)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            # Retransmit on both standard WoL ports: UDP datagrams can be dropped,
            # and some NICs listen on 7 rather than 9. Cheap insurance for a packet
            # that either wakes the PC or harmlessly no-ops if it's already on.
            for _ in range(3):
                for dest in targets:
                    for port in (9, 7):
                        sock.sendto(magic, (dest, port))
        finally:
            sock.close()

    def _get_subnet_broadcast(self) -> str:
        """Get the subnet broadcast address from the default interface."""
        try:
            # Use the IP to determine subnet - assume /24 if we have a target IP
            if self.ip:
                parts = self.ip.split(".")
                return f"{parts[0]}.{parts[1]}.{parts[2]}.255"
        except (IndexError, ValueError):
            pass
        return "255.255.255.255"

    def wake(self, wait: bool = False) -> dict[str, Any]:
        """Send Wake-on-LAN magic packet to Gaming PC.

        Args:
            wait: If True, wait until LM Studio is available

        Returns:
            Status dict with result information
        """
        if not self.mac:
            return {"success": False, "error": "GAMING_PC_MAC not configured in .env"}

        broadcast = self._get_subnet_broadcast()
        try:
            self._send_magic_packet(self.mac, broadcast)
        except (ValueError, OSError, socket.error) as e:
            return {"success": False, "error": f"Failed to send magic packet: {e}"}
        result = {
            "success": True,
            "message": f"Magic Packet gesendet an {self.mac} (Broadcast {broadcast} + Unicast {self.ip}, Ports 9+7, 3x)",
            "mac": self.mac,
        }

        if wait:
            result["lm_studio"] = self._wait_for_lm_studio()

        return result

    def _wait_for_lm_studio(self) -> dict[str, Any]:
        """Poll until LM Studio becomes available or wol_timeout wall-clock
        seconds have elapsed. Wall-clock (time.time()) instead of summing
        poll_interval because each _check_lm_studio() can block up to 5s
        on connect timeout when the PC is still booting — counting only
        the sleeps would let the real wait silently grow to ~2x the
        configured timeout."""
        poll_interval = 5
        start = time.time()

        while True:
            if self._check_lm_studio():
                return {"available": True, "waited_seconds": int(time.time() - start)}
            elapsed = int(time.time() - start)
            if elapsed >= self.wol_timeout:
                return {"available": False, "waited_seconds": elapsed, "timeout": True}
            time.sleep(poll_interval)
            print(f"  Warte auf LM Studio... ({int(time.time() - start)}s/{self.wol_timeout}s)", file=sys.stderr)

    def _check_lm_studio(self) -> bool:
        """Check if LM Studio API is responding."""
        if not self.lm_studio_url:
            return False
        try:
            response = requests.get(f"{self.lm_studio_url}/v1/models", timeout=5)
            return response.status_code == 200
        except (requests.RequestException, ConnectionError):
            return False

    def status(self) -> dict[str, Any]:
        """Check Gaming PC and LM Studio status.

        Returns:
            Status dict with ping and LM Studio availability
        """
        result = {"ip": self.ip, "mac": self.mac}

        # Ping check
        result["ping"] = self._ping()

        # LM Studio check
        if self.lm_studio_url:
            result["lm_studio_url"] = self.lm_studio_url
            result["lm_studio_available"] = self._check_lm_studio()
        else:
            result["lm_studio_available"] = False
            result["lm_studio_error"] = "LM Studio URL not configured"

        return result

    def _ping(self) -> bool:
        """Ping the Gaming PC.

        Note: `ping -W` unit differs by platform:
          - macOS (BSD): milliseconds → "2000" = 2 s
          - Linux: seconds → "2" = 2 s
        """
        if not self.ip:
            return False
        wait_flag = "2000" if sys.platform == "darwin" else "2"
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", wait_flag, self.ip],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def models(self) -> dict[str, Any]:
        """List loaded LM Studio models.

        Returns:
            Dict with models list or error
        """
        if not self.lm_studio_url:
            return {"success": False, "error": "LM Studio URL not configured"}

        try:
            response = requests.get(f"{self.lm_studio_url}/v1/models", timeout=10)
            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                chat_models = [m for m in models if "embed" not in m.get("id", "").lower()]
                embed_models = [m for m in models if "embed" in m.get("id", "").lower()]
                return {
                    "success": True,
                    "chat_models": [m["id"] for m in chat_models],
                    "embedding_models": [m["id"] for m in embed_models],
                    "total": len(models),
                }
            return {"success": False, "error": f"HTTP {response.status_code}"}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}

    def ping(self) -> dict[str, Any]:
        """Simple ping to Gaming PC.

        Returns:
            Dict with ping result
        """
        if not self.ip:
            return {"success": False, "error": "GAMING_PC_IP not configured in .env"}

        reachable = self._ping()
        return {
            "success": True,
            "ip": self.ip,
            "reachable": reachable,
            "message": f"PC {'erreichbar' if reachable else 'nicht erreichbar'} ({self.ip})",
        }


def execute(command: str, args: dict = None) -> Any:
    """Programmatic entry point for other skills/scripts.

    Args:
        command: Command name (wake, status, models, ping)
        args: Optional arguments dict

    Returns:
        Command result as dict
    """
    args = args or {}
    api = WolAPI()

    commands = {
        "wake": lambda: api.wake(wait=args.get("wait", False)),
        "status": lambda: api.status(),
        "models": lambda: api.models(),
        "ping": lambda: api.ping(),
    }

    if command not in commands:
        return {"error": f"Unknown command: {command}. Available: {', '.join(commands)}"}

    return commands[command]()


def main():
    parser = argparse.ArgumentParser(description="Wake-on-LAN & LM Studio Management")
    # Accepted for compatibility with the skill CLI contract (`script --json <command>`).
    # Output is always JSON, so this flag is a no-op — but tolerating it means a
    # caller that passes --json won't crash with an argparse error.
    parser.add_argument("--json", action="store_true", help="Output JSON (always on)")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # wake
    wake_parser = subparsers.add_parser("wake", help="Send Magic Packet to Gaming PC")
    wake_parser.add_argument("--wait", action="store_true", help="Wait until LM Studio is available")

    # status
    subparsers.add_parser("status", help="Check Gaming PC and LM Studio status")

    # models
    subparsers.add_parser("models", help="List loaded LM Studio models")

    # ping
    subparsers.add_parser("ping", help="Ping Gaming PC")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = WolAPI()

    commands = {
        "wake": lambda: api.wake(wait=args.wait if hasattr(args, "wait") else False),
        "status": lambda: api.status(),
        "models": lambda: api.models(),
        "ping": lambda: api.ping(),
    }

    result = commands[args.command]()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
