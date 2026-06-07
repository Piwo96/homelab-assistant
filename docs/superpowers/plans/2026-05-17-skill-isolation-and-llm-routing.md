# Skill Isolation & LLM Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** smart-home wird selbst-versorgendes Skill (kein Querverweis zu homeassistant), Agent bekommt Skill-Owned-Context-Pattern + Two-Stage-LLM-Routing mit Fast-Path bei 1 Skill.

**Architecture:** Smart-home reimplementiert nur die HA-REST-Methoden die es braucht (`ha_client.py`) und baut den Entity-Catalogue selbst (`catalogue.py`, neuer `context` Subcommand). Der Agent lädt Skill-Context lazy aus jedem Skill der das `context`-Command exponiert, und routet zwischen Skills via kleinem JSON-Output-LLM-Call (übersprungen wenn nur 1 Skill geladen ist). Embedding-Router + `BYPASS_ROUTER` werden ersatzlos gelöscht.

**Tech Stack:** TypeScript/Bun (`bun test`, `tsc --noEmit`), Python 3 (smart-home Skill via `python3` Subprozess), Vercel AI SDK (`generateText` für Stage-1- und Stage-2-Calls), Zod (env schema, tool schemas).

**Spec:** `docs/superpowers/specs/2026-05-17-skill-isolation-and-llm-routing-design.md`

---

## File Structure

**Created:**
- `.claude/skills/smart-home/scripts/ha_client.py` — minimaler HA-REST-Client
- `.claude/skills/smart-home/scripts/catalogue.py` — Markdown-Catalogue-Builder
- `.claude/skills/smart-home/scripts/skill_helpers.py` — Kopie für lokales `emit_help_json`
- `agent/src/skills/context-cache.ts` — TTL-Cache für `--json context`-Output pro Skill
- `agent/src/router/llm-router.ts` — Stage-1 LLM-basierter Skill-Picker
- `agent/tests/context-cache.test.ts` — Tests für Cache-Verhalten + Fehler-Fallback
- `agent/tests/llm-router.test.ts` — Tests für JSON-Parse-Robustheit

**Modified:**
- `.claude/skills/smart-home/scripts/smart_home_api.py` — sys.path-Hack raus, Imports auf `ha_client`, neuer `context` Subparser
- `agent/src/skills/loader.ts` — `hasContext` Detection, `context`-Command aus Tools rausfiltern
- `agent/src/skills/registry.ts` — Typ ergänzen (`hasContext: boolean`)
- `agent/src/pipeline/system-prompt.ts` — Signature: `contextBlocks: string[]` statt `entityCatalogue?: string`; Vokabular auf smart-home (`lights-status`/`rollos-status`/`klima-status`/`gerät-status` statt `entities`/`get-state`)
- `agent/src/pipeline/leak-recovery.ts` — Allowlist auf smart-home-Commands, `formatRecoveredResult` für smart-home-Result-Shape
- `agent/src/pipeline/handle-message.ts` — Routing-Block ersetzen (Fast-Path + Stage 1), `looksLikeLeakedReasoning`-Regex umstellen
- `agent/src/config/env.ts` — `EMBEDDING_MODEL` raus
- `agent/src/main.ts` — Catalogue-Plumbing raus, Context-Cache rein
- `agent/tests/handle-message.test.ts` — Fast-Path + LLM-Router Mock
- `agent/tests/leak-recovery.test.ts` — Fixtures auf smart-home

**Deleted:**
- `agent/src/router/semantic.ts`
- `agent/src/router/cache.ts`
- `agent/src/llm/embedding.ts`
- `agent/src/skills/ha-catalogue.ts`
- `agent/tests/semantic.test.ts`
- `agent/tests/cache.test.ts`
- `agent/tests/ha-catalogue.test.ts`

**Untouched:** `.claude/skills/homeassistant/` (Skill bleibt als Standalone-CLI nutzbar)

---

## Task 1: Schreibe `ha_client.py` (minimaler HA-REST-Client)

**Files:**
- Create: `.claude/skills/smart-home/scripts/ha_client.py`
- Reference: `.claude/skills/homeassistant/scripts/homeassistant_api.py` (Quelle der Methoden)

Smart-home nutzt nur 5 Methoden von HomeAssistantAPI: `get_states`, `get_state`, `call_service`, `render_template`, `entities_in_area`. Plus `load_env` Helper und Konstruktor. Alles andere (turn_on/off/toggle, list_*, history, logbook, get_config, set_state, fire_event, get_status, get_components, get_error_log) gehört zum homeassistant-Skill-Scope und kommt **nicht** mit.

- [ ] **Step 1: Datei anlegen mit Minimal-Surface**

```python
#!/usr/bin/env python3
"""Minimaler Home-Assistant-REST-Client für den smart-home Skill.

Reimplementiert NUR die Methoden, die smart_home_api.py / catalogue.py
tatsächlich aufrufen. Admin-Operationen (Automationen, Skripte, History,
Logbook, Config) sind absichtlich nicht enthalten — die gehören zum
homeassistant-Skill und sind kein Smart-Home-Alltag.
"""

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
        response = self.session.post(url, json={"template": template}, timeout=10)
        response.raise_for_status()
        return response.text

    def entities_in_area(self, area: str) -> list[str]:
        """entity_ids in einer HA-Area (display-name oder area_id)."""
        raw = self.render_template(f"{{{{ area_entities('{area}') }}}}")
        if isinstance(raw, str):
            import ast
            try:
                value = ast.literal_eval(raw)
                if isinstance(value, list):
                    return [str(x) for x in value]
            except (ValueError, SyntaxError):
                pass
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return []
```

- [ ] **Step 2: Datei ausführbar und syntaktisch valide**

Run: `python3 -c "import ast; ast.parse(open('.claude/skills/smart-home/scripts/ha_client.py').read())" && echo OK`
Expected: `OK`

- [ ] **Step 3: Smoke-Test gegen live HA (manuell, optional)**

Run:
```bash
cd .claude/skills/smart-home/scripts
python3 -c "from ha_client import HAClient; c = HAClient(); print(len(c.get_states()), 'states')"
```
Expected: positive Zahl, kein Stacktrace. Falls HA nicht erreichbar: OK weiterzumachen, der Live-Test kommt in Task 4.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/smart-home/scripts/ha_client.py
git commit -m "feat(skills/smart-home): minimal HA REST client, self-contained"
```

---

## Task 2: Kopiere `skill_helpers.py` in smart-home

**Files:**
- Create: `.claude/skills/smart-home/scripts/skill_helpers.py`
- Reference: `.claude/skills/homeassistant/scripts/skill_helpers.py`

smart_home_api.py braucht `emit_help_json` — heute kommt das via `sys.path`-Fallback aus `homeassistant/scripts`. Wir kopieren die Datei ins smart-home-Verzeichnis. Die Konvention ist stabil, parallele Kopien sind akzeptabel.

- [ ] **Step 1: Datei 1:1 kopieren**

Run:
```bash
cp .claude/skills/homeassistant/scripts/skill_helpers.py .claude/skills/smart-home/scripts/skill_helpers.py
```

- [ ] **Step 2: Verifizieren dass identisch**

Run: `diff .claude/skills/{homeassistant,smart-home}/scripts/skill_helpers.py`
Expected: keine Ausgabe (identisch)

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/smart-home/scripts/skill_helpers.py
git commit -m "feat(skills/smart-home): own copy of skill_helpers for self-containment"
```

---

## Task 3: Schreibe `catalogue.py` (Markdown-Builder)

**Files:**
- Create: `.claude/skills/smart-home/scripts/catalogue.py`
- Reference: `.claude/skills/homeassistant/scripts/homeassistant_catalogue.py`

Logik 1:1 wie heute (Entities → Domain → Etage → Area gruppiert), aber als Function `build_markdown(client) -> str` aufrufbar (statt CLI-Entry-Point), Import via `ha_client`, und mit selbst-tragendem Header (smart-home eigene Sektion, nicht mehr vom Agent gewrappt).

- [ ] **Step 1: Datei anlegen**

```python
#!/usr/bin/env python3
"""Baut den Entity-Catalogue für den smart-home System-Prompt-Context.

Wird von smart_home_api.py's `context` Subcommand aufgerufen. Output ist
self-contained Markdown — der Agent ketttet Skill-Context-Blocks nur noch
zusammen, keine zusätzliche Wrapper-Sektion.
"""

from collections import defaultdict
from datetime import datetime

from ha_client import HAClient


DEFAULT_DOMAINS = ["light", "switch", "cover", "climate", "scene", "script", "group"]

FLOOR_LABELS: dict[str, str] = {
    "kg": "KG (Kellergeschoss)",
    "eg": "EG (Erdgeschoss)",
    "og": "OG (Obergeschoss)",
    "dg": "DG (Dachgeschoss)",
    "aussen": "Außen",
}
FLOOR_ORDER = ["aussen", "kg", "eg", "og", "dg", "_other"]

DOMAIN_LABELS = {
    "light": "Lichter",
    "switch": "Schalter / Steckdosen",
    "cover": "Rollos / Jalousien",
    "climate": "Heizung / Klima",
    "scene": "Szenen",
    "script": "Skripte",
    "group": "Gruppen (bevorzugen für Sammelaktionen!)",
}


def floor_from_entity_id(entity_id: str) -> str:
    local = entity_id.split(".", 1)[-1]
    first = local.split("_", 1)[0]
    return first if first in FLOOR_LABELS else "_other"


def build_markdown(client: HAClient, domains: list[str] | None = None, max_per_area: int = 999) -> str:
    """Erzeuge den Catalogue-Markdown für den smart-home Skill."""
    domains = domains or DEFAULT_DOMAINS

    areas_raw = client.render_template("{{ areas() | sort | join(',') }}").strip()
    area_ids = [a.strip() for a in areas_raw.split(",") if a.strip()]
    area_names: dict[str, str] = {}
    for aid in area_ids:
        try:
            name = client.render_template(f"{{{{ area_name('{aid}') }}}}").strip()
            area_names[aid] = name or aid
        except Exception:
            area_names[aid] = aid

    entity_area: dict[str, str] = {}
    for aid in area_ids:
        for eid in client.entities_in_area(aid):
            entity_area[eid] = aid

    states = client.get_states()
    grouped: dict[str, dict[str, dict[str, list[tuple[str, str]]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))
    for s in states:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        if domain not in domains:
            continue
        friendly = s.get("attributes", {}).get("friendly_name") or eid
        floor = floor_from_entity_id(eid)
        aid = entity_area.get(eid) or "_unassigned"
        grouped[domain][floor][aid].append((eid, friendly))

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    out: list[str] = [
        f"BEKANNTE ENTITIES (smart-home, Snapshot {ts} — keine entity_ids erfinden, immer aus dieser Liste wählen):",
        "",
    ]
    for domain in domains:
        floors = grouped.get(domain)
        if not floors:
            continue
        out.append(f"### {DOMAIN_LABELS.get(domain, domain)} ({domain})")
        for floor in FLOOR_ORDER:
            areas = floors.get(floor)
            if not areas:
                continue
            out.append(f"#### {FLOOR_LABELS.get(floor, 'Sonstige')}")
            area_sorted = sorted(areas.keys(), key=lambda a: area_names.get(a, a))
            for aid in area_sorted:
                label = area_names.get(aid, "(ohne Area)" if aid == "_unassigned" else aid)
                for eid, friendly in areas[aid][:max_per_area]:
                    out.append(f"- {label}: `{eid}` ({friendly})")
        out.append("")
    return "\n".join(out).rstrip()
```

