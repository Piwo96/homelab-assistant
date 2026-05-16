# Rolly Proxmox Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy Rolly (the Bun/TypeScript Telegram-Agent) to a freshly provisioned LXC on the local Proxmox host, publicly reachable via DuckDNS + Caddy + Let's Encrypt (DNS-01), with all provisioning driven by an idempotent `./deploy.sh`.

**Architecture:** Extend the existing `proxmox` skill with four new actions (`templates`, `wait-task`, `create-lxc`, `delete-lxc`) so LXC lifecycle is a first-class skill capability. Then build a Rolly-specific `infra/rolly/` directory containing a Mac-side `deploy.sh` (which calls the skill and SCPs/SSHes setup artifacts into the LXC) and an in-LXC `setup-lxc.sh` (which installs Bun, Caddy, the agent code, and systemd units). Public endpoint is `https://sophia-und-philipp.duckdns.org:8443/webhook`.

**Tech Stack:** Python 3.13 (skill extension), `requests` (existing), `pytest` + `unittest.mock` (new tests), Bash 5+ (deploy scripts), Caddy 2.7+ with `caddy-dns/duckdns` plugin, systemd, Debian 12 LXC template.

**Spec:** [docs/superpowers/specs/2026-05-16-rolly-proxmox-deploy-design.md](../specs/2026-05-16-rolly-proxmox-deploy-design.md)

---

## File Structure

```
.claude/skills/proxmox/
├── SKILL.md                                  # MODIFY: document new actions
└── scripts/
    ├── proxmox_api.py                        # MODIFY: +templates +wait_task +create_lxc +delete_lxc
    └── test_proxmox_api.py                   # NEW: pytest tests for new actions

infra/rolly/                                  # NEW directory
├── deploy.sh                                 # NEW: Mac-side orchestrator
├── setup-lxc.sh                              # NEW: runs inside LXC
├── config.env.example                        # NEW: template for user secrets
├── Caddyfile.tmpl                            # NEW: envsubst template
├── rolly.service.tmpl                        # NEW: systemd unit template
├── caddy.service                             # NEW: static systemd unit
└── README.md                                 # NEW: manual steps + troubleshooting

.gitignore                                    # MODIFY: +infra/rolly/config.env
requirements.txt                              # MODIFY: +pytest (dev) for the new tests
```

**Boundary recap:** `deploy.sh` only calls `proxmox_api.py` via CLI — never imports Python. `setup-lxc.sh` runs inside the LXC and knows nothing about Proxmox. Each file has one responsibility.

---

## Task 1: Add pytest as a dev dependency and bootstrap the test file

**Files:**
- Modify: `requirements.txt`
- Create: `.claude/skills/proxmox/scripts/test_proxmox_api.py`

- [ ] **Step 1: Append pytest to requirements.txt**

Add this line under a new `# === Dev dependencies ===` heading at the bottom of `requirements.txt`:

```
# === Dev dependencies ===
pytest>=8.0.0
```

- [ ] **Step 2: Install the new dep locally**

Run: `pip install pytest>=8.0.0`
Expected: pytest 8.x installed (already-installed message is fine).

- [ ] **Step 3: Create test file with one smoke test against an existing method**

Create `.claude/skills/proxmox/scripts/test_proxmox_api.py`:

```python
"""Tests for proxmox_api.py — uses unittest.mock to patch requests.request.

Run with: pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the script importable as a module
sys.path.insert(0, str(Path(__file__).parent))
import proxmox_api  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Provide dummy credentials so ProxmoxAPI() doesn't fail at import."""
    monkeypatch.setenv("PROXMOX_HOST", "test-host")
    monkeypatch.setenv("PROXMOX_PORT", "8006")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "root@pam!test")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "00000000-0000-0000-0000-000000000000")
    monkeypatch.setenv("PROXMOX_VERIFY_SSL", "false")


def _mock_response(json_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def test_get_nodes_smoke(monkeypatch):
    """Smoke test: existing get_nodes() works with mocked HTTP."""
    api = proxmox_api.ProxmoxAPI()
    with patch("proxmox_api.requests.request",
               return_value=_mock_response({"data": [{"node": "pve"}]})) as mock_req:
        nodes = api.get_nodes()
    assert nodes == [{"node": "pve"}]
    mock_req.assert_called_once()
    args, kwargs = mock_req.call_args
    assert args[0] == "GET"
    assert args[1].endswith("/nodes")
```

- [ ] **Step 4: Run the smoke test**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: `1 passed`. If it fails with import error, verify `sys.path.insert` line and that `proxmox_api.py` is in the same directory.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .claude/skills/proxmox/scripts/test_proxmox_api.py
git commit -m "test(skills/proxmox): bootstrap pytest with smoke test for get_nodes"
```

---

## Task 2: Add `list_templates` method + `templates` CLI action

**Files:**
- Modify: `.claude/skills/proxmox/scripts/proxmox_api.py`
- Modify: `.claude/skills/proxmox/scripts/test_proxmox_api.py`

- [ ] **Step 1: Write the failing test**

Append to `test_proxmox_api.py`:

```python
def test_list_templates_returns_vztmpl_only():
    api = proxmox_api.ProxmoxAPI()
    sample = {
        "data": [
            {"volid": "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst",
             "format": "tzst", "size": 200000000},
            {"volid": "local:iso/some.iso", "format": "iso", "size": 9999},
        ]
    }
    with patch("proxmox_api.requests.request",
               return_value=_mock_response(sample)) as mock_req:
        templates = api.list_templates("pve", "local")
    assert len(templates) == 1
    assert templates[0]["volid"].startswith("local:vztmpl/")
    # Verify endpoint includes content=vztmpl filter
    _, kwargs = mock_req.call_args
    assert kwargs.get("params", {}).get("content") == "vztmpl" or \
        "content=vztmpl" in mock_req.call_args.args[1]
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py::test_list_templates_returns_vztmpl_only -v`
Expected: FAIL with `AttributeError: 'ProxmoxAPI' object has no attribute 'list_templates'`.

- [ ] **Step 3: Implement `list_templates` method**

In `proxmox_api.py`, locate the storage section (right after `get_storage_content`, around line 188). Add this method:

```python
    def list_templates(self, node: str, storage: str = "local") -> list:
        """List container templates (vztmpl) available on a storage.

        Returns list of dicts with keys: volid, format, size.
        Only vztmpl content is returned (ISO and backups filtered out).
        """
        # Proxmox content filter: ?content=vztmpl
        return self.get(f"/nodes/{node}/storage/{storage}/content?content=vztmpl")
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py::test_list_templates_returns_vztmpl_only -v`
Expected: PASS.

- [ ] **Step 5: Add CLI dispatch in `execute()`**

In `proxmox_api.py` `execute()` function, before the `else: raise ValueError(...)` line (around line 312), add:

```python
    elif action == "templates":
        return api.list_templates(args["node"], args.get("storage", "local"))
