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