- [ ] **Step 2: Syntax-Check**

Run: `python3 -c "import ast; ast.parse(open('.claude/skills/smart-home/scripts/catalogue.py').read())" && echo OK`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/smart-home/scripts/catalogue.py
git commit -m "feat(skills/smart-home): own catalogue builder, no homeassistant dep"
```

---

## Task 4: Migriere `smart_home_api.py` auf eigene Imports + `context` Command

**Files:**
- Modify: `.claude/skills/smart-home/scripts/smart_home_api.py`

Drei Änderungen: sys.path-Hack raus, Import-Swap (`HomeAssistantAPI` → `HAClient`, mit Alias damit der Rest des Files keine Touch braucht), neuer `context` Subparser + Dispatch-Branch.

- [ ] **Step 1: sys.path-Hack und Cross-Skill-Import entfernen**

Open `.claude/skills/smart-home/scripts/smart_home_api.py:23-36` und ersetze diesen Block:

```python
import argparse
import json
import os
import sys
from typing import Any

# Pfad zum homeassistant Skill (Schwester-Verzeichnis) damit wir die rohe
# HA-API-Klasse importieren können ohne sie zu duplizieren.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HA_SCRIPTS = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", "homeassistant", "scripts"))
sys.path.insert(0, _HA_SCRIPTS)
sys.path.insert(0, _THIS_DIR)  # for skill_helpers shared by both skills

from homeassistant_api import HomeAssistantAPI  # type: ignore  # noqa: E402
```

durch:

```python
import argparse
import json
import os
import sys
from typing import Any

# smart-home ist self-contained: ha_client.py + catalogue.py + skill_helpers.py
# liegen alle im selben scripts/-Verzeichnis. Damit Python sie ohne package-
# Konfiguration findet, fügen wir _THIS_DIR zum sys.path hinzu.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from ha_client import HAClient as HomeAssistantAPI  # type: ignore  # noqa: E402
```

Das `as HomeAssistantAPI`-Alias hält den Rest der Datei (`api: HomeAssistantAPI` Annotations, Konstruktor-Aufruf) ohne weitere Touches funktional.

- [ ] **Step 2: `emit_help_json`-Fallback vereinfachen**

Open `smart_home_api.py:670-679` und ersetze:

```python
    if args.help_json:
        # Reuse the homeassistant skill's emitter so the format matches the
        # loader's HelpJsonScript shape exactly (including the `positional` flag).
        try:
            from skill_helpers import emit_help_json  # type: ignore
        except ImportError:
            sys.path.insert(0, _HA_SCRIPTS)
            from skill_helpers import emit_help_json  # type: ignore
        emit_help_json(parser)
        return 0
```

durch:

```python
    if args.help_json:
        from skill_helpers import emit_help_json  # type: ignore
        emit_help_json(parser)
        return 0
```

- [ ] **Step 3: `context` Subparser hinzufügen**

In `build_parser()` (vor `return p` am Ende von Z.661-663) folgenden Block einfügen:

```python
    # ----- Context (für Agent System-Prompt) -----
    sub.add_parser(
        "context",
        help=("Liefert den Entity-Catalogue als Markdown-Block für den "
              "Agent-System-Prompt. Wird vom Agent beim Routing auf smart-home "
              "abgerufen und gecached. NICHT als User-Tool nutzen."),
    )
```

- [ ] **Step 4: `context` Dispatch in `main()`**

In `main()` (vor dem `else` der Command-Kette, also vor Z.727 `else: print(f"Unknown command: ...")`):

```python
        elif args.command == "context":
            from catalogue import build_markdown
            result = {"markdown": build_markdown(api)}
```

- [ ] **Step 5: Schreib-Erkennung für `context` (read-only)**

Direkt nach dem `subparsers_action.add_parser("context", ...)` aus Step 3 KEIN `set_defaults(_is_write=True)` — `context` ist read-only und soll als read erkannt werden.

(Keine Code-Änderung nötig — argparse default ist write=False. Step explizit aufgeführt damit klar ist dass das nicht vergessen werden darf.)

- [ ] **Step 6: --help-json Output verifizieren (enthält `context`, korrekt geshaped)**

Run:
```bash
cd .claude/skills/smart-home/scripts
python3 smart_home_api.py --help-json | python3 -c "import json, sys; d = json.load(sys.stdin); assert 'context' in d['commands'], d['commands'].keys(); print('OK')"
```
Expected: `OK`

- [ ] **Step 7: `context` Command produziert valides JSON mit Markdown**

Run (gegen live HA — kann scheitern wenn HA aus, dann manuell überspringen):
```bash
cd .claude/skills/smart-home/scripts
python3 smart_home_api.py --json context | python3 -c "import json, sys; d = json.load(sys.stdin); assert 'markdown' in d and 'BEKANNTE ENTITIES' in d['markdown']; print('OK,', len(d['markdown']), 'chars')"
```
Expected: `OK, <n> chars` (mehrere tausend Chars realistisch)

- [ ] **Step 8: Smoke-Test existierender Commands (1 read + 1 write)**

Run (gegen live HA, kein write ausführen):
```bash
cd .claude/skills/smart-home/scripts
python3 smart_home_api.py --json lights-status --where OG | python3 -c "import json, sys; d = json.load(sys.stdin); assert d.get('ok') is True; print('lights-status OK:', d['count'], 'lights')"
```
Expected: `lights-status OK: <n> lights`

(Write-Test optional — wenn skip, wird in Task 14 beim Deploy-Smoke abgedeckt.)

- [ ] **Step 9: Commit**

```bash
git add .claude/skills/smart-home/scripts/smart_home_api.py
git commit -m "refactor(skills/smart-home): drop cross-skill imports, add context subcommand"
```

---

## Task 5: Erweitere `LoadedSkill` Typ um `hasContext`

**Files:**
- Modify: `agent/src/skills/loader.ts`
- Modify: `agent/src/skills/registry.ts`
- Test: `agent/tests/loader.test.ts`

Loader entdeckt `context` Command via `--help-json` und setzt das Flag. Das Command darf **nicht** als LLM-Tool registriert werden (sonst sieht das Modell es als wählbares Tool).

- [ ] **Step 1: Failing Test in `agent/tests/loader.test.ts`**

Run: `grep -n "describe\|it(" agent/tests/loader.test.ts | head -10` zuerst um Stil zu sehen.

Dann am Ende der `describe`-Block hinzufügen:

```ts
  it('sets hasContext=true when --help-json includes context command and filters it out from tools', async () => {
    // Mock script setup is shared by the existing tests above; check the
    // smart-home script which the project already provides on disk.
    const skills = await loadSkills(`${import.meta.dir}/../../.claude/skills`, ['smart-home']);
    expect(skills).toHaveLength(1);
    const smartHome = skills[0]!;
    expect(smartHome.hasContext).toBe(true);
    const toolNames = smartHome.tools.map(t => t.name);
    expect(toolNames).not.toContain('smart-home__context');
  });
```

- [ ] **Step 2: Test laufen lassen — soll fehlschlagen weil `hasContext` nicht existiert**

Run: `cd agent && bun test tests/loader.test.ts -t "hasContext"`
Expected: FAIL — `Property 'hasContext' does not exist on type 'LoadedSkill'`

- [ ] **Step 3: Typ ergänzen + Loader-Logik**

Edit `agent/src/skills/loader.ts:24-31` — `LoadedSkill` Interface:

```ts
export interface LoadedSkill {
  id: string;
  description: string;
  triggers: string[];
  intentHints: string[];
  scriptPaths: string[];
  tools: SkillTool[];
  /** True iff the skill exposes a `context` subcommand that the agent should
   *  fetch and inject into the system prompt when this skill is routed. */
  hasContext: boolean;
}
```

Edit `agent/src/skills/loader.ts:107-118` — tool-loop um `context` zu filtern und `hasContext` zu setzen:

```ts
      const stem = scriptStem(scriptPath);
      let hasContextForScript = false;
      for (const [cmdName, cmd] of Object.entries(helpJson.commands)) {
        if (cmdName === 'context') {
          hasContextForScript = true;
          continue; // context is a helper, not a user-callable tool
        }
        const positionalArgs = cmd.args.filter(a => a.positional).map(a => a.name);
        tools.push({
          name: `${stem}__${cmdName}`,
          scriptPath,
          command: cmdName,
          description: cmd.description || cmdName,
          schema: commandToZod(cmd),
          isWrite: cmd.is_write,
          positionalArgs,
        });
      }
      if (hasContextForScript) skillHasContext = true;
