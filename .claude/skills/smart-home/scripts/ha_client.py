#!/usr/bin/env python3
"""Minimaler Home-Assistant-REST-Client für den smart-home Skill.

Reimplementiert NUR die Methoden, die smart_home_api.py / catalogue.py
tatsächlich aufrufen. Admin-Operationen (Automationen, Skripte, History,
Logbook, Config) sind absichtlich nicht enthalten — die gehören zum
homeassistant-Skill und sind kein Smart-Home-Alltag.
"""

import ast
import os
import sys
from pathlib import Path
from typing import Any

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning  # type: ignore
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # type: ignore
except ImportError:
    print("Error: 'requests' library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def load_env() -> None:
    """Lade .env aus Repo-Root falls vorhanden — selbe Logik wie homeassistant_api."""
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


class HAClient:
    """Home Assistant REST API client (minimaler smart-home Scope)."""

    def __init__(
        self,
        host: str | None = None,
        token: str | None = None,
        port: int | None = None,
        ssl: bool | None = None,
        verify_ssl: bool | None = None,
    ) -> None:
        load_env()
        self.host = host or os.environ.get("HOMEASSISTANT_HOST", "homeassistant.local")
        self.token = token or os.environ.get("HOMEASSISTANT_TOKEN")
        self.port = port if port is not None else int(os.environ.get("HOMEASSISTANT_PORT", "8123"))
        self.ssl = ssl if ssl is not None else os.environ.get("HOMEASSISTANT_SSL", "false").lower() == "true"
        verify_env = os.environ.get("HOMEASSISTANT_VERIFY_SSL", "true").lower()
        self.verify_ssl = verify_ssl if verify_ssl is not None else verify_env == "true"
        if not self.token:
            raise RuntimeError("HOMEASSISTANT_TOKEN required")
        self.host = self.host.replace("http://", "").replace("https://", "")
        protocol = "https" if self.ssl else "http"
        self.base_url = f"{protocol}://{self.host}:{self.port}/api"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        self.session.verify = self.verify_ssl

    def _request(self, method: str, endpoint: str, data: dict | None = None, params: dict | None = None) -> Any:
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.request(method, url, json=data, params=params, timeout=30)
            response.raise_for_status()
            if response.text:
                return response.json()
            return {}
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise RuntimeError("Unauthorized. Check your access token.") from e
            elif e.response.status_code == 404:
                raise RuntimeError(f"Not found: {endpoint}") from e
            else:
                raise RuntimeError(f"HTTP Error: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"API error: {e}") from e

    def get_states(self) -> list[dict]:
        """Alle Entities mit state + attributes (group.*-Entities haben attributes.entity_id mit Members)."""
        return self._request("GET", "/states")

    def get_state(self, entity_id: str) -> dict:
        """Einzelne Entity — wirft RuntimeError bei 404 (Existenz-Check für escape-hatch)."""
        return self._request("GET", f"/states/{entity_id}")

    def call_service(self, domain: str, service: str, data: dict | None = None) -> list[dict]:
        """Service-Call mit entity_id-Existenz-Validierung (verhindert silent-success bei Tippfehlern)."""
        if data:
            target = data.get("entity_id")
            ids = target if isinstance(target, list) else [target] if isinstance(target, str) else []
            for eid in ids:
                self.get_state(eid)
        return self._request("POST", f"/services/{domain}/{service}", data)

    def render_template(self, template: str) -> str:
        """Server-side Jinja2-Rendering. Liefert Raw-Text (kein JSON)."""
        url = f"{self.base_url}/template"
        try:
            response = self.session.post(url, json={"template": template}, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            raise RuntimeError(f"Template render failed: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"API error: {e}") from e

    def entities_in_area(self, area: str) -> list[str]:
        """entity_ids in einer HA-Area (display-name oder area_id)."""
        safe_area = area.replace("'", "\\'")
        raw = self.render_template(f"{{{{ area_entities('{safe_area}') }}}}")
        if isinstance(raw, str):
            try:
                value = ast.literal_eval(raw)
                if isinstance(value, list):
                    return [str(x) for x in value]
            except (ValueError, SyntaxError):
                pass
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return []