```

- [ ] **Step 6: Add subparser in `main()`**

In `main()`, after the `overview` subparser block (around line 431), add:

```python
    # Templates
    templates = subparsers.add_parser("templates", help="List LXC templates on storage")
    templates.add_argument("node", nargs="?", help="Node name (auto-detected if omitted)")
    templates.add_argument("--storage", default="local", help="Storage name (default: local)")
```

- [ ] **Step 7: Add `templates` to `commands_with_optional_node`**

In `main()`, find the list `commands_with_optional_node` (around line 444) and add `"templates"`:

```python
    commands_with_optional_node = ["node-status", "vms", "containers", "overview",
                                    "start", "stop", "shutdown", "reboot", "templates"]
```

- [ ] **Step 8: Wire up dispatch in main()**

After the `elif args.command == "overview"` branch (search for it; should be near the end of `main()`), add before the `else`/final block:

```python
    elif args.command == "templates":
        result = execute("templates", {"node": args.node, "storage": args.storage})
```

- [ ] **Step 9: Verify CLI works via mocked subprocess test**

Append to `test_proxmox_api.py`:

```python
def test_templates_cli_dispatch(monkeypatch, capsys):
    """End-to-end: invoking via main() with mocked HTTP returns JSON."""
    sample_data = [
        {"volid": "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst",
         "format": "tzst", "size": 200000000}
    ]
    monkeypatch.setattr(sys, "argv",
                        ["proxmox_api.py", "--json", "templates", "pve"])
    with patch("proxmox_api.requests.request",
               return_value=_mock_response({"data": sample_data})):
        proxmox_api.main()
    out = capsys.readouterr().out
    assert "debian-12-standard" in out
```

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: 3 passed.

- [ ] **Step 10: Commit**

```bash
git add .claude/skills/proxmox/scripts/proxmox_api.py .claude/skills/proxmox/scripts/test_proxmox_api.py
git commit -m "feat(skills/proxmox): add 'templates' action to list LXC templates"
```

---

## Task 3: Add `wait_task` method + `wait-task` CLI action

**Files:**
- Modify: `.claude/skills/proxmox/scripts/proxmox_api.py`
- Modify: `.claude/skills/proxmox/scripts/test_proxmox_api.py`

- [ ] **Step 1: Write the failing test for success path**

Append to `test_proxmox_api.py`:

```python
def test_wait_task_success(monkeypatch):
    """Polls until status=stopped, returns exitstatus."""
    api = proxmox_api.ProxmoxAPI()
    # Simulate two "running" polls then "stopped/OK"
    responses_seq = [
        _mock_response({"data": {"status": "running"}}),
        _mock_response({"data": {"status": "running"}}),
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
    ]
    with patch("proxmox_api.requests.request", side_effect=responses_seq):
        # Patch sleep so we don't actually wait
        with patch("proxmox_api.time.sleep") as mock_sleep:
            result = api.wait_task("pve", "UPID:pve:1234", interval=2, timeout=60)
    assert result["exitstatus"] == "OK"
    assert mock_sleep.call_count == 2  # sleeps before re-poll, not after final


def test_wait_task_failure(monkeypatch):
    """Non-OK exitstatus surfaces as RuntimeError."""
    api = proxmox_api.ProxmoxAPI()
    with patch("proxmox_api.requests.request",
               return_value=_mock_response(
                   {"data": {"status": "stopped", "exitstatus": "command 'lxc-start' failed"}})):
        with patch("proxmox_api.time.sleep"):
            with pytest.raises(RuntimeError, match="lxc-start"):
                api.wait_task("pve", "UPID:pve:1234", interval=2, timeout=60)


def test_wait_task_timeout(monkeypatch):
    """Returns TimeoutError when task never stops within timeout."""
    api = proxmox_api.ProxmoxAPI()
    with patch("proxmox_api.requests.request",
               return_value=_mock_response({"data": {"status": "running"}})):
        with patch("proxmox_api.time.sleep"):
            # Need monotonic to advance so timeout triggers
            t = [0.0]
            def fake_monotonic():
                t[0] += 5
                return t[0]
            with patch("proxmox_api.time.monotonic", side_effect=fake_monotonic):
                with pytest.raises(TimeoutError):
                    api.wait_task("pve", "UPID:pve:1234", interval=2, timeout=10)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k wait_task`
Expected: All 3 FAIL with `AttributeError` (and the test file fails to import `time` from `proxmox_api`).

- [ ] **Step 3: Add `time` import + `wait_task` method**

In `proxmox_api.py`, near the top with the other imports, add:

```python
import time
```

Then add this method to the `ProxmoxAPI` class, right after `rollback_snapshot` (search for `def rollback_snapshot`; add below its closing). Locate by finding `# Storage operations` or the snapshot section — place after the last existing method but before the dedent that ends the class:

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k wait_task`
Expected: 3 passed.

- [ ] **Step 5: Add CLI dispatch + subparser**

In `execute()` (before the `else: raise ValueError`):

```python
    elif action == "wait-task":
        return api.wait_task(args["node"], args["upid"],
                             interval=float(args.get("interval", 2.0)),
                             timeout=float(args.get("timeout", 600.0)))
```

In `main()`, after the `templates` subparser:

```python
    # Wait for task
    wait_task = subparsers.add_parser("wait-task", help="Poll a Proxmox task until done")
    wait_task.add_argument("upid", help="Task UPID returned by an async call")
    wait_task.add_argument("--node", help="Node name (auto-detected if omitted)")
    wait_task.add_argument("--interval", type=float, default=2.0, help="Poll interval seconds")
    wait_task.add_argument("--timeout", type=float, default=600.0, help="Max wait seconds")
```

Add `"wait-task"` to `commands_with_optional_node`:

```python
    commands_with_optional_node = ["node-status", "vms", "containers", "overview",
                                    "start", "stop", "shutdown", "reboot",
                                    "templates", "wait-task"]
```

In the main dispatch:

```python
    elif args.command == "wait-task":
        result = execute("wait-task", {"node": args.node, "upid": args.upid,
                                        "interval": args.interval, "timeout": args.timeout})
```

- [ ] **Step 6: Run full test file**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/proxmox/scripts/proxmox_api.py .claude/skills/proxmox/scripts/test_proxmox_api.py
git commit -m "feat(skills/proxmox): add 'wait-task' action to poll Proxmox tasks"
```

---

## Task 4: Add `create_lxc` method + `create-lxc` CLI action

**Files:**
- Modify: `.claude/skills/proxmox/scripts/proxmox_api.py`
- Modify: `.claude/skills/proxmox/scripts/test_proxmox_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_proxmox_api.py`:

```python
def test_get_next_vmid(monkeypatch):
    """Calls /cluster/nextid and returns an int."""
    api = proxmox_api.ProxmoxAPI()
    with patch("proxmox_api.requests.request",
               return_value=_mock_response({"data": "201"})):
        next_id = api.get_next_vmid()
    assert next_id == 201


def test_create_lxc_with_explicit_vmid(monkeypatch):
    """Posts to /nodes/{node}/lxc with correct body, waits for task, returns vmid."""
    api = proxmox_api.ProxmoxAPI()

    upid = "UPID:pve:00001234:00ABCDEF:5A0000:vzcreate:200:root@pam!homelab:"

    seq = [
        # POST /nodes/pve/lxc → returns UPID
        _mock_response({"data": upid}),
        # GET /nodes/pve/tasks/.../status → done OK
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
    ]
    with patch("proxmox_api.requests.request", side_effect=seq) as mock_req:
        with patch("proxmox_api.time.sleep"):
            result = api.create_lxc(
                node="pve",
                vmid=200,
                ostemplate="local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst",
                hostname="rolly",
                cores=2,
                memory=1024,
                disk_gb=10,
                storage="local-lvm",
                bridge="vmbr0",
                ip_cidr="192.168.10.200/24",
                gateway="192.168.10.1",
                ssh_public_keys="ssh-ed25519 AAAA test@mac",
                unprivileged=True,
                start=True,
            )

    assert result["vmid"] == 200
    assert result["upid"] == upid
    assert result["exitstatus"] == "OK"

    # Inspect the POST body — _request passes data= as kwarg to requests.request
    post_call = mock_req.call_args_list[0]
    body = post_call.kwargs["data"]
    assert body["vmid"] == 200
    assert body["hostname"] == "rolly"
    assert body["cores"] == 2
    assert body["memory"] == 1024
    assert body["rootfs"] == "local-lvm:10"
    assert body["net0"] == "name=eth0,bridge=vmbr0,ip=192.168.10.200/24,gw=192.168.10.1"
    assert body["unprivileged"] == 1
    assert body["start"] == 1
    assert "ssh-ed25519" in body["ssh-public-keys"]


def test_create_lxc_auto_vmid(monkeypatch):
    """When vmid='auto', calls /cluster/nextid first."""
    api = proxmox_api.ProxmoxAPI()
    upid = "UPID:pve:fake:vzcreate:201:test:"
    seq = [
        # GET /cluster/nextid → "201"
        _mock_response({"data": "201"}),
        # POST /nodes/pve/lxc → upid
        _mock_response({"data": upid}),
        # GET tasks/.../status → OK
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
    ]
    with patch("proxmox_api.requests.request", side_effect=seq) as mock_req:
        with patch("proxmox_api.time.sleep"):
            result = api.create_lxc(
                node="pve", vmid="auto",
                ostemplate="local:vztmpl/debian-12-standard.tar.zst",
                hostname="rolly", cores=1, memory=512, disk_gb=5,
                storage="local-lvm", bridge="vmbr0",
                ip_cidr="dhcp", gateway=None,
                ssh_public_keys="", unprivileged=True, start=False,
            )
    assert result["vmid"] == 201
    # net0 with dhcp should not include gw=
    post_call = mock_req.call_args_list[1]
    body = post_call.kwargs["data"]
    assert "ip=dhcp" in body["net0"]
    assert "gw=" not in body["net0"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k create_lxc -k next_vmid`
Expected: 3 FAIL with AttributeError.

- [ ] **Step 3: Implement `get_next_vmid` and `create_lxc` methods**

In `proxmox_api.py`, in the `ProxmoxAPI` class (after `wait_task`):

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k "create_lxc or next_vmid"`
Expected: 3 passed.

If `test_create_lxc_with_explicit_vmid` fails on body inspection: the `_request` signature passes `data=` as a keyword arg, so `post_call.kwargs["data"]` should be the body dict. Adjust the assertion to use `mock_req.call_args_list[0].kwargs["data"]` consistently.

- [ ] **Step 5: Add CLI dispatch in `execute()`**

```python
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
```

- [ ] **Step 6: Add subparser in `main()`**

```python
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
```

Add `"create-lxc"` to `commands_with_optional_node`.

- [ ] **Step 7: Wire dispatch in main**

```python
    elif args.command == "create-lxc":
        result = execute("create-lxc", {
            "node": args.node, "vmid": args.vmid, "hostname": args.hostname,
            "template": args.template, "cores": args.cores, "memory": args.memory,
            "disk": args.disk, "storage": args.storage, "bridge": args.bridge,
            "ip": args.ip, "gateway": args.gateway, "ssh_key": args.ssh_key,
            "unprivileged": args.unprivileged, "start": args.start,
            "nameserver": args.nameserver, "timeout": args.timeout,
        })
```

- [ ] **Step 8: Run full test file**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: 9 passed.

- [ ] **Step 9: Commit**

```bash
git add .claude/skills/proxmox/scripts/proxmox_api.py .claude/skills/proxmox/scripts/test_proxmox_api.py
git commit -m "feat(skills/proxmox): add 'create-lxc' action to provision containers"
```

---

## Task 5: Add `delete_lxc` method + `delete-lxc` CLI action

**Files:**
- Modify: `.claude/skills/proxmox/scripts/proxmox_api.py`
- Modify: `.claude/skills/proxmox/scripts/test_proxmox_api.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_proxmox_api.py`:

```python
def test_delete_lxc_graceful(monkeypatch):
    """Shutdown then destroy, waiting for each task."""
    api = proxmox_api.ProxmoxAPI()
    upid_shutdown = "UPID:pve:fake:vzshutdown:200:"
    upid_destroy = "UPID:pve:fake:vzdestroy:200:"
    seq = [
        # GET status (running)
        _mock_response({"data": {"status": "running"}}),
        # POST shutdown
        _mock_response({"data": upid_shutdown}),
        # wait_task → stopped/OK
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
        # DELETE → upid
        _mock_response({"data": upid_destroy}),
        # wait_task → stopped/OK
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
    ]
    with patch("proxmox_api.requests.request", side_effect=seq):
        with patch("proxmox_api.time.sleep"):
            result = api.delete_lxc("pve", 200)
    assert result["vmid"] == 200
    assert result["deleted"] is True