```

…wobei `skillHasContext` als `let skillHasContext = false;` direkt vor der `for (const scriptPath of scriptPaths)` Schleife (Z.98) deklariert werden muss, und beim `result.push({...})` (Z.121) als `hasContext: skillHasContext` ergänzt wird:

```ts
    let skillHasContext = false;
    for (const scriptPath of scriptPaths) {
      // ... existing logic with the modified tool loop above ...
    }

    result.push({
      id: frontmatter.name ?? name,
      description: frontmatter.description ?? '',
      triggers: frontmatter.triggers ?? [],
      intentHints: frontmatter.intent_hints ?? [],
      scriptPaths,
      tools,
      hasContext: skillHasContext,
    });
```

- [ ] **Step 4: `SkillRegistry` Typ-Updates falls nötig**

Run: `grep -n "LoadedSkill\|hasContext" agent/src/skills/registry.ts`. Falls `registry.ts` `LoadedSkill` nur weiterreicht (keine Felder destrukturiert): keine Änderung nötig. Falls Felder einzeln gehalten werden: `hasContext` mit propagieren.

- [ ] **Step 5: Tests laufen lassen — sollte grün sein**

Run: `cd agent && bun test tests/loader.test.ts`
Expected: PASS

- [ ] **Step 6: Auch typecheck**

Run: `cd agent && bun run typecheck`
Expected: keine Fehler

- [ ] **Step 7: Commit**

```bash
git add agent/src/skills/loader.ts agent/src/skills/registry.ts agent/tests/loader.test.ts
git commit -m "feat(agent/skills): detect hasContext via --help-json, filter from tools"
```

---

## Task 6: Schreibe `context-cache.ts` + Test

**Files:**
- Create: `agent/src/skills/context-cache.ts`
- Test: `agent/tests/context-cache.test.ts`

TTL-Cache: Lazy-Fetch beim ersten `get`, Background-Refresh nach TTL. Bei Fetch-Fehler: alten Wert behalten + warn-log.

- [ ] **Step 1: Failing Tests in `agent/tests/context-cache.test.ts`**

```ts
import { describe, it, expect } from 'bun:test';
import { createSkillContextCache } from '../src/skills/context-cache';

describe('SkillContextCache', () => {
  it('returns null for skills without context', async () => {
    const cache = createSkillContextCache({
      skills: [{ id: 'wol', hasContext: false }],
      fetch: async () => '',
      ttlMs: 1000,
    });
    expect(await cache.get('wol')).toBeNull();
  });

  it('fetches lazily on first get and caches', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 60_000,
    });
    expect(await cache.get('smart-home')).toBe('markdown-1');
    expect(await cache.get('smart-home')).toBe('markdown-1'); // cached
    expect(calls).toBe(1);
  });

  it('refetches after ttl expires', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { calls++; return `markdown-${calls}`; },
      ttlMs: 10,
    });
    expect(await cache.get('smart-home')).toBe('markdown-1');
    await new Promise(r => setTimeout(r, 20));
    expect(await cache.get('smart-home')).toBe('markdown-2');
  });

  it('keeps previous value when fetch fails', async () => {
    let calls = 0;
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => {
        calls++;
        if (calls === 1) return 'good';
        throw new Error('HA unreachable');
      },
      ttlMs: 10,
    });
    expect(await cache.get('smart-home')).toBe('good');
    await new Promise(r => setTimeout(r, 20));
    // 2nd fetch throws; we should still return the cached value.
    expect(await cache.get('smart-home')).toBe('good');
  });

  it('returns null on first-fetch failure (no previous value)', async () => {
    const cache = createSkillContextCache({
      skills: [{ id: 'smart-home', hasContext: true }],
      fetch: async () => { throw new Error('boom'); },
      ttlMs: 1000,
    });
    expect(await cache.get('smart-home')).toBeNull();
  });
});
```

- [ ] **Step 2: Test laufen lassen — soll fehlschlagen (Module fehlt)**

Run: `cd agent && bun test tests/context-cache.test.ts`
Expected: FAIL — Module not found

- [ ] **Step 3: Implementation**

```ts
import { log } from '../utils/logger';

export interface SkillContextCacheOpts {
  skills: ReadonlyArray<{ id: string; hasContext: boolean }>;
  /** Fetch a fresh markdown block for the skill. Throws on failure. */
  fetch: (skillId: string) => Promise<string>;
  /** Cache TTL in ms; entries older than this are refetched on the next get(). */
  ttlMs: number;
}

export interface SkillContextCache {
  get(skillId: string): Promise<string | null>;
}

interface Entry {
  markdown: string;
  fetchedAt: number;
}

export function createSkillContextCache(opts: SkillContextCacheOpts): SkillContextCache {
  const hasContextById = new Map(opts.skills.map(s => [s.id, s.hasContext] as const));
  const entries = new Map<string, Entry>();
  // Coalesce concurrent fetches for the same skill so a burst of requests
  // doesn't trigger N parallel python subprocesses.
  const inflight = new Map<string, Promise<string | null>>();

  async function fetchOnce(skillId: string): Promise<string | null> {
    const existing = inflight.get(skillId);
    if (existing) return existing;
    const p = (async () => {
      try {
        const md = await opts.fetch(skillId);
        entries.set(skillId, { markdown: md, fetchedAt: Date.now() });
        return md;
      } catch (err) {
        const prev = entries.get(skillId);
        if (prev) {
          log.warn('skill_context_refresh_failed_keeping_old', { skillId, err: String(err) });
          return prev.markdown;
        }
        log.warn('skill_context_fetch_failed_no_prior_value', { skillId, err: String(err) });
        return null;
      } finally {
        inflight.delete(skillId);
      }
    })();
    inflight.set(skillId, p);
    return p;
  }

  return {
    async get(skillId: string): Promise<string | null> {
      if (!hasContextById.get(skillId)) return null;
      const entry = entries.get(skillId);
      if (entry && Date.now() - entry.fetchedAt < opts.ttlMs) {
        return entry.markdown;
      }
      return fetchOnce(skillId);
    },
  };
}
```

- [ ] **Step 4: Tests grün**

Run: `cd agent && bun test tests/context-cache.test.ts`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/src/skills/context-cache.ts agent/tests/context-cache.test.ts
git commit -m "feat(agent/skills): TTL-driven skill context cache"
```

---

## Task 7: Schreibe `llm-router.ts` + Test

**Files:**
- Create: `agent/src/router/llm-router.ts`
- Test: `agent/tests/llm-router.test.ts`

Stage-1-Router: nimmt User-Message, letzte 3 Turns, Skill-Frontmatter — returnt `{ skillId } | null`. JSON-Output, robustes Parsing (code fences, leerzeichen, garbage tolerieren).

- [ ] **Step 1: Failing Tests**

```ts
import { describe, it, expect } from 'bun:test';
import { parseRouterResponse, buildRouterPrompt } from '../src/router/llm-router';

describe('parseRouterResponse', () => {
  const candidates = ['smart-home', 'unifi-protect'];

  it('parses plain JSON {"skill":"smart-home"}', () => {
    expect(parseRouterResponse('{"skill":"smart-home"}', candidates)).toEqual({ skillId: 'smart-home' });
  });

  it('parses JSON wrapped in markdown code fences', () => {
    expect(parseRouterResponse('```json\n{"skill":"unifi-protect"}\n```', candidates))
      .toEqual({ skillId: 'unifi-protect' });
  });

  it('parses JSON with surrounding whitespace and prose', () => {
    expect(parseRouterResponse('Sure, here is the answer:\n  {"skill": "smart-home"}  \n', candidates))
      .toEqual({ skillId: 'smart-home' });
  });

  it('returns null for {"skill":null}', () => {
    expect(parseRouterResponse('{"skill":null}', candidates)).toBeNull();
  });

  it('returns null when skill name is unknown', () => {
    expect(parseRouterResponse('{"skill":"made-up"}', candidates)).toBeNull();
  });

  it('returns null when JSON is malformed', () => {
    expect(parseRouterResponse('not json at all', candidates)).toBeNull();
    expect(parseRouterResponse('{"skill"', candidates)).toBeNull();
  });
});

describe('buildRouterPrompt', () => {
  it('lists candidates and includes user message + recent context', () => {
    const prompt = buildRouterPrompt({
      msg: 'Licht im Wohnzimmer aus',
      recentMessages: [
        { role: 'user', content: 'Hallo' },
        { role: 'assistant', content: 'Hi, was brauchst du?' },
      ],
      candidates: [
        { id: 'smart-home', description: 'Lichter / Rollos / Heizung steuern' },
        { id: 'unifi-protect', description: 'Kameras und Bewegungen' },
      ],
    });
    expect(prompt).toContain('smart-home');
    expect(prompt).toContain('unifi-protect');
    expect(prompt).toContain('Licht im Wohnzimmer aus');
    expect(prompt).toContain('Hallo');
  });
});
```

- [ ] **Step 2: Test laufen lassen — soll fehlschlagen**

Run: `cd agent && bun test tests/llm-router.test.ts`
Expected: FAIL — Module not found

- [ ] **Step 3: Implementation**

```ts
import { generateText, type LanguageModel } from 'ai';
import { log } from '../utils/logger';

export interface RouterCandidate {
  id: string;
  description: string;
}

export interface RouterInput {
  msg: string;
  recentMessages: Array<{ role: 'user' | 'assistant'; content: string }>;
  candidates: RouterCandidate[];
}

export interface RouterResult {
  skillId: string;
}

export function buildRouterPrompt(input: RouterInput): string {
  const list = input.candidates.map(c => `- ${c.id}: ${c.description}`).join('\n');
  const recent = input.recentMessages
    .slice(-3)
    .map(m => `[${m.role}] ${m.content}`)
    .join('\n') || '(keine)';
  return `Du bist ein Skill-Router für einen Homelab-Assistenten. Wähle den passenden Skill für die User-Anfrage, oder null wenn keine Domain passt (Smalltalk, Frage außerhalb des Homelabs).

