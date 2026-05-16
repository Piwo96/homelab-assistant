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
import time
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
            raise RuntimeError("PROXMOX_TOKEN_ID and PROXMOX_TOKEN_SECRET required")

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
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(f"Cannot connect to {self.host}:{self.port}") from e
        except requests.exceptions.HTTPError as e:
            try:
                error_msg = response.json().get("errors", str(e))
            except Exception:
                error_msg = str(e)
            raise RuntimeError(f"API error: {response.status_code} - {error_msg}") from e

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

    def get_default_node(self) -> str:
        """Get the default node name (first/only node in cluster).

        Returns:
            Node name string

        Raises:
            SystemExit if no nodes found
        """
        nodes = self.get_nodes()
        if not nodes:
            raise RuntimeError("No nodes found in cluster")
        # Return first node (usually the only one in single-node setups)
        return nodes[0].get("node")

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

    def list_templates(self, node: str, storage: str = "local") -> list:
        """List container templates (vztmpl) available on a storage.

        Returns list of dicts with keys: volid, format, size.
        Only vztmpl content is returned (ISO and backups filtered out).
        """
        # Proxmox content filter: ?content=vztmpl (server-side).
        # Also filter client-side as a safety net in case the server
        # returns unfiltered content (older Proxmox / proxied responses).
        items = self.get(f"/nodes/{node}/storage/{storage}/content?content=vztmpl")
        if not isinstance(items, list):
            return []
        return [
            it for it in items
            if str(it.get("volid", "")).startswith(f"{storage}:vztmpl/")
        ]

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

    # Task operations
    def wait_task(self, node: str, upid: str, interval: float = 2.0,
                  timeout: float = 600.0) -> dict:
        """Poll a Proxmox task UPID until terminal state.

        Args:
            node: cluster node name.
            upid: task identifier returned by an async API call.
            interval: seconds between polls.
            timeout: max total wait in seconds.

        Returns:
            { "exitstatus": "OK", ... } on success.

        Raises:
            RuntimeError: task finished with non-OK exitstatus.
            TimeoutError: task still running after `timeout` seconds.
        """
        deadline = time.monotonic() + timeout
        endpoint = f"/nodes/{node}/tasks/{upid}/status"
        while True:
            status = self.get(endpoint)
            if status.get("status") == "stopped":
                exit_status = status.get("exitstatus", "")
                if exit_status != "OK":
                    raise RuntimeError(f"Task {upid} failed: {exit_status}")
                return status
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Task {upid} did not finish within {timeout}s")
            time.sleep(interval)

    def get_next_vmid(self) -> int:
        """Ask Proxmox for the next free VMID (cluster-wide)."""
        result = self.get("/cluster/nextid")
        # Proxmox returns the id as a string
        return int(result)

    def create_lxc(self, node: str, vmid, ostemplate: str, hostname: str,
                   cores: int, memory: int, disk_gb: int, storage: str,
                   bridge: str, ip_cidr: str, gateway: str = None,
                   ssh_public_keys: str = "", unprivileged: bool = True,
                   start: bool = True, nameserver: str = None,
                   wait: bool = True, timeout: float = 600.0) -> dict:
        """Create an LXC container.

        vmid can be int or 'auto' to use /cluster/nextid.
        Returns: { vmid, upid, exitstatus } (exitstatus omitted if wait=False).
        Raises RuntimeError on task failure, TimeoutError on wait timeout.
        """
        if vmid == "auto":
            vmid = self.get_next_vmid()
        vmid = int(vmid)

        net0_parts = [f"name=eth0", f"bridge={bridge}", f"ip={ip_cidr}"]
        if gateway and ip_cidr != "dhcp":
            net0_parts.append(f"gw={gateway}")

        body = {
            "vmid": vmid,
            "ostemplate": ostemplate,
            "hostname": hostname,
            "cores": cores,
            "memory": memory,
            "rootfs": f"{storage}:{disk_gb}",
            "net0": ",".join(net0_parts),
            "unprivileged": 1 if unprivileged else 0,
            "start": 1 if start else 0,
            "onboot": 1,
        }
        if ssh_public_keys:
            body["ssh-public-keys"] = ssh_public_keys
        if nameserver:
            body["nameserver"] = nameserver

        upid = self.post(f"/nodes/{node}/lxc", body)
        result = {"vmid": vmid, "upid": upid}
        if wait:
            status = self.wait_task(node, upid, timeout=timeout)
            result["exitstatus"] = status.get("exitstatus")
        return result

    def delete_lxc(self, node: str, vmid: int, force: bool = False,
                   timeout: float = 120.0) -> dict:
        """Shutdown then destroy an LXC container.

        Args:
            node: cluster node.
            vmid: container ID.
            force: if True, hard-stop instead of graceful shutdown when running.
            timeout: max wait per phase (shutdown, destroy).
        """
        status = self.get(f"/nodes/{node}/lxc/{vmid}/status/current")
        if status.get("status") == "running":
            stop_action = "stop" if force else "shutdown"
            upid = self.post(f"/nodes/{node}/lxc/{vmid}/status/{stop_action}")
            self.wait_task(node, upid, timeout=timeout)

        destroy_upid = self.delete(f"/nodes/{node}/lxc/{vmid}")
        self.wait_task(node, destroy_upid, timeout=timeout)
        return {"vmid": vmid, "deleted": True}