def test_delete_lxc_already_stopped(monkeypatch):
    """Skip shutdown when container is already stopped."""
    api = proxmox_api.ProxmoxAPI()
    upid_destroy = "UPID:pve:fake:vzdestroy:200:"
    seq = [
        _mock_response({"data": {"status": "stopped"}}),
        _mock_response({"data": upid_destroy}),
        _mock_response({"data": {"status": "stopped", "exitstatus": "OK"}}),
    ]
    with patch("proxmox_api.requests.request", side_effect=seq) as mock_req:
        with patch("proxmox_api.time.sleep"):
            result = api.delete_lxc("pve", 200)
    assert result["deleted"] is True
    # Only 3 calls: status, DELETE, wait — no shutdown POST
    assert mock_req.call_count == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k delete_lxc`
Expected: FAIL with AttributeError.

- [ ] **Step 3: Implement `delete_lxc`**

Add to `ProxmoxAPI` class (after `create_lxc`):

```python
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
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v -k delete_lxc`
Expected: 2 passed.

- [ ] **Step 5: Add CLI dispatch + subparser**

In `execute()`:

```python
    elif action == "delete-lxc":
        return api.delete_lxc(args["node"], int(args["vmid"]),
                              force=bool(args.get("force", False)),
                              timeout=float(args.get("timeout", 120.0)))
```

In `main()`:

```python
    # Delete LXC
    delete_lxc = subparsers.add_parser("delete-lxc", help="Stop and destroy an LXC")
    delete_lxc.add_argument("vmid", type=int, help="Container ID")
    delete_lxc.add_argument("--node", help="Node name (auto-detected)")
    delete_lxc.add_argument("--force", action="store_true",
                            help="Hard-stop instead of graceful shutdown")
    delete_lxc.add_argument("--timeout", type=float, default=120.0)
```

Add `"delete-lxc"` to `commands_with_optional_node`.

Dispatch:

```python
    elif args.command == "delete-lxc":
        result = execute("delete-lxc", {"node": args.node, "vmid": args.vmid,
                                         "force": args.force, "timeout": args.timeout})
```

- [ ] **Step 6: Full test file run**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: 11 passed.

- [ ] **Step 7: Commit**

```bash
git add .claude/skills/proxmox/scripts/proxmox_api.py .claude/skills/proxmox/scripts/test_proxmox_api.py
git commit -m "feat(skills/proxmox): add 'delete-lxc' action with graceful shutdown"
```

---

## Task 6: Document the new actions in proxmox SKILL.md

**Files:**
- Modify: `.claude/skills/proxmox/SKILL.md`

- [ ] **Step 1: Add new commands to the "Common Commands" section**

In `.claude/skills/proxmox/SKILL.md`, find the `# Containers` block in the "Common Commands" section (around line 119) and append:

```bash

# LXC lifecycle (new in 1.3.0)
proxmox_api.py templates [node] [--storage local]              # List LXC templates
proxmox_api.py create-lxc --hostname rolly --template "local:vztmpl/debian-12-standard_*_amd64.tar.zst" \
                          --cores 2 --memory 1024 --disk 10 \
                          --ip 192.168.10.200/24 --gateway 192.168.10.1 \
                          --ssh-key "$(cat ~/.ssh/id_rsa.pub)" --unprivileged --start
proxmox_api.py delete-lxc <vmid> [--force]                     # Stop + destroy LXC
proxmox_api.py wait-task <upid> [--node pve] [--timeout 600]   # Poll a task
```

- [ ] **Step 2: Add a "Provisioning new app via LXC" workflow**

After the "Pre-Maintenance Snapshot" workflow, add:

```markdown
### Provisioning a New App in an LXC

1. Verify template available:
   `proxmox_api.py templates pve --storage local | grep debian-12`
2. Create container (auto-picks VMID via `/cluster/nextid`):
   ```
   proxmox_api.py --json create-lxc --hostname myapp \
       --template "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst" \
       --cores 2 --memory 1024 --disk 10 \
       --ip 192.168.10.X/24 --gateway 192.168.10.1 \
       --ssh-key "$(cat ~/.ssh/id_rsa.pub)"
   ```
   Output JSON: `{"vmid": 201, "upid": "...", "exitstatus": "OK"}`
3. SSH in: `ssh root@192.168.10.X` (key already injected by --ssh-key)
4. To remove: `proxmox_api.py delete-lxc 201`
```

- [ ] **Step 3: Bump skill version**

Change `version: 1.2.0` at the top of the SKILL.md to `version: 1.3.0`.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/proxmox/SKILL.md
git commit -m "docs(skills/proxmox): document templates/create-lxc/delete-lxc/wait-task actions"
```

---

## Task 7: Bootstrap `infra/rolly/` directory + `.gitignore` rule

**Files:**
- Create: `infra/rolly/` (directory)
- Modify: `.gitignore`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p infra/rolly
```

- [ ] **Step 2: Append the ignore rule**

In `.gitignore`, append at the end:

```
# Rolly deployment secrets (never commit the real config)
infra/rolly/config.env
```