Skills:
${list}

Letzte Nachrichten (Kontext):
${recent}

Anfrage: "${input.msg}"

Antwort als JSON (keine Erklärung, kein Markdown):
{ "skill": "<name>" }  ODER  { "skill": null }`;
}

/** Strip ```json fences, find the first balanced {...} block, parse, validate. */
export function parseRouterResponse(raw: string, candidates: string[]): RouterResult | null {
  const stripped = raw.replace(/```(?:json)?/gi, '').trim();
  const firstBrace = stripped.indexOf('{');
  if (firstBrace < 0) return null;
  for (let end = stripped.length; end > firstBrace; end--) {
    const slice = stripped.slice(firstBrace, end);
    if (!slice.endsWith('}')) continue;
    try {
      const parsed = JSON.parse(slice) as { skill?: unknown };
      const skill = parsed?.skill;
      if (skill === null) return null;
      if (typeof skill === 'string' && candidates.includes(skill)) {
        return { skillId: skill };
      }
      return null; // unknown / wrong type
    } catch {
      // try a shorter window
    }
  }
  return null;
}

export interface LlmRouterDeps {
  model: LanguageModel;
}

export interface LlmRouter {
  pick(input: RouterInput): Promise<RouterResult | null>;
}

export function createLlmRouter(deps: LlmRouterDeps): LlmRouter {
  return {
    async pick(input: RouterInput): Promise<RouterResult | null> {
      const prompt = buildRouterPrompt(input);
      const t0 = Date.now();
      try {
        const { text } = await generateText({
          model: deps.model,
          prompt,
          temperature: 0,
          maxOutputTokens: 50,
        });
        const result = parseRouterResponse(text, input.candidates.map(c => c.id));
        log.info('llm_router_decision', { ms: Date.now() - t0, result: result?.skillId ?? null, textLen: text.length });
        return result;
      } catch (err) {
        log.warn('llm_router_call_failed', { err: String(err) });
        return null;
      }
    },
  };
}
```

- [ ] **Step 4: Tests grün**

Run: `cd agent && bun test tests/llm-router.test.ts`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add agent/src/router/llm-router.ts agent/tests/llm-router.test.ts
git commit -m "feat(agent/router): LLM-based skill router (Stage 1)"
```

---

## Task 8: Aktualisiere `system-prompt.ts` (Signature + Vokabular)

**Files:**
- Modify: `agent/src/pipeline/system-prompt.ts`
- Test: `agent/tests/system-prompt.test.ts`

Zwei Änderungen: (a) Signature nimmt `contextBlocks: string[]` statt `entityCatalogue?: string`, und (b) TOOLED_PROMPT-Vokabular auf smart-home-Tool-Namen.

- [ ] **Step 1: Failing Tests in `agent/tests/system-prompt.test.ts` ergänzen**

Vorhandene Datei öffnen und am Ende des `describe`-Blocks (oder in einem neuen) hinzufügen:

```ts
describe('buildSystemPrompt — smart-home vocabulary', () => {
  it('mentions smart-home status tools, not homeassistant entities/get-state', () => {
    const prompt = buildSystemPrompt({
      skills: [{ id: 'smart-home', description: 'Smart Home' }],
      hasTools: true,
      contextBlocks: [],
    });
    expect(prompt).toContain('lights-status');
    expect(prompt).not.toContain('entities --domain');
    expect(prompt).not.toMatch(/\bget-state\b/);
  });

  it('concatenates context blocks at the end', () => {
    const prompt = buildSystemPrompt({
      skills: [{ id: 'smart-home', description: 'Smart Home' }],
      hasTools: true,
      contextBlocks: ['BEKANNTE ENTITIES (smart-home, Snapshot 2026-05-17 — ...)\n- light.x'],
    });
    expect(prompt).toContain('BEKANNTE ENTITIES (smart-home');
    expect(prompt).toContain('light.x');
  });

  it('omits catalogue section when contextBlocks empty', () => {
    const prompt = buildSystemPrompt({
      skills: [{ id: 'smart-home', description: 'Smart Home' }],
      hasTools: true,
      contextBlocks: [],
    });
    expect(prompt).not.toContain('BEKANNTE ENTITIES');
  });
});
```

- [ ] **Step 2: Test laufen lassen — soll fehlschlagen (alte Signature)**

Run: `cd agent && bun test tests/system-prompt.test.ts -t "smart-home vocabulary"`
Expected: FAIL — TS-Fehler oder ungültige Property `contextBlocks`

- [ ] **Step 3: `BuildOptions` Interface umstellen (Z.6-15)**

Ersetze in `agent/src/pipeline/system-prompt.ts:6-15`:

```ts
export interface BuildOptions {
  skills: SkillSummary[];
  hasTools: boolean;
  /** Telegram first name of the current sender. Drives how the LLM
   *  addresses the user. Owner of the homelab is Philipp regardless. */
  firstName?: string;
  /** Optional snapshot of all controllable HA entities (Markdown, grouped by
   *  area). Injected verbatim so the model never has to guess entity_ids. */
  entityCatalogue?: string;
}
```

durch:

```ts
export interface BuildOptions {
  skills: SkillSummary[];
  hasTools: boolean;
  /** Telegram first name of the current sender. Drives how the LLM
   *  addresses the user. Owner of the homelab is Philipp regardless. */
  firstName?: string;
  /** Self-contained context blocks (markdown) contributed by routed skills.
   *  Each block has its own header — the prompt simply concatenates them. */
  contextBlocks: string[];
}
```

- [ ] **Step 4: TOOLED_PROMPT-Vokabular umschreiben**

Ersetze in `agent/src/pipeline/system-prompt.ts` die Sektion `KOLLEKTIVE ZUSTANDS-ABFRAGEN ...` (Z.46-49) durch:

```ts
KOLLEKTIVE ZUSTANDS-ABFRAGEN ("welche X sind an/aus/offen/zu/...", "was ist gerade alles an"):
- IMMER mit EINEM einzigen Status-Tool lösen: lights-status / rollos-status / klima-status, optional mit --where (Etage/Area/Group) und --state on/off (nur für lights-status).
- NIEMALS einzelne gerät-status-Calls aufreihen — das ist ineffizient, fehleranfällig und überschreitet schnell das Output-Budget.
- Die BEKANNTE-ENTITIES-Liste unten dient nur dazu spezifische entity_ids für einzelne Aktionen nachzuschlagen, NICHT um sie alle einzeln durchzugehen.
```

Ersetze die Sektion `ZUSTANDS-WISSEN IST NIE STATISCH:` (Z.56-59):

```ts
ZUSTANDS-WISSEN IST NIE STATISCH:
- Die BEKANNTE-ENTITIES-Liste enthält NUR Namen + IDs, KEINE aktuellen Zustände. Erfinde NIEMALS einen aktuellen Zustand ("ist offen", "ist an", "ist auf 50%") aus dieser Liste.
- Jede Status-Frage ("ist X an?", "wie weit ist X?", "welche X sind {Zustand}?") MUSS per *-status-Tool (lights-status / rollos-status / klima-status mit --where für gezielte Abfrage) ODER gerät-status (für 1 spezifische entity_id) live geprüft werden.
- Antwort ohne vorherigen Tool-Call zum aktuellen Zustand ist ein Fehler.
```

- [ ] **Step 5: `catalogueBlock` Helper raus, `buildSystemPrompt` umverdrahten**

Ersetze in `agent/src/pipeline/system-prompt.ts:97-117` (von `function catalogueBlock` bis Ende von `buildSystemPrompt`):

```ts
export function buildSystemPrompt(opts: BuildOptions): string {
  const u = userLine(opts.firstName);
  if (!opts.hasTools) return SMALLTALK_PROMPT.replace('{user_line}', u);
  const list = opts.skills.map(s => `- ${s.id}: ${s.description}`).join('\n');
  const contextSection = opts.contextBlocks.length > 0
    ? `\n\n${opts.contextBlocks.join('\n\n')}`
    : '';
  return (TOOLED_PROMPT
    .replace('{user_line}', u)
    .replace('{skill_list}', list)
    .replace('{entity_catalogue}', '') // legacy placeholder, kept until template literal cleaned up
    + contextSection
  ).trim();
}
```

Außerdem entferne `{entity_catalogue}` aus dem TOOLED_PROMPT-String (Z.91, letzte Zeile):

```ts
Verfügbare Skill-Domains:
{skill_list}`;
```

(Der `${contextSection}`-Anhang ersetzt die alte Inline-Variable.)

- [ ] **Step 6: Tests grün + Typecheck**

Run: `cd agent && bun test tests/system-prompt.test.ts && bun run typecheck`
Expected: PASS, kein TS-Fehler.

Anmerkung: bestehende Tests die `entityCatalogue` setzen müssen ggf. auf `contextBlocks: [catalogue]` umgestellt werden. Falls solche Tests existieren, in diesem Step mit anpassen (Suche: `grep -n entityCatalogue agent/tests/system-prompt.test.ts`).

- [ ] **Step 7: Commit**

```bash
git add agent/src/pipeline/system-prompt.ts agent/tests/system-prompt.test.ts
git commit -m "refactor(agent/prompt): smart-home vocabulary, contextBlocks signature"
```

---

## Task 9: Aktualisiere `leak-recovery.ts` für smart-home-Tools

**Files:**
- Modify: `agent/src/pipeline/leak-recovery.ts`
- Test: `agent/tests/leak-recovery.test.ts`

Allowlist auf smart-home-Commands, `formatRecoveredResult` für smart-home's `{ok, action, entities_affected, ...}` Result-Shape, Doc-Comment auf smart-home umschreiben.

- [ ] **Step 1: Bestehende Tests im File anschauen + neue smart-home-Tests ergänzen**

In `agent/tests/leak-recovery.test.ts` die bestehenden homeassistant-bezogenen Tests **ersetzen**, nicht zusätzlich. Konkret:

```ts
import { describe, it, expect } from 'bun:test';
import { parseLeakedToolCall, formatRecoveredResult } from '../src/pipeline/leak-recovery';

describe('parseLeakedToolCall', () => {
  it('extracts from {tool_name, parameters} shape with smart-home prefix', () => {
    const parsed = parseLeakedToolCall(`\`\`\`json
{"tool_name": "smart-home_lights-status", "parameters": {"where": "OG"}}
\`\`\``);
    expect(parsed).toEqual({ toolName: 'smart-home__lights-status', args: { where: 'OG' } });
  });

  it('extracts from {tool_calls: [{function, args}]} shape', () => {
    const parsed = parseLeakedToolCall(`{
      "tool_calls": [
        { "function": "smart-home_rollos-status", "args": { "where": "DG" } }
      ]
    }`);
    expect(parsed?.toolName).toBe('smart-home__rollos-status');
    expect(parsed?.args).toEqual({ where: 'DG' });
  });

  it('normalizes underscores in the command part (lights_status → lights-status)', () => {
    const parsed = parseLeakedToolCall('{"tool_name":"smart-home_lights_status","parameters":{}}');
    expect(parsed?.toolName).toBe('smart-home__lights-status');
  });

  it('handles already-namespaced form smart-home__lights-on', () => {
    const parsed = parseLeakedToolCall('{"tool_name":"smart-home__lights-on","parameters":{"where":"Esstisch"}}');
    expect(parsed?.toolName).toBe('smart-home__lights-on');
  });

  it('returns null when no JSON found', () => {
    expect(parseLeakedToolCall('Ich denke das Licht ist an.')).toBeNull();
  });
});

