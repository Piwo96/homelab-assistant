"""Tests for proxmox_api.py — uses unittest.mock to patch requests.request.

Run with: pytest .claude/skills/proxmox/scripts/test_proxmox_api.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make the script importable as a module
sys.path.insert(0, str(Path(__file__).parent))
import proxmox_api  # noqa: E402


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Provide dummy credentials so ProxmoxAPI() construction doesn't fail."""
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
    # Verify endpoint includes content=vztmpl filter (sent in URL query string)
    method = mock_req.call_args.args[0]
    url = mock_req.call_args.args[1]
    assert method == "GET"
    assert "content=vztmpl" in url


def test_templates_cli_dispatch(monkeypatch, capsys):
    """End-to-end: invoking via main() with mocked HTTP returns JSON."""
    sample_data = [
        {"volid": "local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst",
         "format": "tzst", "size": 200000000}
    ]
    monkeypatch.setattr(sys, "argv",
                        ["proxmox_api.py", "--json", "templates", "pve"])
    # main() validates the node by calling get_nodes() first, then runs list_templates()
    responses = [
        _mock_response({"data": [{"node": "pve"}]}),   # get_nodes() for node validation
        _mock_response({"data": sample_data}),          # list_templates() actual call
    ]
    with patch("proxmox_api.requests.request", side_effect=responses):
        proxmox_api.main()
    out = capsys.readouterr().out
    assert "debian-12-standard" in out


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