- [ ] **Step 3: Commit (empty dir won't be tracked yet; we commit just the gitignore for now)**

```bash
git add .gitignore
git commit -m "chore: gitignore infra/rolly/config.env (deploy secrets)"
```

---

## Task 8: Write `config.env.example`

**Files:**
- Create: `infra/rolly/config.env.example`

- [ ] **Step 1: Write the template**

Create `infra/rolly/config.env.example` with this exact content:

```bash
# ===== Rolly Deployment Config =====
# Copy this file to config.env and fill in your values.
# config.env is gitignored.

# --- Proxmox connection (where your existing token works) ---
PROXMOX_HOST=192.168.10.140
PROXMOX_PORT=8006
PROXMOX_TOKEN_ID=root@pam!homelab
PROXMOX_TOKEN_SECRET=

# --- LXC placement ---
LXC_HOSTNAME=rolly
LXC_IP_CIDR=192.168.10.200/24
LXC_GATEWAY=192.168.10.1
LXC_BRIDGE=vmbr0
LXC_CORES=2
LXC_MEMORY_MB=1024
LXC_DISK_GB=10
LXC_STORAGE=local-lvm
LXC_TEMPLATE_PREFIX=debian-12-standard

# --- Public endpoint (Let's Encrypt + Telegram webhook) ---
DUCKDNS_HOST=sophia-und-philipp.duckdns.org
DUCKDNS_TOKEN=
PUBLIC_PORT=8443

# --- Telegram (ROTATE the bot token at @BotFather before first deploy) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_ALLOWED_USERS=
ADMIN_TELEGRAM_ID=

# --- LM Studio (Gaming PC, cross-subnet) ---
LM_STUDIO_URL=http://192.168.1.135:1234
LM_STUDIO_MODEL=gemma-4-e4b
EMBEDDING_MODEL=nomic-embed-text-v2-moe

# --- Home Assistant ---
HA_URL=http://homeassistant.local:8123
HA_TOKEN=

# --- Wake-on-LAN (Gaming PC) ---
GAMING_PC_IP=192.168.1.135
GAMING_PC_MAC=

# --- Internal endpoints (leave empty → deploy.sh generates) ---
INTERNAL_NOTIFY_TOKEN=
PORT=8080
```

- [ ] **Step 2: Commit**

```bash
git add infra/rolly/config.env.example
git commit -m "feat(infra/rolly): add config.env template for deployment"
```

---

## Task 9: Write Caddyfile, rolly.service, caddy.service templates

**Files:**
- Create: `infra/rolly/Caddyfile.tmpl`
- Create: `infra/rolly/rolly.service.tmpl`
- Create: `infra/rolly/caddy.service`

- [ ] **Step 1: Create `Caddyfile.tmpl`**

```caddy
{
    email letsencrypt-${DUCKDNS_HOST}@duckdns.org
    # DNS-01 challenge via DuckDNS (no port 80 needed)
    acme_dns duckdns ${DUCKDNS_TOKEN}
}

${DUCKDNS_HOST}:${PUBLIC_PORT} {
    reverse_proxy 127.0.0.1:${PORT}
    encode gzip
    log {
        output file /var/log/caddy/rolly.access.log
        format console
    }
}
```

- [ ] **Step 2: Create `rolly.service.tmpl`**

```ini
[Unit]
Description=Rolly Telegram Bot (Bun)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/rolly/agent
EnvironmentFile=/opt/rolly/.env
ExecStart=/root/.bun/bin/bun run src/main.ts
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

# Light hardening — LXC already isolates
NoNewPrivileges=yes
ProtectSystem=full
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create `caddy.service`**

```ini
[Unit]
Description=Caddy reverse proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=root
ExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile
ExecReload=/usr/bin/caddy reload --config /etc/caddy/Caddyfile --force
Restart=on-abnormal
RestartSec=5s
LimitNOFILE=1048576
TimeoutStopSec=5s

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Commit**

```bash
git add infra/rolly/Caddyfile.tmpl infra/rolly/rolly.service.tmpl infra/rolly/caddy.service
git commit -m "feat(infra/rolly): add Caddyfile + systemd unit templates"
```

---

## Task 10: Write `setup-lxc.sh` (runs inside the LXC)

**Files:**
- Create: `infra/rolly/setup-lxc.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# Runs inside the LXC. Idempotent: every step is check-then-act.
# Expected files in /root before invocation:
#   .env, Caddyfile.tmpl, rolly.service.tmpl, caddy.service

set -euo pipefail

log() { printf "\n\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }

REPO_URL="https://github.com/Piwo96/homelab-assistant.git"
REPO_DIR="/opt/rolly"

require_files() {
    for f in /root/.env /root/Caddyfile.tmpl /root/rolly.service.tmpl /root/caddy.service; do
        [ -f "$f" ] || { echo "Missing required file: $f" >&2; exit 1; }
    done
}

apt_install() {
    log "Installing base packages"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -yqq git curl ca-certificates python3 python3-pip \
                         python3-venv unzip gettext-base debian-keyring \
                         debian-archive-keyring apt-transport-https
    ok "base packages installed"
}

install_caddy_repo() {
    log "Configuring Caddy APT repo"
    if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ]; then
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            > /etc/apt/sources.list.d/caddy-stable.list
        apt-get update -qq
    fi
    apt-get install -yqq caddy
    ok "caddy installed: $(caddy version | head -1)"
}

install_bun() {
    log "Installing Bun"
    if [ ! -x /root/.bun/bin/bun ]; then
        curl -fsSL https://bun.sh/install | bash
    fi
    export PATH="/root/.bun/bin:$PATH"
    ok "bun: $(bun --version)"
}

clone_or_pull() {
    log "Syncing code at $REPO_DIR"
    if [ ! -d "$REPO_DIR/.git" ]; then
        git clone "$REPO_URL" "$REPO_DIR"
    else
        git -C "$REPO_DIR" pull --ff-only
    fi
    ok "repo at: $(git -C $REPO_DIR rev-parse --short HEAD)"
}

install_agent_deps() {
    log "Installing agent (Bun) deps"
    cd "$REPO_DIR/agent"
    /root/.bun/bin/bun install
    ok "agent deps installed"
}

install_skill_deps() {
    log "Installing Python skill deps"
    if [ ! -d "$REPO_DIR/.venv" ]; then
        python3 -m venv "$REPO_DIR/.venv"
    fi
    "$REPO_DIR/.venv/bin/pip" install -q --upgrade pip
    "$REPO_DIR/.venv/bin/pip" install -q -r "$REPO_DIR/requirements.txt"
    ok "python deps installed"
}

add_duckdns_plugin() {
    log "Ensuring caddy has caddy-dns/duckdns module"
    if ! caddy list-modules 2>/dev/null | grep -q "dns.providers.duckdns"; then
        systemctl stop caddy 2>/dev/null || true
        caddy add-package github.com/caddy-dns/duckdns
    fi
    ok "duckdns module present"
}

place_env_and_render() {
    log "Placing .env and rendering templates"
    install -m 600 /root/.env "$REPO_DIR/.env"
    chown root:root "$REPO_DIR/.env"
    # Render Caddyfile + rolly.service via envsubst (read vars from .env)
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
    mkdir -p /etc/caddy /var/log/caddy
    envsubst < /root/Caddyfile.tmpl > /etc/caddy/Caddyfile
    envsubst < /root/rolly.service.tmpl > /etc/systemd/system/rolly.service
    cp /root/caddy.service /etc/systemd/system/caddy.service
    ok "rendered /etc/caddy/Caddyfile + systemd units"
}

start_services() {
    log "Starting/restarting services"
    systemctl daemon-reload
    systemctl enable rolly.service caddy.service >/dev/null
    systemctl restart caddy.service
    systemctl restart rolly.service
    ok "services started"
}

smoke_test() {
    log "Smoke test: GET http://localhost:8080/health"
    for i in 1 2 3 4 5; do
        if curl -fsS --max-time 3 http://127.0.0.1:8080/health >/dev/null; then
            ok "rolly /health OK"
            return 0
        fi
        sleep 2
    done
    echo "Rolly /health did not respond. Check: journalctl -u rolly --no-pager -n 50" >&2
    exit 1
}

main() {
    require_files
    apt_install
    install_caddy_repo
    install_bun
    clone_or_pull
    install_agent_deps
    install_skill_deps
    add_duckdns_plugin
    place_env_and_render
    start_services
    smoke_test
    log "Setup complete"
}

main "$@"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x infra/rolly/setup-lxc.sh
```

- [ ] **Step 3: Lint with shellcheck (if installed)**

Run: `shellcheck infra/rolly/setup-lxc.sh || echo "shellcheck not installed — skipping"`
Expected: no errors. Warnings about `SC1091` (sourcing a file at runtime) are acceptable and suppressed inline.

- [ ] **Step 4: Commit**

```bash
git add infra/rolly/setup-lxc.sh
git commit -m "feat(infra/rolly): add idempotent in-LXC setup script"
```

---

## Task 11: Write `deploy.sh` (Mac-side orchestrator)

**Files:**
- Create: `infra/rolly/deploy.sh`

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# Rolly deployment orchestrator — runs on the Mac.
# Idempotent: re-runs reuse the existing LXC and just re-sync code + restart.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$( cd "$SCRIPT_DIR/../.." && pwd )"
PROXMOX_API="$REPO_ROOT/.claude/skills/proxmox/scripts/proxmox_api.py"

log()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$1"; }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$1" >&2; exit 1; }