describe('formatRecoveredResult', () => {
  it('formats successful lights-status with counts', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-status', args: { where: 'OG', state: 'on' } },
      { ok: true, action: 'lights-status', count: 3, lights: [
        { entity_id: 'light.og_kind_1', friendly_name: 'OG Kind 1', state: 'on', brightness: 200 },
        { entity_id: 'light.og_buero', friendly_name: 'OG Büro', state: 'on', brightness: null },
        { entity_id: 'light.og_bad', friendly_name: 'OG Bad', state: 'on', brightness: null },
      ]},
    );
    expect(reply).toContain('OG Kind 1');
    expect(reply.toLowerCase()).toContain('on');
  });

  it('formats successful write actions (lights-on) with affected count', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-on', args: { where: 'Wohnzimmer' } },
      { ok: true, action: 'lights-on', label: 'Wohnzimmer', match_kind: 'area',
        entities_affected: ['light.eg_wohnzimmer_decke', 'light.eg_wohnzimmer_steh'] },
    );
    expect(reply).toMatch(/wohnzimmer/i);
    expect(reply).toContain('2');
  });

  it('surfaces tool error message verbatim when ok=false', () => {
    const reply = formatRecoveredResult(
      { toolName: 'smart-home__lights-on', args: { where: 'foo' } },
      { ok: false, error: "Keine Lichter gefunden für 'foo'", match_kind: 'none' },
    );
    expect(reply).toContain("Keine Lichter gefunden für 'foo'");
  });
});
```

- [ ] **Step 2: Tests laufen lassen — sollten fehlschlagen (Allowlist + Formatter)**

Run: `cd agent && bun test tests/leak-recovery.test.ts`
Expected: FAIL — Allowlist enthält noch homeassistant-Commands, Formatter erkennt smart-home-Shape nicht.

- [ ] **Step 3: `RECOVERABLE_COMMANDS` Allowlist umschreiben**

Ersetze in `agent/src/pipeline/leak-recovery.ts:138-147`:

```ts
const RECOVERABLE_COMMANDS = new Set([
  // smart-home read/status
  'lights-status', 'rollos-status', 'klima-status', 'gerät-status',
  // smart-home write actions
  'lights-on', 'lights-off', 'lights-set',
  'rollos-open', 'rollos-close', 'rollos-set',
  'klima-set',
  // smart-home scene actions
  'szenen-aktivieren', 'szenen-liste',
  // smart-home macros
  'bereich-aus', 'etage-aus',
  // smart-home escape-hatches
  'gerät-an', 'gerät-aus', 'gerät-toggle',
]);
```

- [ ] **Step 4: `formatRecoveredResult` für smart-home-Shape umschreiben**

Ersetze in `agent/src/pipeline/leak-recovery.ts:106-132`:

```ts
/** Format a smart-home tool result as a short German reply. Smart-home
 *  commands return structured `{ok, action, entities_affected?, lights?,
 *  rollos?, klimas?, error?, label?, ...}` — we surface the key fields
 *  without needing a second LLM round-trip. */
export function formatRecoveredResult(call: RecoveredCall, result: unknown): string {
  if (!result || typeof result !== 'object') {
    return `Tool ${call.toolName} ausgeführt.`;
  }
  const r = result as Record<string, unknown>;
  if (r.ok === false) {
    const err = typeof r.error === 'string' ? r.error : 'Aktion fehlgeschlagen';
    return `⚠️ ${err}`;
  }
  const action = typeof r.action === 'string' ? r.action : (call.toolName.split('__')[1] ?? call.toolName);

  // Status-Listen: lights / rollos / klimas
  for (const key of ['lights', 'rollos', 'klimas'] as const) {
    if (Array.isArray(r[key])) {
      const list = r[key] as Array<{ friendly_name?: string; entity_id?: string; state?: string }>;
      if (list.length === 0) return `${action}: keine Treffer.`;
      if (list.length > 15) return `${list.length} Treffer — bitte enger eingrenzen (--where).`;
      return list.map(it => `• ${it.friendly_name ?? it.entity_id ?? '?'} — ${it.state ?? '?'}`).join('\n');
    }
  }

  // Write-Aktionen mit entities_affected
  if (Array.isArray(r.entities_affected)) {
    const n = (r.entities_affected as unknown[]).length;
    const label = typeof r.label === 'string' ? r.label : action;
    return `OK — ${action} auf "${label}" (${n} Entit${n === 1 ? 'y' : 'ies'}).`;
  }

  // Generischer Fallback
  return `OK — ${action}.`;
}
```

- [ ] **Step 5: Doc-Comment am Datei-Anfang aktualisieren**

Ersetze in `agent/src/pipeline/leak-recovery.ts:1-14`:

```ts
/**
 * Gemma occasionally dumps its intended tool call as a JSON code block in the
 * reply text instead of issuing a real function call. Three shapes observed
 * in prod / E2E tests:
 *
 *   {"tool_name": "smart-home_lights-status", "parameters": {...}}
 *   {"tool_calls": [{"function": "smart-home_rollos-status", "args": {...}}]}
 *   {"function": "smart-home_lights-on", "arguments": {...}}
 *
 * Rather than asking the user to retry, we parse what the model meant,
 * normalize the tool name back to the registry's `skill__command` form, and
 * execute it ourselves. The result is formatted with a small German template
 * so we don't need a second LLM round-trip.
 */
```

- [ ] **Step 6: `normalize`-Comment auf smart-home umschreiben**

Ersetze in `agent/src/pipeline/leak-recovery.ts:80-88`:

```ts
/** Normalize the tool name the model wrote into the registry's
 *  `skill__command` form. Two transforms needed:
 *   1. Skill→command separator: Gemma writes single underscore
 *      ("smart-home_lights-status") but the registry uses double
 *      ("smart-home__lights-status"); convert the first one.
 *   2. Command word boundary: Python argparse subcommands use HYPHENS
 *      ("lights-on", "rollos-status"); Gemma sometimes writes underscores
 *      ("lights_on", "rollos_status"). After splitting the skill prefix,
 *      convert remaining underscores in the command part. */
```

- [ ] **Step 7: Tests grün**

Run: `cd agent && bun test tests/leak-recovery.test.ts`
Expected: PASS (8 tests)

- [ ] **Step 8: Commit**

```bash
git add agent/src/pipeline/leak-recovery.ts agent/tests/leak-recovery.test.ts
git commit -m "refactor(agent/pipeline): rewrite leak-recovery for smart-home tools"
```

---

## Task 10: Refactor `handle-message.ts` Routing-Block

**Files:**
- Modify: `agent/src/pipeline/handle-message.ts`
- Test: `agent/tests/handle-message.test.ts`

Routing-Block (Z.178-205) durch Fast-Path + Stage-1 ersetzen. `HandleDeps` ändert sich: `embedQuery`, `skillEmbeddings`, `thresholds`, `entityCatalogue` raus; `llmRouter`, `contextCache` rein. `looksLikeLeakedReasoning` Regex auf smart-home.

- [ ] **Step 1: Failing Tests in `agent/tests/handle-message.test.ts` aktualisieren**

Bestehende Tests nutzen `embedQuery` / `skillEmbeddings` / `thresholds` — alle entfernen. Stattdessen `llmRouter.pick` mocken. Beispiel-Refactor des ersten Tests:

```ts
import { describe, it, expect, beforeEach } from 'bun:test';
import { Database } from 'bun:sqlite';
import { initDb } from '../src/memory/db';
import { handleMessage, type HandleDeps } from '../src/pipeline/handle-message';
import { SkillRegistry } from '../src/skills/registry';
import { z } from 'zod';
import type { LoadedSkill } from '../src/skills/loader';

let db: Database;
let registry: SkillRegistry;

beforeEach(() => {
  db = new Database(':memory:'); initDb(db);
  registry = new SkillRegistry();
  const skills: LoadedSkill[] = [{
    id: 'smart-home',
    description: 'Smart Home steuern',
    triggers: ['licht', 'lampe'],
    intentHints: [],
    scriptPaths: ['/fake/smart_home_api.py'],
    hasContext: true,
    tools: [{
      name: 'smart-home__lights-status',
      scriptPath: '/fake/smart_home_api.py',
      command: 'lights-status',
      description: 'Lichter Status',
      schema: z.object({}),
      isWrite: false,
      positionalArgs: [],
    }],
  }];
  registry.replaceAll(skills);
});

