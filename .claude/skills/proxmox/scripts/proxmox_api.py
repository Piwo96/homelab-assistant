#!/usr/bin/env python3
"""
Proxmox VE API Client

CLI tool for managing Proxmox VMs, containers, and storage.
Uses API token authentication (no CSRF required).

Usage:
    python proxmox_api.py nodes
    python proxmox_api.py vms <node>
    python proxmox_api.py start <node> <vmid>
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

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
        Path(__file__).parent.parent.parent.parent.parent / ".env",  # project root
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


class ProxmoxAPI:
    """Proxmox VE REST API client with token authentication."""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        token_id: str = None,
        token_secret: str = None,
        verify_ssl: bool = None,
    ):
        load_env()

        self.host = host or os.environ.get("PROXMOX_HOST", "192.168.10.140")
        self.port = port or int(os.environ.get("PROXMOX_PORT", "8006"))
        self.token_id = token_id or os.environ.get("PROXMOX_TOKEN_ID")
        self.token_secret = token_secret or os.environ.get("PROXMOX_TOKEN_SECRET")

        verify_env = os.environ.get("PROXMOX_VERIFY_SSL", "false").lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"

        if not self.token_id or not self.token_secret:
            print("Error: PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET required", file=sys.stderr)
            print("Set via environment variables or .env file", file=sys.stderr)
            sys.exit(1)

        self.base_url = f"https://{self.host}:{self.port}/api2/json"
        self.headers = {
            "Authorization": f"PVEAPIToken={self.token_id}={self.token_secret}"
        }

    def _request(self, method: str, endpoint: str, data: dict = None) -> dict:
        """Make API request and return data."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method,
                url,
                headers=self.headers,
                data=data,
                verify=self.verify_ssl,
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("data", {})
        except requests.exceptions.ConnectionError:
            print(f"Error: Cannot connect to {self.host}:{self.port}", file=sys.stderr)
            sys.exit(1)
        except requests.exceptions.HTTPError as e:
            error_msg = response.json().get("errors", str(e))
            print(f"Error: {response.status_code} - {error_msg}", file=sys.stderr)
            sys.exit(1)

    def get(self, endpoint: str) -> Any:
        return self._request("GET", endpoint)

    def post(self, endpoint: str, data: dict = None) -> Any:
        return self._request("POST", endpoint, data)

    def put(self, endpoint: str, data: dict = None) -> Any:
        return self._request("PUT", endpoint, data)

    def delete(self, endpoint: str) -> Any:
        return self._request("DELETE", endpoint)

    # Node operations
    def get_nodes(self) -> list:
        """Get all cluster nodes."""
        return self.get("/nodes")

    def get_node_status(self, node: str) -> dict:
        """Get node status (CPU, RAM, uptime)."""
        return self.get(f"/nodes/{node}/status")

    # VM operations
    def get_vms(self, node: str) -> list:
        """Get all VMs on a node."""
        return self.get(f"/nodes/{node}/qemu")

    def get_vm_status(self, node: str, vmid: int) -> dict:
        """Get VM status."""
        return self.get(f"/nodes/{node}/qemu/{vmid}/status/current")

    def get_vm_config(self, node: str, vmid: int) -> dict:
        """Get VM configuration."""
        return self.get(f"/nodes/{node}/qemu/{vmid}/config")

    def vm_action(self, node: str, vmid: int, action: str) -> dict:
        """Execute VM action (start, stop, shutdown, reboot)."""
        return self.post(f"/nodes/{node}/qemu/{vmid}/status/{action}")

    # Container operations
    def get_containers(self, node: str) -> list:
        """Get all LXC containers on a node."""
        return self.get(f"/nodes/{node}/lxc")

    def get_container_status(self, node: str, vmid: int) -> dict:
        """Get container status."""
        return self.get(f"/nodes/{node}/lxc/{vmid}/status/current")

    def get_container_config(self, node: str, vmid: int) -> dict:
        """Get container configuration (includes mount points)."""
        return self.get(f"/nodes/{node}/lxc/{vmid}/config")

    def container_action(self, node: str, vmid: int, action: str) -> dict:
        """Execute container action (start, stop, shutdown, reboot)."""
        return self.post(f"/nodes/{node}/lxc/{vmid}/status/{action}")

    def update_container_config(self, node: str, vmid: int, config: dict) -> dict:
        """Update container configuration."""
        return self.put(f"/nodes/{node}/lxc/{vmid}/config", config)

    # Storage operations
    def get_storage(self, node: str = None) -> list:
        """Get storage list (cluster-wide or per-node)."""
        if node:
            return self.get(f"/nodes/{node}/storage")
        return self.get("/storage")

    def get_storage_status(self, node: str, storage: str) -> dict:
        """Get storage status."""
        return self.get(f"/nodes/{node}/storage/{storage}/status")

    def get_storage_content(self, node: str, storage: str) -> list:
        """Get storage content."""
        return self.get(f"/nodes/{node}/storage/{storage}/content")

    # Mount operations
    def add_mount_to_lxc(
        self,
        node: str,
        vmid: int,
        mp_id: int,
        source: str,
        target: str,
        readonly: bool = False,
    ) -> dict:
        """Add bind mount to LXC container."""
        ro = ",ro=1" if readonly else ""
        config = {f"mp{mp_id}": f"{source},mp={target}{ro}"}
        return self.update_container_config(node, vmid, config)

    def remove_mount_from_lxc(self, node: str, vmid: int, mp_id: int) -> dict:
        """Remove mount from LXC container."""
        config = {f"delete": f"mp{mp_id}"}
        return self.update_container_config(node, vmid, config)

    # Snapshot operations
    def get_snapshots(self, node: str, vmid: int, vm_type: str = "qemu") -> list:
        """Get snapshots for VM or container."""
        return self.get(f"/nodes/{node}/{vm_type}/{vmid}/snapshot")

    def create_snapshot(
        self, node: str, vmid: int, name: str, vm_type: str = "qemu"
    ) -> dict:
        """Create snapshot."""
        return self.post(f"/nodes/{node}/{vm_type}/{vmid}/snapshot", {"snapname": name})

    def rollback_snapshot(
        self, node: str, vmid: int, name: str, vm_type: str = "qemu"
    ) -> dict:
        """Rollback to snapshot."""
        return self.post(f"/nodes/{node}/{vm_type}/{vmid}/snapshot/{name}/rollback")