# --- 1. Load + validate config ---
load_config() {
    log "Loading infra/rolly/config.env"
    [ -f "$SCRIPT_DIR/config.env" ] || fail "Missing $SCRIPT_DIR/config.env (copy from config.env.example)"
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/config.env"
    set +a

    local required=(PROXMOX_HOST PROXMOX_TOKEN_ID PROXMOX_TOKEN_SECRET
                    LXC_HOSTNAME LXC_IP_CIDR LXC_GATEWAY LXC_BRIDGE
                    LXC_CORES LXC_MEMORY_MB LXC_DISK_GB LXC_STORAGE
                    DUCKDNS_HOST DUCKDNS_TOKEN PUBLIC_PORT
                    TELEGRAM_BOT_TOKEN TELEGRAM_ALLOWED_USERS ADMIN_TELEGRAM_ID
                    LM_STUDIO_URL HA_URL HA_TOKEN PORT)
    for v in "${required[@]}"; do
        [ -n "${!v:-}" ] || fail "Missing required variable: $v"
    done

    # Generate missing secrets
    if [ -z "${TELEGRAM_WEBHOOK_SECRET:-}" ]; then
        TELEGRAM_WEBHOOK_SECRET=$(openssl rand -hex 32)
        ok "Generated TELEGRAM_WEBHOOK_SECRET"
    fi
    if [ -z "${INTERNAL_NOTIFY_TOKEN:-}" ]; then
        INTERNAL_NOTIFY_TOKEN=$(openssl rand -hex 32)
        ok "Generated INTERNAL_NOTIFY_TOKEN"
    fi

    LXC_IP="${LXC_IP_CIDR%%/*}"  # strip CIDR for SSH target
    ok "Config validated. Target IP: $LXC_IP"
}

# --- 2. Verify proxmox skill reachable ---
verify_proxmox() {
    log "Verifying Proxmox API reachable"
    python3 "$PROXMOX_API" --json nodes >/dev/null || fail "proxmox_api.py nodes failed"
    ok "Proxmox API OK"
}

# --- 3. Check for existing LXC by hostname ---
find_existing_lxc() {
    log "Checking for existing LXC named '$LXC_HOSTNAME'"
    local found
    found=$(python3 "$PROXMOX_API" --json containers \
            | python3 -c "import sys,json; data=json.load(sys.stdin); \
                          m=[c for c in data if c.get('name')=='$LXC_HOSTNAME']; \
                          print(m[0]['vmid'] if m else '')")
    if [ -n "$found" ]; then
        EXISTING_VMID="$found"
        ok "Found existing LXC '$LXC_HOSTNAME' vmid=$found — will reuse"
    else
        EXISTING_VMID=""
        ok "No existing LXC found — will create"
    fi
}

# --- 4. Verify template available ---
verify_template() {
    log "Checking for template matching '$LXC_TEMPLATE_PREFIX'"
    LXC_TEMPLATE_VOLID=$(python3 "$PROXMOX_API" --json templates --storage local \
        | python3 -c "import sys,json; data=json.load(sys.stdin); \
            m=sorted([t['volid'] for t in data if '$LXC_TEMPLATE_PREFIX' in t['volid']]); \
            print(m[-1] if m else '')")
    if [ -z "$LXC_TEMPLATE_VOLID" ]; then
        fail "Template '$LXC_TEMPLATE_PREFIX' not found. SSH to Proxmox and run: pveam download local debian-12-standard"
    fi
    ok "Template: $LXC_TEMPLATE_VOLID"
}

# --- 5. Create LXC (if needed) ---
create_lxc_if_needed() {
    if [ -n "$EXISTING_VMID" ]; then
        VMID="$EXISTING_VMID"
        return
    fi
    log "Creating LXC '$LXC_HOSTNAME'"
    local pubkey
    pubkey=$(cat "${SSH_KEY_PATH:-$HOME/.ssh/id_rsa.pub}")

    local result
    result=$(python3 "$PROXMOX_API" --json create-lxc \
        --hostname "$LXC_HOSTNAME" \
        --template "$LXC_TEMPLATE_VOLID" \
        --cores "$LXC_CORES" --memory "$LXC_MEMORY_MB" --disk "$LXC_DISK_GB" \
        --storage "$LXC_STORAGE" --bridge "$LXC_BRIDGE" \
        --ip "$LXC_IP_CIDR" --gateway "$LXC_GATEWAY" \
        --ssh-key "$pubkey" \
        --nameserver "$LXC_GATEWAY")
    VMID=$(echo "$result" | python3 -c "import sys,json;print(json.load(sys.stdin)['vmid'])")
    ok "Created LXC vmid=$VMID"
}

# --- 6. Wait for SSH ---
wait_for_ssh() {
    log "Waiting for SSH on $LXC_IP"
    for i in $(seq 1 40); do  # 40 × 3s = 2 min
        if ssh -o ConnectTimeout=3 -o BatchMode=yes \
               -o StrictHostKeyChecking=accept-new \
               -o UserKnownHostsFile=/dev/null \
               "root@$LXC_IP" "echo ok" >/dev/null 2>&1; then
            ok "SSH up after ${i} attempts"
            return
        fi
        sleep 3
    done
    fail "SSH did not come up within 2 min"
}