function baseDeps(overrides: Partial<HandleDeps> = {}): HandleDeps {
  return {
    db,
    registry,
    generate: async () => ({ text: 'OK', toolCalls: [], finishReason: 'stop' }),
    llmRouter: { pick: async () => ({ skillId: 'smart-home' }) },
    contextCache: { get: async () => null },
    ...overrides,
  };
}

describe('handleMessage — fast-path (single skill)', () => {
  it('skips llmRouter when only 1 skill is loaded', async () => {
    let routerCalls = 0;
    const deps = baseDeps({
      llmRouter: { pick: async () => { routerCalls++; return null; } },
      generate: async ({ tools }) => {
        expect(Object.keys(tools as object)).toContain('smart-home__lights-status');
        return { text: 'Status: alles ok', toolCalls: [], finishReason: 'stop' };
      },
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 1, chatId: 100, userId: 999, messageId: 1, text: 'welche Lichter sind an?', ts: 1,
    });
    expect(reply).toBe('Status: alles ok');
    expect(routerCalls).toBe(0);
  });

  it('injects skill context block when contextCache returns markdown', async () => {
    let receivedSystem = '';
    const deps = baseDeps({
      contextCache: { get: async () => 'BEKANNTE ENTITIES (smart-home, Snapshot ...)' },
      generate: async ({ system }) => {
        receivedSystem = system;
        return { text: 'OK', toolCalls: [], finishReason: 'stop' };
      },
    });
    await handleMessage(deps, {
      kind: 'text', updateId: 2, chatId: 100, userId: 999, messageId: 1, text: 'Licht im OG an', ts: 1,
    });
    expect(receivedSystem).toContain('BEKANNTE ENTITIES (smart-home');
  });
});

describe('handleMessage — multi-skill (router-driven)', () => {
  beforeEach(() => {
    // Add a second skill to force router-mode.
    const cur = registry.all();
    registry.replaceAll([...cur, {
      id: 'unifi-protect',
      description: 'Kameras',
      triggers: [],
      intentHints: [],
      scriptPaths: [],
      hasContext: false,
      tools: [{
        name: 'unifi-protect__cameras',
        scriptPath: '/fake/unifi_protect_api.py',
        command: 'cameras',
        description: 'list cameras',
        schema: z.object({}),
        isWrite: false,
        positionalArgs: [],
      }],
    }]);
  });

  it('calls llmRouter and only loads the selected skill\'s tools', async () => {
    let toolNames: string[] = [];
    const deps = baseDeps({
      llmRouter: { pick: async (input) => {
        expect(input.candidates.map(c => c.id).sort()).toEqual(['smart-home', 'unifi-protect']);
        return { skillId: 'smart-home' };
      }},
      generate: async ({ tools }) => {
        toolNames = Object.keys(tools as object);
        return { text: 'OK', toolCalls: [], finishReason: 'stop' };
      },
    });
    await handleMessage(deps, {
      kind: 'text', updateId: 3, chatId: 100, userId: 999, messageId: 1, text: 'licht an', ts: 1,
    });
    expect(toolNames).toEqual(['smart-home__lights-status']);
  });

  it('returns smalltalk reply when llmRouter returns null', async () => {
    const deps = baseDeps({
      llmRouter: { pick: async () => null },
      generate: async ({ tools }) => {
        expect(Object.keys(tools as object)).toHaveLength(0);
        return { text: 'Ich helfe beim Homelab — frag mich gern.', toolCalls: [], finishReason: 'stop' };
      },
    });
    const reply = await handleMessage(deps, {
      kind: 'text', updateId: 4, chatId: 100, userId: 999, messageId: 1, text: 'Wie geht es dir?', ts: 1,
    });
    expect(reply).toContain('Homelab');
  });
});
```

(Existierende Tests die `embedQuery`/`thresholds`/`skillEmbeddings` setzen → entsprechend auf das neue `baseDeps`-Schema migrieren oder löschen wenn das selbe Szenario im Fast-Path-Test abgedeckt wird.)

- [ ] **Step 2: Tests laufen lassen — sollten fehlschlagen**

Run: `cd agent && bun test tests/handle-message.test.ts`
Expected: FAIL — `HandleDeps` Felder nicht vorhanden, `LoadedSkill` braucht `hasContext`.

- [ ] **Step 3: `HandleDeps` Interface umstellen (Z.28-49)**

Ersetze in `agent/src/pipeline/handle-message.ts:28-49`:

```ts
export interface HandleDeps {
  db: Database;
  registry: SkillRegistry;
  generate: (input: GenerateInput) => Promise<GenerateOutput>;
  /** Stage-1 LLM-based skill picker. Used only when >1 skill is loaded;
   *  the fast-path (1 skill) skips this entirely. */
  llmRouter: LlmRouter;
  /** Lazy-loaded context blocks per skill, fetched via `--json context`. */
  contextCache: SkillContextCache;
  /** Optional: quick reachability check for LM Studio (returns true if up). */
  healthCheck?: () => Promise<boolean>;
  /** Optional: triggers Wake-on-LAN + waits until LM Studio answers again. */
  wakeGamingPc?: () => Promise<{ success: boolean; ms: number }>;
  /** Optional: side-channel to send a status message to the user mid-pipeline. */
  notifyStatus?: (chatId: number, text: string) => Promise<void>;
  /** Optional: resolve a Telegram voice file_id to its transcribed German text. */
  transcribeVoice?: (fileId: string) => Promise<string>;
}
```

…und am Anfang der Datei die fehlenden Imports ergänzen:

```ts
import type { LlmRouter } from '../router/llm-router';
import type { SkillContextCache } from '../skills/context-cache';
```

…und den nicht mehr benötigten Import entfernen:

```ts
// REMOVE: import { route, type Thresholds } from '../router/semantic';
```

- [ ] **Step 4: Routing-Block ersetzen (Z.178-205)**

Ersetze:

```ts
  let selectedSkills;
  if (bypassRouter) {
    selectedSkills = deps.registry.all();
    log.info('routing_bypassed', { skillCount: selectedSkills.length });
  } else {
    const tEmbed = Date.now();
    const queryEmbedding = await deps.embedQuery(update.text);
    log.info('embed_done', { ms: Date.now() - tEmbed, dim: queryEmbedding.length });

    const skills = deps.registry.all();
    const routable = skills
      .filter(s => deps.skillEmbeddings[s.id] !== undefined)
      .map(s => ({ id: s.id, embedding: deps.skillEmbeddings[s.id]! }));
    const routed = route(queryEmbedding, routable, deps.thresholds);
    log.info('routed', { band: routed.band, selected: routed.selectedIds, topScore: routed.scores[0]?.score });

    selectedSkills = deps.registry.all().filter(s => routed.selectedIds.includes(s.id));
  }
```

durch:

```ts
  const loaded = deps.registry.all();
  let selectedSkill: ReturnType<SkillRegistry['all']>[number] | null = null;
  if (loaded.length === 1) {
    // Fast-path: single skill, skip Stage 1.
    selectedSkill = loaded[0]!;
    log.info('routing_fast_path', { skillId: selectedSkill.id });
  } else if (loaded.length > 1) {
    const recent = history.slice(-3);
    const picked = await deps.llmRouter.pick({
      msg: update.text,
      recentMessages: recent,
      candidates: loaded.map(s => ({ id: s.id, description: s.description })),
    });
    if (picked) {
      selectedSkill = loaded.find(s => s.id === picked.skillId) ?? null;
    }
    log.info('routing_stage1', { picked: picked?.skillId ?? null, candidates: loaded.length });
  }

  const selectedSkills = selectedSkill ? [selectedSkill] : [];
```

…und `const bypassRouter = process.env.BYPASS_ROUTER === '1';` (Z.122) löschen.

Das Auslesen von `history` muss VOR dem Routing-Block passieren (heute steht der `recentMessages`-Aufruf weiter unten). Also die `const history = recentMessages(...)` Zeilen (Z.214-217) nach oben verschieben — direkt nach dem `appendMessage` von User-Msg (Z.153) und vor der LM-Studio-Reachability-Probe.

- [ ] **Step 5: System-Prompt-Build umverdrahten (Z.207-212)**

Ersetze:

```ts
  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
    ...(update.firstName !== undefined ? { firstName: update.firstName } : {}),
    ...(deps.entityCatalogue !== undefined ? { entityCatalogue: deps.entityCatalogue } : {}),
  });
```

durch:

```ts
  // Fetch context blocks for routed skills (only those with hasContext=true).
  const contextBlocks: string[] = [];
  for (const s of selectedSkills) {
    if (s.hasContext) {
      const md = await deps.contextCache.get(s.id);
      if (md) contextBlocks.push(md);
    }
  }

  const system = buildSystemPrompt({
    skills: selectedSkills.map(s => ({ id: s.id, description: s.description })),
    hasTools,
    contextBlocks,
    ...(update.firstName !== undefined ? { firstName: update.firstName } : {}),
  });
```

- [ ] **Step 6: `looksLikeLeakedReasoning` Regex auf smart-home (Z.71-74)**

Ersetze:

```ts
    /"function"\s*:\s*"homeassistant_/i,
```

durch:

```ts
    /"function"\s*:\s*"smart-home_/i,
```

- [ ] **Step 7: Comment-Update für `get-state-Schleife` (Z.253-257)**

Ersetze:

```ts
    // Tools liefen, aber das Modell hat keinen finalen Text produziert — meist
    // weil es nach ein paar Calls die Übersicht verloren hat. Häufigster
    // Auslöser: einzelne get-state-Schleife statt entities --state-Filter.
    reply = '🤔 Ich hab die Daten geholt aber konnte sie nicht zusammenfassen. Frag bitte spezifischer (z.B. "welche Lichter sind an?" statt "was ist alles an?").';
