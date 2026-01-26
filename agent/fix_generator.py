"""Fix generation via Claude API.

Analyzes errors and generates code fixes automatically.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .skill_config import get_skill_dir, get_skill_path, validate_file_path, SKILLS_BASE_PATH

logger = logging.getLogger(__name__)


async def generate_fix(
    error_type: str,
    error_message: str,
    skill: str,
    action: str,
    context: str,
    settings: Settings,
) -> dict[str, Any] | None:
    """Generate a fix for an error using Claude API.

    Args:
        error_type: Type of error (e.g., "ScriptError", "TimeoutExpired")
        error_message: The error message
        skill: Which skill failed
        action: Which action failed
        context: Additional context (command executed, etc.)
        settings: Application settings

    Returns:
        Dict with fix details including files to modify, or None if generation fails
    """
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY not configured")
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        logger.error("anthropic package not installed")
        return None

    # Load relevant source code for context
    source_context = _load_error_context(skill, action, settings)

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Use centralized skill paths
    skill_base_path = get_skill_dir(skill)
    skill_script_path = get_skill_path(skill)

    prompt = f"""Analysiere diesen Fehler und schlage einen Fix vor:

## Fehler
- **Typ:** {error_type}
- **Nachricht:** {error_message}
- **Skill:** {skill}
- **Aktion:** {action}
- **Kontext:** {context}

## Relevanter Quellcode
{source_context}

## WICHTIG: Projektstruktur

Skills befinden sich IMMER in `{SKILLS_BASE_PATH}/<skill-name>/`:
- Scripts: `{skill_base_path}scripts/`
- Dokumentation: `{skill_base_path}SKILL.md`

Der zu ändernde Skill befindet sich in: `{skill_base_path}`

## Aufgabe

Analysiere den Fehler und erstelle einen Fix. Der Fix sollte:
1. Das Problem korrekt identifizieren
2. Eine minimale, gezielte Änderung vorschlagen
3. Keine Breaking Changes einführen
4. Error-Handling verbessern wenn sinnvoll
5. **NIEMALS bestehenden Code komplett ersetzen - nur ändern was nötig ist**

## WICHTIG: Ausgabeformat

⚠️ **WICHTIG: old_string/new_string ist VERBOTEN!**
Verwende IMMER marker + insert_before ODER marker + insert.
Das System wird old_string automatisch ablehnen!

### MODUS 1: insert_before (BEVORZUGT für Error-Handling)
Fügt Code VOR einer Zeile ein. Ideal für try/except Wrapper.

```json
{{
  "analysis": "Kurze Analyse was das Problem ist",
  "fix_description": "Beschreibung was der Fix macht",
  "commit_message": "fix(scope): beschreibung",
  "edits": [
    {{
      "path": "{skill_script_path}",
      "marker": "def problematic_function(self):",
      "insert_before": "    # Error handling wrapper\\n"
    }}
  ],
  "confidence": 0.8
}}
```

### MODUS 2: insert (nach marker)
Fügt Code NACH einer Zeile ein. Ideal für zusätzliche Checks.

```json
{{
  "edits": [
    {{
      "path": "{skill_script_path}",
      "marker": "def __init__(self):",
      "insert": "        self.retry_count = 3\\n"
    }}
  ]
}}
```

## EDIT-REGELN:

1. **marker**: Eine EINDEUTIGE Zeile aus dem Code (z.B. Funktionsdefinition)
2. **insert_before**: Code der VOR dem marker eingefügt wird
3. **insert**: Code der NACH dem marker eingefügt wird
4. **Einrückung**: Achte auf korrekte Einrückung im eingefügten Code!

- analysis: 1-2 Sätze zur Fehlerursache
- fix_description: Was der Fix ändert
- commit_message: Conventional Commits Format
- edits: Array mit marker-basierten Edits (Pfade MÜSSEN mit `{skill_base_path}` beginnen!)
- confidence: 0.0-1.0 wie sicher du dir beim Fix bist

Bei niedriger Confidence (< 0.5) oder wenn der Fehler extern ist (API down, Netzwerk):
```json
{{
  "analysis": "Erklärung warum kein Code-Fix möglich",
  "fix_description": null,
  "commit_message": null,
  "edits": [],
  "confidence": 0.0
}}
```

