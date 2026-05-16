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