```

durch:

```ts
    // Tools liefen, aber das Modell hat keinen finalen Text produziert — meist
    // weil es nach ein paar Calls die Übersicht verloren hat. Häufigster
    // Auslöser: einzelne gerät-status-Calls aufgereiht statt lights-status/
    // rollos-status mit --where/--state.
    reply = '🤔 Ich hab die Daten geholt aber konnte sie nicht zusammenfassen. Frag bitte spezifischer (z.B. "welche Lichter sind an?" statt "was ist alles an?").';
```

- [ ] **Step 8: Tests grün**

Run: `cd agent && bun test tests/handle-message.test.ts`
Expected: PASS

- [ ] **Step 9: Typecheck**

Run: `cd agent && bun run typecheck`
Expected: keine Fehler.

- [ ] **Step 10: Commit**

```bash
git add agent/src/pipeline/handle-message.ts agent/tests/handle-message.test.ts
git commit -m "refactor(agent/pipeline): fast-path + Stage-1 LLM routing, drop embedding router"
```

---

## Task 11: Aktualisiere `env.ts` (EMBEDDING_MODEL raus)

**Files:**
- Modify: `agent/src/config/env.ts`
- Test: `agent/tests/env.test.ts`

- [ ] **Step 1: Test in `env.test.ts` — falls dort `EMBEDDING_MODEL` referenziert wird, anpassen**

Run: `grep -n "EMBEDDING_MODEL" agent/tests/env.test.ts`. Falls Treffer: in den Test-Cases entfernen. Falls keiner: skip.

- [ ] **Step 2: `EMBEDDING_MODEL` aus Schema löschen**

Edit `agent/src/config/env.ts:20` — löschen:

```ts
  EMBEDDING_MODEL: z.string().min(1).default('google/embedding-gemma-300m'),
```

- [ ] **Step 3: Tests + typecheck**

Run: `cd agent && bun test tests/env.test.ts && bun run typecheck`
Expected: PASS, kein TS-Fehler (`process.env.EMBEDDING_MODEL` darf nirgendwo mehr referenziert sein — das wird in den folgenden Tasks abgeräumt).

- [ ] **Step 4: Commit**

```bash
git add agent/src/config/env.ts agent/tests/env.test.ts
git commit -m "refactor(agent/env): drop EMBEDDING_MODEL — embedding router removed"
```

---

## Task 12: Refactor `main.ts` (Catalogue-Plumbing raus, Context-Cache rein)

**Files:**
- Modify: `agent/src/main.ts`

Streiche die gesamte Embedding-/Catalogue-/Bypass-Logik. Stelle `contextCache` + `llmRouter` Wiring auf.

- [ ] **Step 1: Imports aufräumen (Z.1-22)**

Ersetze in `agent/src/main.ts:1-23`:

```ts
import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from './config/env';
import { openDb } from './memory/db';
import { loadSkills } from './skills/loader';
import { SkillRegistry } from './skills/registry';
import { embed, embedMany } from './llm/embedding';
import { isLmStudioReachable } from './llm/health';
import { wakeGamingPc } from './wol/wake';
import { sendText } from './telegram/send';
import { downloadTelegramFile } from './telegram/download';
import { transcribeAudio } from './llm/transcribe';
import { fetchHaCatalogue, startCatalogueRefresh } from './skills/ha-catalogue';

// Refetch the HA entity catalogue every 30 min so new / renamed entities show
// up without a deploy. Failed refreshes keep the previous snapshot in place
// (see startCatalogueRefresh), so a transient HA blip never poisons the prompt.
const CATALOGUE_REFRESH_MS = 30 * 60 * 1000;
import { computeCacheKey, loadCache, saveCache } from './router/cache';
import { buildGenerator } from './llm/generate';
import { startServer } from './server';
import { log } from './utils/logger';
```

durch:

```ts
import { mkdir } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from './config/env';
import { openDb } from './memory/db';
import { loadSkills } from './skills/loader';
import { SkillRegistry } from './skills/registry';
import { isLmStudioReachable } from './llm/health';
import { wakeGamingPc } from './wol/wake';
import { sendText } from './telegram/send';
import { downloadTelegramFile } from './telegram/download';
import { transcribeAudio } from './llm/transcribe';
import { runSkillCommand } from './skills/executor';
import { createSkillContextCache } from './skills/context-cache';
import { createLlmRouter } from './router/llm-router';
import { buildGenerator } from './llm/generate';
import { lmStudioProvider } from './llm/lm-studio';
import { startServer } from './server';
import { log } from './utils/logger';

// Default TTL for skill-owned context (entity catalogue etc.). The cache
// keeps the previous value on fetch errors, so a transient HA blip never
// poisons the prompt.
const CONTEXT_TTL_MS = 30 * 60 * 1000;
```

- [ ] **Step 2: `main()` Body komplett ersetzen (Z.35-110)**

Ersetze:

```ts
async function main(): Promise<void> {
  const env = loadEnv();
  const dataDir = resolveRepoPath(env.DATA_DIR);
  const skillsRoot = resolveRepoPath(env.SKILLS_ROOT);
  await mkdir(dataDir, { recursive: true });
  // New agent uses its own DB file to avoid colliding with agent-old's
  // legacy conversations.db schema. Legacy data is intentionally not migrated.
  const db = openDb(join(dataDir, 'agent.db'));

  // smart-home is the user-facing domain layer; the homeassistant skill stays
  // on disk as the raw HA-API implementation but is no longer exposed as tools.
  const skills = await loadSkills(skillsRoot, ['smart-home']);
  if (skills.length === 0) throw new Error('No skills loaded');
  const registry = new SkillRegistry();
  registry.replaceAll(skills);

  const cacheable = skills.map(s => ({
    id: s.id,
    description: s.description,
    triggers: s.triggers,
    intentHints: s.intentHints,
    commandDescriptions: s.tools.map(t => t.description),
  }));
  const cacheKey = await computeCacheKey(env.EMBEDDING_MODEL, cacheable);
  const cachePath = join(dataDir, 'agent-embedding-cache.json');
  let cache = await loadCache(cachePath);
  if (!cache || cache.key !== cacheKey) {
    log.info('embedding_cache_rebuild');
    const inputs = skills.map(s => buildSkillEmbeddingInput(s));
    const vectors = await embedMany(inputs, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL });
    const bySkillId: Record<string, number[]> = {};
    skills.forEach((s, i) => { bySkillId[s.id] = vectors[i]!; });
    cache = { key: cacheKey, embeddingModel: env.EMBEDDING_MODEL, bySkillId };
    await saveCache(cachePath, cache);
  } else {
    log.info('embedding_cache_hit');
  }

  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });

  // Pull a snapshot of all controllable HA entities (lights, switches, covers,
  // climates, scenes, scripts) grouped by area. The agent injects this into
  // the system prompt so the LLM never has to guess entity_ids.
  const initialCatalogue = await fetchHaCatalogue(skillsRoot);

  const handleDeps: import('./pipeline/handle-message').HandleDeps = {
    db,
    registry,
    embedQuery: (text) => embed(text, { baseUrl: env.LM_STUDIO_URL, model: env.EMBEDDING_MODEL }),
    skillEmbeddings: cache.bySkillId,
    generate,
    thresholds: { high: 0.75, med: 0.4 },
    healthCheck: () => isLmStudioReachable({ baseUrl: env.LM_STUDIO_URL, timeoutMs: 3000 }),
    wakeGamingPc: () => wakeGamingPc({ skillsRoot, timeoutMs: 150_000 }),
    notifyStatus: async (chatId, text) => {
      await sendText({ botToken: env.TELEGRAM_BOT_TOKEN }, chatId, text);
    },
    transcribeVoice: async (fileId) => {
      const audio = await downloadTelegramFile({ botToken: env.TELEGRAM_BOT_TOKEN }, fileId);
      return transcribeAudio(
        { baseUrl: env.LM_STUDIO_URL, model: env.WHISPER_MODEL },
        { data: audio.data, filename: audio.filename, mimeType: audio.mimeType },
      );
    },
    ...(initialCatalogue ? { entityCatalogue: initialCatalogue } : {}),
  };

  // Background refresh: every CATALOGUE_REFRESH_MS, refetch and mutate
  // handleDeps.entityCatalogue in place. The pipeline reads deps.entityCatalogue
  // per-request, so the next message picks up the new snapshot automatically.
  startCatalogueRefresh(skillsRoot, CATALOGUE_REFRESH_MS, (fresh) => {
    handleDeps.entityCatalogue = fresh;
  });

  startServer({ env, db, handleDeps });
}
```

durch:

```ts
async function main(): Promise<void> {
  const env = loadEnv();
  const dataDir = resolveRepoPath(env.DATA_DIR);
  const skillsRoot = resolveRepoPath(env.SKILLS_ROOT);
  await mkdir(dataDir, { recursive: true });
  const db = openDb(join(dataDir, 'agent.db'));

  // smart-home is the user-facing domain layer; the homeassistant skill stays
  // on disk as a standalone CLI but is intentionally not loaded into the bot.
  const skills = await loadSkills(skillsRoot, ['smart-home']);
  if (skills.length === 0) throw new Error('No skills loaded');
  const registry = new SkillRegistry();
  registry.replaceAll(skills);

  const generate = buildGenerator({ baseUrl: env.LM_STUDIO_URL, modelId: env.LM_STUDIO_MODEL });

  // Skill-owned context: each skill with hasContext=true exposes `--json context`,
  // which the cache fetches lazily and refreshes every CONTEXT_TTL_MS.
  const contextCache = createSkillContextCache({
    skills: skills.map(s => ({ id: s.id, hasContext: s.hasContext })),
    fetch: async (skillId) => {
      const skill = skills.find(s => s.id === skillId);
      if (!skill || !skill.scriptPaths[0]) throw new Error(`No script for skill ${skillId}`);
      const t0 = Date.now();
      const res = await runSkillCommand(skill.scriptPaths[0], 'context', {}, { timeoutMs: 15_000 });
      if (!res.success) {
        throw new Error(`context command failed: exit=${res.exitCode} stderr=${res.stderr.slice(0, 200)}`);
      }
      const data = res.data as { markdown?: string } | undefined;
      if (!data || typeof data.markdown !== 'string') {
        throw new Error(`context command returned unexpected shape: ${res.stdout.slice(0, 200)}`);
      }
      log.info('skill_context_fetched', { skillId, ms: Date.now() - t0, chars: data.markdown.length });
      return data.markdown;
    },
    ttlMs: CONTEXT_TTL_MS,
  });

  // Stage-1 LLM router. Only called when >1 skill is loaded (handle-message
  // falls into the fast-path when there's a single skill).
  const llmRouter = createLlmRouter({
    model: lmStudioProvider({ baseUrl: env.LM_STUDIO_URL }).chatModel(env.LM_STUDIO_MODEL),
  });

  const handleDeps: import('./pipeline/handle-message').HandleDeps = {
    db,
    registry,
    generate,
    llmRouter,
    contextCache,
    healthCheck: () => isLmStudioReachable({ baseUrl: env.LM_STUDIO_URL, timeoutMs: 3000 }),
    wakeGamingPc: () => wakeGamingPc({ skillsRoot, timeoutMs: 150_000 }),
    notifyStatus: async (chatId, text) => {
      await sendText({ botToken: env.TELEGRAM_BOT_TOKEN }, chatId, text);
    },
    transcribeVoice: async (fileId) => {
      const audio = await downloadTelegramFile({ botToken: env.TELEGRAM_BOT_TOKEN }, fileId);
      return transcribeAudio(
        { baseUrl: env.LM_STUDIO_URL, model: env.WHISPER_MODEL },
        { data: audio.data, filename: audio.filename, mimeType: audio.mimeType },
      );
    },
  };

  startServer({ env, db, handleDeps });
}
```

- [ ] **Step 3: `buildSkillEmbeddingInput` löschen (Z.112-119)**

Die Function nicht mehr nötig:

```ts
function buildSkillEmbeddingInput(s: { description: string; triggers: string[]; intentHints: string[]; tools: Array<{ description: string }> }): string {
  return [
    s.description,
    s.triggers.length > 0 ? `Triggers: ${s.triggers.join(', ')}.` : '',
    s.intentHints.join('. '),
    `Commands: ${s.tools.map(t => t.description).join('. ')}.`,
  ].filter(Boolean).join(' ');
}
```

Komplett löschen.

- [ ] **Step 4: `lmStudioProvider`-Export verifizieren**

Run: `grep -n "export" agent/src/llm/lm-studio.ts | head`. Falls `lmStudioProvider` so heißt: OK. Falls anders (z.B. `createLmStudio`): in Step 2 entsprechend anpassen.

Falls die Datei ein einzelnes `createOpenAICompatible(...)` Ergebnis als named export hat: den Export-Namen im `import`-Statement und in `main.ts` ausrichten.

- [ ] **Step 5: Typecheck**

Run: `cd agent && bun run typecheck`
Expected: keine Fehler.

- [ ] **Step 6: Commit**

```bash
git add agent/src/main.ts
git commit -m "refactor(agent/main): wire context-cache + llm-router, drop embedding plumbing"
```

---

## Task 13: Lösche obsolete Files

**Files:**
- Delete: `agent/src/router/semantic.ts`
- Delete: `agent/src/router/cache.ts`
- Delete: `agent/src/llm/embedding.ts`
- Delete: `agent/src/skills/ha-catalogue.ts`
- Delete: `agent/tests/semantic.test.ts`
- Delete: `agent/tests/cache.test.ts`
- Delete: `agent/tests/ha-catalogue.test.ts`

- [ ] **Step 1: Letzte Reference-Suche (sicherstellen dass nichts mehr verlinkt)**

Run:
```bash
grep -rn "router/semantic\|router/cache\|llm/embedding\|skills/ha-catalogue\|fetchHaCatalogue\|startCatalogueRefresh\|embedMany\|computeCacheKey" agent/src/ agent/tests/ 2>/dev/null
```
Expected: keine Treffer (in Source). Falls Treffer: vorheriger Task hat Reference vergessen — fixen.

- [ ] **Step 2: Files löschen**

Run:
```bash
git rm agent/src/router/semantic.ts agent/src/router/cache.ts agent/src/llm/embedding.ts agent/src/skills/ha-catalogue.ts \
       agent/tests/semantic.test.ts agent/tests/cache.test.ts agent/tests/ha-catalogue.test.ts