Gib NUR das JSON zurück, keine weiteren Erklärungen."""

    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = message.content[0].text
        return _parse_fix_response(response_text)

    except Exception as e:
        logger.error(f"Error generating fix: {e}")
        return None


def _load_error_context(skill: str, action: str, settings: Settings) -> str:
    """Load relevant source code for error context.

    Args:
        skill: Skill name
        action: Action that failed
        settings: Application settings

    Returns:
        String with relevant source code
    """
    context_parts = []

    # Load skill script using centralized path
    skill_script_rel = get_skill_path(skill)
    skill_script = settings.project_root / skill_script_rel

    if skill_script.exists():
        try:
            content = skill_script.read_text()
            # Truncate if too long
            if len(content) > 8000:
                content = content[:8000] + "\n... (truncated)"
            # Use FULL RELATIVE PATH so Claude knows exactly where the file is
            context_parts.append(f"### Datei: `{skill_script_rel}`\n```python\n{content}\n```")
        except Exception as e:
            logger.warning(f"Failed to read skill script: {e}")

    # Load skill SKILL.md for understanding
    skill_dir = get_skill_dir(skill)
    skill_md = settings.project_root / skill_dir / "SKILL.md"
    if skill_md.exists():
        try:
            content = skill_md.read_text()
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"
            context_parts.append(f"### SKILL.md\n```markdown\n{content}\n```")
        except Exception as e:
            logger.warning(f"Failed to read SKILL.md: {e}")

    # Load relevant agent code if it's an agent error
    if skill == "agent" or not context_parts:
        agent_files = ["skill_executor.py", "intent_classifier.py", "main.py"]
        for filename in agent_files:
            agent_file = settings.project_root / "agent" / filename
            if agent_file.exists():
                try:
                    content = agent_file.read_text()
                    if len(content) > 4000:
                        content = content[:4000] + "\n... (truncated)"
                    context_parts.append(f"### agent/{filename}\n```python\n{content}\n```")
                except Exception:
                    pass

    return "\n\n".join(context_parts) if context_parts else "Kein Quellcode verfügbar."


def _parse_fix_response(response_text: str) -> dict[str, Any] | None:
    """Parse Claude's JSON response.

    Args:
        response_text: Claude's response

    Returns:
        Parsed fix data or None
    """
    # Try to extract JSON from response
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_str = response_text.strip()

    try:
        data = json.loads(json_str)

        # Validate required fields
        if "analysis" not in data:
            logger.error("Missing 'analysis' field in fix response")
            return None

        return {
            "analysis": data.get("analysis", ""),
            "fix_description": data.get("fix_description"),
            "commit_message": data.get("commit_message"),
            "edits": data.get("edits", []),
            "confidence": data.get("confidence", 0.0),
        }

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse fix JSON: {e}")
        logger.debug(f"Response was: {response_text[:1000]}")
        return None


async def apply_fix(fix_data: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Apply a generated fix to the codebase using targeted edits.

    Args:
        fix_data: Fix data from generate_fix() containing edits
        settings: Application settings

    Returns:
        Dict with applied files info
    """
    from .edit_utils import apply_edits

    edits = fix_data.get("edits", [])
    if not edits:
        return {"success": False, "error": "Keine Edits zum Anwenden"}

    # Validate all paths before applying
    for edit in edits:
        rel_path = edit.get("path", "")
        if not rel_path:
            continue

        is_valid, error_msg = validate_file_path(rel_path)
        if not is_valid:
            logger.error(f"Invalid path: {rel_path} - {error_msg}")
            return {"success": False, "error": error_msg}

    # Note: old_string/new_string is supported by edit_utils with fuzzy matching
    # We prefer marker/insert_before in the prompt, but accept old_string as fallback
    for i, edit in enumerate(edits):
        if "old_string" in edit and "marker" not in edit:
            logger.info(f"Edit {i} uses old_string/new_string (fuzzy matching will be applied)")

    # Apply edits using the shared utility
    result = apply_edits(edits, settings.project_root)

    if not result["success"]:
        errors = result.get("errors", [])
        error_msg = "; ".join(e.get("error", "Unknown error") for e in errors)
        return {"success": False, "error": error_msg}

    return {
        "success": True,
        "files": result.get("applied", []),
        "commit_message": fix_data.get("commit_message", "fix: auto-generated fix"),
    }
