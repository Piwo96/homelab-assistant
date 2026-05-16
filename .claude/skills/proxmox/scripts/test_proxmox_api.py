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