def format_output(data: Any, format_type: str = "table") -> str:
    """Format output for display."""
    if format_type == "json":
        return json.dumps(data, indent=2)

    if isinstance(data, list):
        if not data:
            return "No results"
        if isinstance(data[0], dict):
            # Table format for list of dicts
            keys = list(data[0].keys())
            lines = ["\t".join(keys)]
            for item in data:
                lines.append("\t".join(str(item.get(k, "")) for k in keys))
            return "\n".join(lines)
    elif isinstance(data, dict):
        lines = []
        for k, v in data.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    return str(data)


def main():
    parser = argparse.ArgumentParser(description="Proxmox VE API Client")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Node commands
    subparsers.add_parser("nodes", help="List all nodes")

    node_status = subparsers.add_parser("node-status", help="Get node status")
    node_status.add_argument("node", help="Node name")

    # VM commands
    vms = subparsers.add_parser("vms", help="List VMs on node")
    vms.add_argument("node", help="Node name")
    vms.add_argument("--ids-only", action="store_true", help="Output only VMIDs")

    # Container commands
    containers = subparsers.add_parser("containers", help="List containers on node")
    containers.add_argument("node", help="Node name")
    containers.add_argument("--ids-only", action="store_true", help="Output only VMIDs")

    # Status command
    status = subparsers.add_parser("status", help="Get VM/container status")
    status.add_argument("node", help="Node name")
    status.add_argument("vmid", type=int, help="VM/Container ID")

    # Action commands (explicit for skill loader compatibility)
    start_cmd = subparsers.add_parser("start", help="Start VM or container")
    start_cmd.add_argument("node", help="Node name")
    start_cmd.add_argument("vmid", type=int, help="VM/Container ID")

    stop_cmd = subparsers.add_parser("stop", help="Stop VM or container (hard)")
    stop_cmd.add_argument("node", help="Node name")
    stop_cmd.add_argument("vmid", type=int, help="VM/Container ID")

    shutdown_cmd = subparsers.add_parser("shutdown", help="Shutdown VM or container (graceful)")
    shutdown_cmd.add_argument("node", help="Node name")
    shutdown_cmd.add_argument("vmid", type=int, help="VM/Container ID")

    reboot_cmd = subparsers.add_parser("reboot", help="Reboot VM or container")
    reboot_cmd.add_argument("node", help="Node name")
    reboot_cmd.add_argument("vmid", type=int, help="VM/Container ID")

    # Storage commands
    storage = subparsers.add_parser("storage", help="List storage")
    storage.add_argument("node", nargs="?", help="Node name (optional)")

    storage_info = subparsers.add_parser("storage-info", help="Get storage info")
    storage_info.add_argument("node", help="Node name")
    storage_info.add_argument("storage", help="Storage name")

    # LXC config
    lxc_config = subparsers.add_parser("lxc-config", help="Get LXC container config")
    lxc_config.add_argument("node", help="Node name")
    lxc_config.add_argument("vmid", type=int, help="Container ID")

    # Mount commands
    add_mount = subparsers.add_parser("add-mount", help="Add mount to LXC")
    add_mount.add_argument("node", help="Node name")
    add_mount.add_argument("vmid", type=int, help="Container ID")
    add_mount.add_argument("--mp", type=int, required=True, help="Mount point ID (0-9)")
    add_mount.add_argument("--source", required=True, help="Source path on host")
    add_mount.add_argument("--target", required=True, help="Target path in container")
    add_mount.add_argument("--readonly", action="store_true", help="Mount as read-only")

    remove_mount = subparsers.add_parser("remove-mount", help="Remove mount from LXC")
    remove_mount.add_argument("node", help="Node name")
    remove_mount.add_argument("vmid", type=int, help="Container ID")
    remove_mount.add_argument("--mp", type=int, required=True, help="Mount point ID")

    # Snapshot commands
    snapshots = subparsers.add_parser("snapshots", help="List snapshots")
    snapshots.add_argument("node", help="Node name")
    snapshots.add_argument("vmid", type=int, help="VM/Container ID")
    snapshots.add_argument("--lxc", action="store_true", help="Target is LXC container")

    snapshot = subparsers.add_parser("snapshot", help="Create snapshot")
    snapshot.add_argument("node", help="Node name")
    snapshot.add_argument("vmid", type=int, help="VM/Container ID")
    snapshot.add_argument("--name", required=True, help="Snapshot name")
    snapshot.add_argument("--lxc", action="store_true", help="Target is LXC container")

    rollback = subparsers.add_parser("rollback", help="Rollback to snapshot")
    rollback.add_argument("node", help="Node name")
    rollback.add_argument("vmid", type=int, help="VM/Container ID")
    rollback.add_argument("--name", required=True, help="Snapshot name")
    rollback.add_argument("--lxc", action="store_true", help="Target is LXC container")

    # Overview
    overview = subparsers.add_parser("overview", help="Show node overview")
    overview.add_argument("node", help="Node name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = ProxmoxAPI()
    output_format = "json" if args.json else "table"
    result = None

    # Execute command
    if args.command == "nodes":
        result = api.get_nodes()
    elif args.command == "node-status":
        result = api.get_node_status(args.node)
    elif args.command == "vms":
        vms = api.get_vms(args.node)
        if args.ids_only:
            print("\n".join(str(vm["vmid"]) for vm in vms))
            return
        result = vms
    elif args.command == "containers":
        containers = api.get_containers(args.node)
        if args.ids_only:
            print("\n".join(str(c["vmid"]) for c in containers))
            return
        result = containers
    elif args.command == "status":
        # Try VM first, then container
        try:
            result = api.get_vm_status(args.node, args.vmid)
        except SystemExit:
            result = api.get_container_status(args.node, args.vmid)
    elif args.command in ["start", "stop", "shutdown", "reboot"]:
        # Try VM first, then container
        try:
            result = api.vm_action(args.node, args.vmid, args.command)
            print(f"VM {args.vmid}: {args.command} initiated")
        except SystemExit:
            result = api.container_action(args.node, args.vmid, args.command)
            print(f"Container {args.vmid}: {args.command} initiated")
        return
    elif args.command == "storage":
        result = api.get_storage(args.node)
    elif args.command == "storage-info":
        result = api.get_storage_status(args.node, args.storage)
    elif args.command == "lxc-config":
        result = api.get_container_config(args.node, args.vmid)
    elif args.command == "add-mount":
        result = api.add_mount_to_lxc(
            args.node, args.vmid, args.mp, args.source, args.target, args.readonly
        )
        print(f"Mount mp{args.mp} added to container {args.vmid}")
        return
    elif args.command == "remove-mount":
        result = api.remove_mount_from_lxc(args.node, args.vmid, args.mp)
        print(f"Mount mp{args.mp} removed from container {args.vmid}")
        return
    elif args.command == "snapshots":
        vm_type = "lxc" if args.lxc else "qemu"
        result = api.get_snapshots(args.node, args.vmid, vm_type)
    elif args.command == "snapshot":
        vm_type = "lxc" if args.lxc else "qemu"
        result = api.create_snapshot(args.node, args.vmid, args.name, vm_type)
        print(f"Snapshot '{args.name}' created")
        return
    elif args.command == "rollback":
        vm_type = "lxc" if args.lxc else "qemu"
        result = api.rollback_snapshot(args.node, args.vmid, args.name, vm_type)
        print(f"Rolled back to snapshot '{args.name}'")
        return
    elif args.command == "overview":
        node_status = api.get_node_status(args.node)
        vms = api.get_vms(args.node)
        containers = api.get_containers(args.node)
        storage = api.get_storage(args.node)

        print(f"=== Node: {args.node} ===")
        print(f"CPU: {node_status.get('cpu', 0) * 100:.1f}%")
        print(f"RAM: {node_status.get('memory', {}).get('used', 0) / 1024**3:.1f} GB / {node_status.get('memory', {}).get('total', 0) / 1024**3:.1f} GB")
        print(f"Uptime: {node_status.get('uptime', 0) // 86400} days")
        print(f"\nVMs: {len(vms)}")
        for vm in vms:
            status_icon = "●" if vm.get("status") == "running" else "○"
            print(f"  {status_icon} {vm['vmid']}: {vm.get('name', 'unnamed')}")
        print(f"\nContainers: {len(containers)}")
        for ct in containers:
            status_icon = "●" if ct.get("status") == "running" else "○"
            print(f"  {status_icon} {ct['vmid']}: {ct.get('name', 'unnamed')}")
        print(f"\nStorage: {len(storage)}")
        for st in storage:
            print(f"  - {st['storage']}: {st.get('type', 'unknown')}")
        return

    if result is not None:
        print(format_output(result, output_format))


if __name__ == "__main__":
    main()