```

- [ ] **Step 3: Falls `agent/src/router/` jetzt nur noch `llm-router.ts` enthält — Directory bleibt (kein Cleanup nötig).**

Run: `ls agent/src/router/`
Expected: `llm-router.ts`

- [ ] **Step 4: Full test suite + typecheck**

Run: `cd agent && bun run typecheck && bun test`
Expected: alle grün.

- [ ] **Step 5: Commit**

```bash
git commit -m "chore(agent): remove embedding router and ha-catalogue plumbing"
```

---

## Task 14: Manual smoke test + Deploy

**Files:**
- Touch: none (manual verification + deployment)

- [ ] **Step 1: Local dev-run starten (gegen lokale LM Studio + HA)**

Run (in `agent/`):
```bash
bun run dev
```
Expected: Startup-Logs zeigen `skill_context_fetched skillId=smart-home`, kein Crash.

- [ ] **Step 2: Telegram-Test (oder curl gegen /health)**

Run:
```bash
curl -s http://localhost:8080/health | jq .
```
Expected: `{"status":"ok",...}` o.ä.

Falls Telegram-Bot live: schicke "welche Lichter sind an?" — sollte `lights-status --state on` aufrufen und Liste zurückgeben.

- [ ] **Step 3: LXC redeploy**

Run:
```bash
cd infra/rolly && ./deploy.sh
```
Expected: idempotenter Deploy, keine Fehler.

- [ ] **Step 4: Im LXC `EMBEDDING_MODEL` und `BYPASS_ROUTER` aus `.env` entfernen (manuell)**

Run (auf der LXC):
```bash
ssh <lxc-host>
sudo -u rolly nano /opt/rolly/agent/.env
# Lösche Zeilen EMBEDDING_MODEL=... und BYPASS_ROUTER=...
sudo systemctl restart rolly
```

(Diese Vars sind nicht mehr im Schema — wenn drin, werden sie ignoriert; aber sauber ist sauber.)

- [ ] **Step 5: Optional `data/agent-embedding-cache.json` auf LXC löschen**

Run (auf der LXC):
```bash
sudo rm -f /opt/rolly/data/agent-embedding-cache.json
```

- [ ] **Step 6: Smoke-Test gegen produktiven Bot**

Auf Telegram folgende Sequenz testen:
1. `/start` — Welcome-Reply auf Deutsch, freundlich.
2. "welche Lichter sind an?" — Tool-Call `lights-status --state on`, Liste.
3. "Licht im EG aus" — `lights-off --where EG`, Bestätigung.
4. "wie geht's dir?" — Smalltalk-Antwort (akzeptiert dass es leicht weniger natürlich ist als unter SMALLTALK_PROMPT — siehe Spec Non-Goals).

Falls eine dieser Steps fehlschlägt: Logs auf der LXC checken (`journalctl -u rolly -f`), Issue isolieren, fixen, neues Commit + Redeploy.

- [ ] **Step 7: Final-Commit "Deploy abgeschlossen" (optional, nur falls Migration-Notes nötig)**

Falls Migration-Notes für `agent-old`/`README` aktualisiert werden sollen: dokumentieren. Sonst kein zusätzlicher Commit.

---

## Self-Review Checklist (after writing)

- [x] Jedes Spec-Goal hat einen Task:
  - smart-home self-contained → Tasks 1-4
  - homeassistant unberührt → kein Task (kein Touch)
  - Architektur für mehr Domain-Skills → Task 5 (`hasContext`), Task 6 (context-cache), Task 7 (llm-router)
  - Routing entscheidet pro Anfrage → Task 7, Task 10
  - Fast-Path bei 1 Skill → Task 10 Step 4
  - System-Prompt smart-home only → Task 8
  - Leak-Recovery smart-home only → Task 9
- [x] Keine Placeholder ("TBD", "TODO", "implement later") im Plan.
- [x] Typ-Konsistenz: `LoadedSkill.hasContext` ist in Task 5 definiert, in Task 6 (Cache) und Task 10 (handle-message) konsistent benutzt.
- [x] Tool-Namen konsistent: `smart-home__<command>` durchgängig (mit Hyphen im Skill-Namen, gleichzeitig zwei Unterstriche als Separator).
- [x] Alle Test-Steps haben echten Code, nicht "Write tests for the above".
- [x] Commit-Steps mit exakten Pfaden + Conventional-Commits-Style-Messages.

## Bemerkungen für den Executor

- **Reihenfolge**: Tasks 1-4 (Python) sind unabhängig vom TS-Refactor. Tasks 5-13 hängen sequenziell zusammen (Loader → Cache → Router → System-Prompt → Recovery → handle-message → main → cleanup).
- **`bun test` kann zwischen Tasks rot sein** weil Tasks 8/9/10/12 inkrementell auf neue Signaturen umstellen. Erst nach Task 13 muss die volle Suite wieder grün sein. Bei Subagent-Driven Execution: nicht zwischen Tasks Tests laufen lassen, sondern erst nach Task 13.
- **Falls in Task 12 Step 4 die Provider-Import-Form (`lmStudioProvider`) nicht stimmt**: kurz in `agent/src/llm/lm-studio.ts` reinschauen und Import-Namen ausrichten. `buildGenerator` reicht für Stage 2; Stage 1 könnte auch über `buildGenerator` laufen wenn der Direkt-Provider-Import friction macht. Pragmatisch entscheiden.
- **HA muss erreichbar sein** für Task 4 Step 7-8 und Task 14 Step 1. Falls HA aus: Steps können verschoben werden, aber der finale Smoke (Task 14 Step 6) ist nicht skippbar.