def execute(action: str, args: dict) -> Any:
    """Execute a Proxmox action directly (no CLI).

    Args:
        action: Command name (e.g. "vms", "start", "containers")
        args: Dict of arguments (e.g. {"vmid": 100, "node": "pve"})

    Returns:
        Raw Python data (dict/list)

    Raises:
        ValueError: Unknown action
        KeyError: Missing required argument
    """
    api = ProxmoxAPI()

    # Auto-detect node for commands that support it
    node_optional_actions = {
        "node-status", "vms", "containers", "overview",
        "start", "stop", "shutdown", "reboot",
    }
    if action in node_optional_actions:
        node = args.get("node")
        if not node:
            node = api.get_default_node()
        else:
            valid_nodes = [n.get("node") for n in api.get_nodes()]
            if node not in valid_nodes:
                node = api.get_default_node()
        args = {**args, "node": node}

    if action == "nodes":
        return api.get_nodes()
    elif action == "node-status":
        return api.get_node_status(args["node"])
    elif action == "vms":
        return api.get_vms(args["node"])
    elif action == "containers":
        return api.get_containers(args["node"])
    elif action == "status":
        # Try VM first, then container
        try:
            return api.get_vm_status(args["node"], int(args["vmid"]))
        except RuntimeError:
            return api.get_container_status(args["node"], int(args["vmid"]))
    elif action in ("start", "stop", "shutdown", "reboot"):
        vmid = int(args["vmid"])
        # Try VM first, then container
        try:
            return api.vm_action(args["node"], vmid, action)
        except RuntimeError:
            return api.container_action(args["node"], vmid, action)
    elif action == "storage":
        return api.get_storage(args.get("node"))
    elif action == "storage-info":
        return api.get_storage_status(args["node"], args["storage"])
    elif action == "lxc-config":
        return api.get_container_config(args["node"], int(args["vmid"]))
    elif action == "add-mount":
        return api.add_mount_to_lxc(
            args["node"], int(args["vmid"]), int(args["mp"]),
            args["source"], args["target"], args.get("readonly", False),
        )
    elif action == "remove-mount":
        return api.remove_mount_from_lxc(
            args["node"], int(args["vmid"]), int(args["mp"]),
        )
    elif action == "snapshots":
        vm_type = "lxc" if args.get("lxc") else "qemu"
        return api.get_snapshots(args["node"], int(args["vmid"]), vm_type)
    elif action == "snapshot":
        vm_type = "lxc" if args.get("lxc") else "qemu"
        return api.create_snapshot(args["node"], int(args["vmid"]), args["name"], vm_type)
    elif action == "rollback":
        vm_type = "lxc" if args.get("lxc") else "qemu"
        return api.rollback_snapshot(args["node"], int(args["vmid"]), args["name"], vm_type)
    elif action == "overview":
        node = args["node"]
        return {
            "node": node,
            "status": api.get_node_status(node),
            "vms": api.get_vms(node),
            "containers": api.get_containers(node),
            "storage": api.get_storage(node),
        }
    elif action == "templates":
        return api.list_templates(args["node"], args.get("storage", "local"))
    elif action == "wait-task":
        return api.wait_task(args["node"], args["upid"],
                             interval=float(args.get("interval", 2.0)),
                             timeout=float(args.get("timeout", 600.0)))
    elif action == "create-lxc":
        return api.create_lxc(
            node=args["node"],
            vmid=args.get("vmid", "auto"),
            ostemplate=args["template"],
            hostname=args["hostname"],
            cores=int(args.get("cores", 2)),
            memory=int(args.get("memory", 1024)),
            disk_gb=int(args.get("disk", 10)),
            storage=args.get("storage", "local-lvm"),
            bridge=args.get("bridge", "vmbr0"),
            ip_cidr=args.get("ip", "dhcp"),
            gateway=args.get("gateway"),
            ssh_public_keys=args.get("ssh_key", ""),
            unprivileged=bool(args.get("unprivileged", True)),
            start=bool(args.get("start", True)),
            nameserver=args.get("nameserver"),
            timeout=float(args.get("timeout", 600.0)),
        )
    elif action == "delete-lxc":
        return api.delete_lxc(args["node"], int(args["vmid"]),
                              force=bool(args.get("force", False)),
                              timeout=float(args.get("timeout", 120.0)))
    else:
        raise ValueError(f"Unknown action: {action}")


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
    node_status.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

    # VM commands
    vms = subparsers.add_parser("vms", help="List VMs on node")
    vms.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")
    vms.add_argument("--ids-only", action="store_true", help="Output only VMIDs")

    # Container commands
    containers = subparsers.add_parser("containers", help="List containers on node")
    containers.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")
    containers.add_argument("--ids-only", action="store_true", help="Output only VMIDs")

    # Status command
    status = subparsers.add_parser("status", help="Get VM/container status")
    status.add_argument("node", help="Node name")
    status.add_argument("vmid", type=int, help="VM/Container ID")

    # Action commands (vmid first, node optional with auto-detection)
    start_cmd = subparsers.add_parser("start", help="Start VM or container")
    start_cmd.add_argument("vmid", type=int, help="VM/Container ID")
    start_cmd.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

    stop_cmd = subparsers.add_parser("stop", help="Stop VM or container (hard)")
    stop_cmd.add_argument("vmid", type=int, help="VM/Container ID")
    stop_cmd.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

    shutdown_cmd = subparsers.add_parser("shutdown", help="Shutdown VM or container (graceful)")
    shutdown_cmd.add_argument("vmid", type=int, help="VM/Container ID")
    shutdown_cmd.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

    reboot_cmd = subparsers.add_parser("reboot", help="Reboot VM or container")
    reboot_cmd.add_argument("vmid", type=int, help="VM/Container ID")
    reboot_cmd.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

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
    overview.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")

    # Templates
    templates = subparsers.add_parser("templates", help="List LXC templates on storage")
    templates.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")
    templates.add_argument("--storage", default="local", help="Storage name (default: local)")

    # Wait for task
    wait_task = subparsers.add_parser("wait-task", help="Poll a Proxmox task until done")
    wait_task.add_argument("upid", help="Task UPID returned by an async call")
    wait_task.add_argument("--node", help="Node name (auto-detected if omitted)")
    wait_task.add_argument("--interval", type=float, default=2.0, help="Poll interval seconds")
    wait_task.add_argument("--timeout", type=float, default=600.0, help="Max wait seconds")

    # Create LXC
    create_lxc = subparsers.add_parser("create-lxc", help="Create an LXC container")
    create_lxc.add_argument("--node", help="Node name (auto-detected if omitted)")
    create_lxc.add_argument("--vmid", default="auto",
                            help="VMID or 'auto' (default: auto, queries /cluster/nextid)")
    create_lxc.add_argument("--hostname", required=True, help="Container hostname")
    create_lxc.add_argument("--template", required=True,
                            help="ostemplate volid (e.g. local:vztmpl/debian-12-...)")
    create_lxc.add_argument("--cores", type=int, default=2, help="vCPU cores")
    create_lxc.add_argument("--memory", type=int, default=1024, help="RAM in MB")
    create_lxc.add_argument("--disk", type=int, default=10, help="Rootfs size in GB")
    create_lxc.add_argument("--storage", default="local-lvm", help="Rootfs storage")
    create_lxc.add_argument("--bridge", default="vmbr0", help="Network bridge")
    create_lxc.add_argument("--ip", default="dhcp",
                            help="IP/CIDR (e.g. 192.168.10.200/24) or 'dhcp'")
    create_lxc.add_argument("--gateway", help="Default gateway (required for static IP)")
    create_lxc.add_argument("--ssh-key", dest="ssh_key", default="",
                            help="SSH public key text (entire ssh-... line)")
    create_lxc.add_argument("--unprivileged", action="store_true", default=True)
    create_lxc.add_argument("--privileged", dest="unprivileged", action="store_false")
    create_lxc.add_argument("--start", action="store_true", default=True)
    create_lxc.add_argument("--no-start", dest="start", action="store_false")
    create_lxc.add_argument("--nameserver", help="DNS server inside container")
    create_lxc.add_argument("--timeout", type=float, default=600.0,
                            help="Max wait seconds for the create task")

    # Delete LXC
    delete_lxc = subparsers.add_parser("delete-lxc", help="Stop and destroy an LXC")
    delete_lxc.add_argument("vmid", type=int, help="Container ID")
    delete_lxc.add_argument("--node", help="Node name (auto-detected)")
    delete_lxc.add_argument("--force", action="store_true",
                            help="Hard-stop instead of graceful shutdown")
    delete_lxc.add_argument("--timeout", type=float, default=120.0)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    api = ProxmoxAPI()
    output_format = "json" if args.json else "table"
    result = None

    # Auto-detect node for commands that support it
    commands_with_optional_node = ["node-status", "vms", "containers", "overview",
                                    "start", "stop", "shutdown", "reboot", "templates",
                                    "wait-task", "create-lxc", "delete-lxc"]
    if args.command in commands_with_optional_node:
        provided_node = getattr(args, "node", None)
        if not provided_node:
            # No node provided - auto-detect
            args.node = api.get_default_node()
        else:
            # Node provided - validate it exists
            valid_nodes = [n.get("node") for n in api.get_nodes()]
            if provided_node not in valid_nodes:
                # Invalid node name (e.g., "pve" when actual is "pve-rollmann")
                # Fall back to auto-detection
                args.node = api.get_default_node()

    # Execute command
    if args.command == "nodes":
        nodes = api.get_nodes()
        if args.json:
            result = nodes
        else:
            print("🖥️ **Proxmox Nodes**\n")
            for node in nodes:
                name = node.get("node", "?")
                status = node.get("status", "unknown")
                icon = "🟢" if status == "online" else "🔴"
                cpu = node.get("cpu", 0) * 100
                mem_used = node.get("mem", 0) / (1024**3)
                mem_total = node.get("maxmem", 0) / (1024**3)
                print(f"{icon} **{name}**")
                print(f"   CPU: {cpu:.1f}%")
                print(f"   RAM: {mem_used:.1f} GB / {mem_total:.1f} GB")
                print()
            return

    elif args.command == "node-status":
        status = api.get_node_status(args.node)
        if args.json:
            result = status
        else:
            cpu = status.get("cpu", 0) * 100
            mem = status.get("memory", {})
            mem_used = mem.get("used", 0) / (1024**3)
            mem_total = mem.get("total", 0) / (1024**3)
            uptime_days = status.get("uptime", 0) // 86400

            print(f"🖥️ **Node: {args.node}**\n")
            print(f"   CPU: {cpu:.1f}%")
            print(f"   RAM: {mem_used:.1f} GB / {mem_total:.1f} GB")
            print(f"   Uptime: {uptime_days} Tage")
            return

    elif args.command == "vms":
        vms = api.get_vms(args.node)
        if args.ids_only:
            print("\n".join(str(vm["vmid"]) for vm in vms))
            return
        if args.json:
            result = vms
        else:
            if not vms:
                print("Keine VMs gefunden.")
                return
            print(f"💻 **VMs auf {args.node}** ({len(vms)} Geräte)\n")
            for vm in vms:
                vmid = vm.get("vmid", "?")
                name = vm.get("name", "unnamed")
                status = vm.get("status", "unknown")
                icon = "🟢" if status == "running" else "⚫"
                cpu = vm.get("cpu", 0) * 100
                mem_used = vm.get("mem", 0) / (1024**3)
                mem_max = vm.get("maxmem", 0) / (1024**3)

                print(f"{icon} **{vmid}: {name}**")
                if status == "running":
                    print(f"   CPU: {cpu:.1f}% | RAM: {mem_used:.1f}/{mem_max:.1f} GB")
                print()
            return

    elif args.command == "containers":
        containers = api.get_containers(args.node)
        if args.ids_only:
            print("\n".join(str(c["vmid"]) for c in containers))
            return
        if args.json:
            result = containers
        else:
            if not containers:
                print("Keine Container gefunden.")
                return
            print(f"📦 **Container auf {args.node}** ({len(containers)} Geräte)\n")
            for ct in containers:
                vmid = ct.get("vmid", "?")
                name = ct.get("name", "unnamed")
                status = ct.get("status", "unknown")
                icon = "🟢" if status == "running" else "⚫"
                cpu = ct.get("cpu", 0) * 100
                mem_used = ct.get("mem", 0) / (1024**3)
                mem_max = ct.get("maxmem", 0) / (1024**3)

                print(f"{icon} **{vmid}: {name}**")
                if status == "running":
                    print(f"   CPU: {cpu:.1f}% | RAM: {mem_used:.1f}/{mem_max:.1f} GB")
                print()
            return

    elif args.command == "status":
        # Try VM first, then container
        try:
            status = api.get_vm_status(args.node, args.vmid)
            vm_type = "VM"
        except RuntimeError:
            status = api.get_container_status(args.node, args.vmid)
            vm_type = "Container"

        if args.json:
            result = status
        else:
            state = status.get("status", "unknown")
            icon = "🟢" if state == "running" else "⚫"
            name = status.get("name", "unnamed")
            cpu = status.get("cpu", 0) * 100
            mem_used = status.get("mem", 0) / (1024**3)
            mem_max = status.get("maxmem", 0) / (1024**3)
            uptime = status.get("uptime", 0) // 3600

            print(f"{icon} **{vm_type} {args.vmid}: {name}**\n")
            print(f"   Status: {state}")
            if state == "running":
                print(f"   CPU: {cpu:.1f}%")
                print(f"   RAM: {mem_used:.1f} GB / {mem_max:.1f} GB")
                print(f"   Uptime: {uptime} Stunden")
            return
    elif args.command in ["start", "stop", "shutdown", "reboot"]:
        # Try VM first, then container
        try:
            result = api.vm_action(args.node, args.vmid, args.command)
            print(f"VM {args.vmid}: {args.command} initiated")
        except RuntimeError:
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
    elif args.command == "templates":
        result = execute("templates", {"node": args.node, "storage": args.storage})
    elif args.command == "wait-task":
        result = execute("wait-task", {"node": args.node, "upid": args.upid,
                                        "interval": args.interval, "timeout": args.timeout})
    elif args.command == "create-lxc":
        result = execute("create-lxc", {
            "node": args.node, "vmid": args.vmid, "hostname": args.hostname,
            "template": args.template, "cores": args.cores, "memory": args.memory,
            "disk": args.disk, "storage": args.storage, "bridge": args.bridge,
            "ip": args.ip, "gateway": args.gateway, "ssh_key": args.ssh_key,
            "unprivileged": args.unprivileged, "start": args.start,
            "nameserver": args.nameserver, "timeout": args.timeout,
        })
    elif args.command == "delete-lxc":
        result = execute("delete-lxc", {"node": args.node, "vmid": args.vmid,
                                         "force": args.force, "timeout": args.timeout})

    if result is not None:
        print(format_output(result, output_format))


if __name__ == "__main__":
    main()