# --- 7. Assemble .env and SCP artifacts ---
upload_artifacts() {
    log "Uploading artifacts to LXC"
    local tmpdir
    tmpdir=$(mktemp -d)
    # Build the .env from current shell env (only the agent-relevant vars)
    cat > "$tmpdir/.env" <<EOF
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET
TELEGRAM_ALLOWED_USERS=$TELEGRAM_ALLOWED_USERS
ADMIN_TELEGRAM_ID=$ADMIN_TELEGRAM_ID
LM_STUDIO_URL=$LM_STUDIO_URL
LM_STUDIO_MODEL=${LM_STUDIO_MODEL:-gemma-4-e4b}
EMBEDDING_MODEL=${EMBEDDING_MODEL:-nomic-embed-text-v2-moe}
HA_URL=$HA_URL
HA_TOKEN=$HA_TOKEN
GAMING_PC_IP=${GAMING_PC_IP:-}
GAMING_PC_MAC=${GAMING_PC_MAC:-}
INTERNAL_NOTIFY_TOKEN=$INTERNAL_NOTIFY_TOKEN
PORT=$PORT
PUBLIC_PORT=$PUBLIC_PORT
DUCKDNS_HOST=$DUCKDNS_HOST
DUCKDNS_TOKEN=$DUCKDNS_TOKEN
PROXMOX_HOST=$PROXMOX_HOST
PROXMOX_TOKEN_ID=$PROXMOX_TOKEN_ID
PROXMOX_TOKEN_SECRET=$PROXMOX_TOKEN_SECRET
EOF
    chmod 600 "$tmpdir/.env"

    local ssh_opts=(-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null)
    scp "${ssh_opts[@]}" \
        "$tmpdir/.env" \
        "$SCRIPT_DIR/setup-lxc.sh" \
        "$SCRIPT_DIR/Caddyfile.tmpl" \
        "$SCRIPT_DIR/rolly.service.tmpl" \
        "$SCRIPT_DIR/caddy.service" \
        "root@$LXC_IP:/root/"
    rm -rf "$tmpdir"
    ok "Artifacts uploaded"
}

# --- 8. Run setup in LXC ---
run_setup() {
    log "Running setup-lxc.sh inside LXC (this is the long step)"
    ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
        "root@$LXC_IP" "bash /root/setup-lxc.sh"
    ok "Setup completed inside LXC"
}

# --- 9. End-to-end health checks ---
health_checks() {
    log "End-to-end health checks"
    ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null \
        "root@$LXC_IP" 'curl -fsS http://127.0.0.1:8080/health' >/dev/null \
        || fail "Internal /health failed"
    ok "Internal /health OK"

    log "Waiting for Caddy to obtain the LE cert (DNS-01 can take ~30-90s on first run)..."
    for i in $(seq 1 30); do
        if curl -fsS --max-time 5 "https://${DUCKDNS_HOST}:${PUBLIC_PORT}/health" >/dev/null 2>&1; then
            ok "Public https://${DUCKDNS_HOST}:${PUBLIC_PORT}/health OK"
            return
        fi
        sleep 4
    done
    fail "Public endpoint never came up. SSH to LXC and check: journalctl -u caddy -n 50"
}

# --- 10. Print setWebhook command ---
print_webhook_command() {
    log "Set the Telegram webhook by running:"
    cat <<EOF

  curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \\
       -d "url=https://${DUCKDNS_HOST}:${PUBLIC_PORT}/webhook" \\
       -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}" \\
       -d "drop_pending_updates=true"

EOF
    ok "Done. Send /start to your bot to verify end-to-end."
}

main() {
    load_config
    verify_proxmox
    find_existing_lxc
    [ -z "$EXISTING_VMID" ] && verify_template
    create_lxc_if_needed
    wait_for_ssh
    upload_artifacts
    run_setup
    health_checks
    print_webhook_command
}

main "$@"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x infra/rolly/deploy.sh
```

- [ ] **Step 3: Lint with shellcheck**

Run: `shellcheck infra/rolly/deploy.sh || echo "shellcheck not installed"`
Expected: clean (SC1091 acceptable since sourced file exists at runtime).

- [ ] **Step 4: Commit**

```bash
git add infra/rolly/deploy.sh
git commit -m "feat(infra/rolly): add Mac-side deploy orchestrator"
```

---

## Task 12: Write `infra/rolly/README.md`

**Files:**
- Create: `infra/rolly/README.md`

- [ ] **Step 1: Write the README**

```markdown
# Rolly — Proxmox Deployment

Deploy Rolly (the Telegram-Agent under `agent/`) as an LXC on the local Proxmox host, reachable from Telegram's cloud via DuckDNS + Caddy + Let's Encrypt.

See [the design spec](../../docs/superpowers/specs/2026-05-16-rolly-proxmox-deploy-design.md) for the full architecture and decisions.

## One-time manual setup

Do these once before the first `./deploy.sh`.

### 1. Rotate the Telegram bot token

Open Telegram → @BotFather → `/revoke` for the existing bot → copy the new token. Paste it into `config.env` as `TELEGRAM_BOT_TOKEN`.

### 2. DuckDNS token

Go to <https://www.duckdns.org/> → log in → copy the token from the top of the page (one token covers all your subdomains). Paste into `config.env` as `DUCKDNS_TOKEN`.

Verify the token works:
```
curl "https://www.duckdns.org/update?domains=${DUCKDNS_HOST%.duckdns.org}&token=${DUCKDNS_TOKEN}&txt=test"
# Expected output: OK
```

### 3. FritzBox port-forward

FritzBox UI → Internet → Permit Access → Port Sharing → Add:
- Protocol: TCP
- External port: 8443
- Internal device: the LXC at the IP from `LXC_IP_CIDR` (default `192.168.10.200`)
- Internal port: 8443

Save. The forward is persistent across reboots.

### 4. Proxmox API token

If you don't already have one: Proxmox UI → Datacenter → Permissions → API Tokens → Add. Uncheck "Privilege Separation" so the token inherits the user's permissions. Copy the token ID and secret into `config.env`.

### 5. Debian 12 template

The deploy script checks for the template and aborts with instructions if missing. To pre-download via the Proxmox UI:
- Node → local → CT Templates → Templates → search "debian-12-standard" → Download.

Or via SSH on the Proxmox host:
```
pveam update && pveam download local debian-12-standard
```

### 6. SSH key

The Mac's `~/.ssh/id_rsa.pub` is injected into the LXC for passwordless SSH. If absent: `ssh-keygen -t ed25519` first.

## Deploy

```bash
cd infra/rolly
cp config.env.example config.env
# Edit config.env with your real values (see comments in the file)
./deploy.sh
```

The first run takes ~2-3 minutes. Subsequent runs (after `git push`) are ~30 seconds and only refresh code + restart services.

At the end, `deploy.sh` prints the exact `setWebhook` command. Run it once. Then `/start` your bot in Telegram.

## Updating

```bash
# Just re-run deploy.sh — it git-pulls the LXC's checkout and restarts the service
./deploy.sh
```

## Troubleshooting

### Bot doesn't reply / nothing in journal

```bash
ssh root@192.168.10.200
journalctl -u rolly -f
# Check that LM Studio is reachable from the LXC:
curl http://192.168.1.135:1234/v1/models
```

If LM Studio isn't reachable: verify FritzBox routes between 192.168.10 and 192.168.1.

### Caddy can't get a cert

```bash
ssh root@192.168.10.200
journalctl -u caddy -n 100
```

Common causes:
- `DUCKDNS_TOKEN` wrong (verify with the curl test in step 2)
- Port 8443 not forwarded in FritzBox (although DNS-01 doesn't need it for the cert itself — only for traffic)

### Webhook not delivering

```
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Look at `last_error_date`, `last_error_message`, and `pending_update_count`. If `last_error_message` mentions cert: the LE cert isn't issued yet (wait a minute, re-run setWebhook).

### Reset the LXC

```bash
# From the Mac
python3 .claude/skills/proxmox/scripts/proxmox_api.py delete-lxc <vmid> --force
./deploy.sh   # creates a fresh LXC
```

## Files in this directory

| File | Role |
|---|---|
| `deploy.sh` | Mac-side orchestrator: validates config, calls `proxmox_api.py create-lxc`, SCPs setup artifacts, runs setup-lxc.sh |
| `setup-lxc.sh` | Runs inside the LXC: installs deps, clones repo, builds/configures Caddy, writes systemd units, starts services |
| `config.env.example` | Template for `config.env` (gitignored) — fill once per machine |
| `Caddyfile.tmpl` | Caddy config template (rendered with `envsubst` during setup) |
| `rolly.service.tmpl` | systemd unit for the Bun bot |
| `caddy.service` | systemd unit for Caddy |
```

- [ ] **Step 2: Commit**

```bash
git add infra/rolly/README.md
git commit -m "docs(infra/rolly): add deployment README with manual setup steps"
```

---

## Task 13: Local dry-run validation (no live deploy yet)

This is a verification task — no code is written. Catches bugs before we touch real infrastructure.

- [ ] **Step 1: Verify all new Python tests pass**

Run: `pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v`
Expected: 11 passed.

- [ ] **Step 2: Verify the existing proxmox CLI didn't regress**

Run: `python3 .claude/skills/proxmox/scripts/proxmox_api.py --help`
Expected: usage line lists all new commands (templates, wait-task, create-lxc, delete-lxc) alongside the existing ones.

- [ ] **Step 3: Verify `create-lxc --help` is well-formed**

Run: `python3 .claude/skills/proxmox/scripts/proxmox_api.py create-lxc --help`
Expected: shows all flags (`--hostname`, `--template`, `--cores`, `--memory`, `--disk`, `--ip`, `--gateway`, `--ssh-key`, `--unprivileged`, `--privileged`, `--start`, `--no-start`, `--nameserver`, `--timeout`).

- [ ] **Step 4: Verify deploy.sh validates config (without real Proxmox calls)**

```bash
cd infra/rolly
cp config.env.example config.env
# Leave it mostly empty — should fail validation
./deploy.sh 2>&1 | head -5
```
Expected: clear error like `Missing required variable: PROXMOX_TOKEN_SECRET`. Restore real values before next step.

- [ ] **Step 5: Smoke-test against live Proxmox: list templates**

(This is a read-only call — safe to run.)
```bash
python3 .claude/skills/proxmox/scripts/proxmox_api.py --json templates pve --storage local
```
Expected: JSON array containing at least one entry with `debian-12-standard` in the volid. If empty: pre-download the template per README step 5 before continuing.

---

## Task 14: First live deploy (user-supervised)

This is the moment of truth. Run alongside the user, with the LXC console open in Proxmox UI as a fallback.

> **Note for the agent worker:** Do NOT run `./deploy.sh` autonomously. The user must run it themselves so they can respond to any prompt (SSH host-key acceptance, Proxmox auth, Telegram cert issuance, etc.). Same convention as cws-deploy.

- [ ] **Step 1: User rotates the Telegram bot token at @BotFather**

User-action. Wait for confirmation before continuing.

- [ ] **Step 2: User adds FritzBox port-forward 8443 → LXC IP:8443**

User-action. Wait for confirmation.

- [ ] **Step 3: User fills `infra/rolly/config.env`**

```bash
cd infra/rolly
cp config.env.example config.env
# Edit with values from steps 1, 2, and existing .env at repo root
```

- [ ] **Step 4: User runs `./deploy.sh`**

```bash
cd infra/rolly
./deploy.sh
```

Expected log markers:
- `▶ Loading infra/rolly/config.env` → `✓ Config validated`
- `▶ Verifying Proxmox API reachable` → `✓ Proxmox API OK`
- `▶ Checking for existing LXC` → `✓ No existing LXC found — will create`
- `▶ Creating LXC 'rolly'` → `✓ Created LXC vmid=<N>`
- `▶ Waiting for SSH` → `✓ SSH up after ~5-15 attempts`
- `▶ Running setup-lxc.sh inside LXC` (~90s)
- `▶ End-to-end health checks` → `✓ Public https://...:8443/health OK`
- `▶ Set the Telegram webhook by running:` followed by the curl command

Total runtime: ~2-3 minutes.

- [ ] **Step 5: User runs the printed `setWebhook` curl**

Expected response: `{"ok":true,"result":true,"description":"Webhook was set"}`

- [ ] **Step 6: User sends `/start` (or any text) to the bot in Telegram**

Expected: bot replies. Check `journalctl -u rolly -n 30` in the LXC if no reply.

- [ ] **Step 7: Verify the webhook stays healthy**

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```
Expected: `pending_update_count: 0`, no `last_error_message`.

- [ ] **Step 8: Final commit (if any drift)**

Most likely nothing to commit at this point. If the user discovered an issue and patched a script, commit the fix. Otherwise:

```bash
git status   # should be clean
git log --oneline -15  # all 12 task commits visible
```

---

## Verification Against Spec

Before declaring this plan complete, confirm each spec section maps to a task:

| Spec section | Covered by |
|---|---|
| §1 Goals 1–4 | Tasks 2–6 (skill ext.) + 7–12 (infra) + 14 (live) |
| §2 / §2.1 Architecture + Hardware | Implicit in task 8 (config.env defaults) |
| §3.1 Proxmox skill ext. | Tasks 1–6 |
| §3.2 infra/rolly layout | Tasks 7–12 |
| §3.3 Boundary contract | Task 11 deploy.sh only calls CLI; setup-lxc.sh has no Proxmox knowledge |
| §4.1 Manual one-time | Task 12 README + Task 14 steps 1–2 |
| §4.2 deploy.sh flow | Task 11 mirrors steps 1–10 |
| §4.3 setup-lxc.sh | Task 10 |
| §5.1 config.env | Task 8 |
| §5.2–5.4 templates | Task 9 |
| §6 Failure modes | Task 12 README "Troubleshooting" |
| §7 Security (token rotation, .env 600) | Task 14 step 1 + Task 10 `install -m 600` |
| §9 Rollout | Tasks 13–14 |
