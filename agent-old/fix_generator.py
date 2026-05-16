"""Fix generation via Claude API.

Analyzes errors and generates code fixes automatically.
"""

import json
import logging
import py_compile
import re
from pathlib import Path
from typing import Any, Optional

from .config import Settings
from .skill_config import get_skill_dir, get_skill_path, validate_file_path, SKILLS_BASE_PATH

logger = logging.getLogger(__name__)


def validate_python_syntax(file_path: Path) -> tuple[bool, str | None]:
    """Validate Python file syntax before committing.

    Args:
        file_path: Path to the Python file

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not file_path.suffix == ".py":
        return True, None  # Not a Python file, skip validation

    try:
        py_compile.compile(str(file_path), doraise=True)
        return True, None
    except py_compile.PyCompileError as e:
        return False, str(e)


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

    # Load relevant source code for context (pass error_message for targeted extraction)
    source_context = _load_error_context(skill, action, settings, error_message)

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


def _extract_relevant_sections(content: str, action: str, error_message: str, budget: int = 60000) -> str:
    """Extract error-relevant sections from a large source file.

    Instead of blind truncation, this finds the code sections most likely
    related to the error and returns them with line numbers.

    Args:
        content: Full file content
        action: The action that failed (e.g., "events")
        error_message: The error message for keyword extraction
        budget: Maximum characters to return

    Returns:
        Extracted sections with line numbers and separator comments
    """
    lines = content.splitlines()

    # Collect line ranges to include (set of line indices)
    important_lines: set[int] = set()

    # 1. Always include imports and top-level definitions (first 40 lines)
    for i in range(min(40, len(lines))):
        important_lines.add(i)

    # 2. Find the action handler: prioritize exact action == "events" matches
    exact_patterns = [f'action == "{action}"', f"action == '{action}'"]
    broad_pattern = f'"{action}"'
    exact_match_lines: list[int] = []

    for i, line in enumerate(lines):
        if any(p in line for p in exact_patterns):
            exact_match_lines.append(i)
            # Exact action handler: wide context (±50 lines to capture full branch)
            for j in range(max(0, i - 15), min(len(lines), i + 50)):
                important_lines.add(j)
        elif broad_pattern in line:
            # Broad mention: narrow context (±10 lines)
            for j in range(max(0, i - 5), min(len(lines), i + 10)):
                important_lines.add(j)

    # 3. Find keywords from the error message (function names, variable names)
    error_keywords = set()
    for word in re.findall(r"'(\w+)'|\"(\w+)\"|(\w+Error)", error_message):
        for w in word:
            if w and len(w) > 3:
                error_keywords.add(w)
    # Also look for .replace, .attribute patterns from AttributeError
    attr_match = re.search(r"'(\w+)' object has no attribute '(\w+)'", error_message)
    if attr_match:
        error_keywords.add(attr_match.group(2))  # The missing attribute

    for i, line in enumerate(lines):
        if any(kw in line for kw in error_keywords):
            for j in range(max(0, i - 5), min(len(lines), i + 15)):
                important_lines.add(j)

    # 4. Find private helper functions called from the exact action handler
    if exact_match_lines:
        # Build called_funcs ONLY from the exact action handler section
        handler_lines = set()
        for em in exact_match_lines:
            for j in range(max(0, em - 15), min(len(lines), em + 50)):
                handler_lines.add(j)
        handler_section = "\n".join(lines[i] for i in sorted(handler_lines) if i < len(lines))
        handler_called = set(re.findall(r'(\w+)\(', handler_section))

        # Anchor for nearby range: last exact match (most specific handler)
        anchor = exact_match_lines[-1]
        nearby_range = range(max(0, anchor - 150), min(len(lines), anchor + 150))

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped.startswith("def "):
                continue
            func_match = re.match(r'def\s+(\w+)', stripped)
            if not func_match:
                continue
            func_name = func_match.group(1)

            # Only include: private helpers called from handler, OR private funcs nearby
            is_called = func_name in handler_called
            is_nearby_private = i in nearby_range and func_name.startswith("_")
            if is_called or is_nearby_private:
                for j in range(i, min(len(lines), i + 30)):
                    important_lines.add(j)
                    if j > i and lines[j].strip() and not lines[j][0].isspace():
                        break

    # Build output: prioritize exact action matches, then helpers, then broad matches
    # This ensures the most relevant code isn't cut off by the budget

    def _format_range(line_indices: list[int]) -> str:
        """Format a contiguous range of lines with line numbers."""
        parts: list[str] = []
        prev = -2
        for idx in sorted(line_indices):
            if idx >= len(lines):
                continue
            if idx != prev + 1:
                if parts:
                    parts.append("")
                if idx > 0:
                    parts.append(f"# ... (Zeile {idx + 1}) ...")
            parts.append(f"{idx + 1:>4}| {lines[idx]}")
            prev = idx
        return "\n".join(parts)

    # Categorize lines by priority
    imports_set = set(i for i in important_lines if i < 40)
    # High priority: exact action handler + any functions called from it
    exact_set = set(i for i in important_lines
                    if any(abs(i - em) <= 50 for em in exact_match_lines))
    # Also include helper function bodies found by Step 4 as high priority
    # (they're directly referenced from the action handler)
    handler_helper_set = important_lines - imports_set - exact_set
    # Lines near the anchor (±150) are helpers, rest is broad context
    if exact_match_lines:
        anchor = exact_match_lines[-1]
        near_anchor = set(i for i in handler_helper_set if abs(i - anchor) <= 150)
    else:
        near_anchor = set()
    broad_set = handler_helper_set - near_anchor

    imports_lines = sorted(imports_set)
    exact_lines = sorted(exact_set)
    helper_lines = sorted(near_anchor)
    broad_lines = sorted(broad_set)

    result_parts: list[str] = []
    used_chars = 0

    for label, line_set in [("imports", imports_lines), ("action handler", exact_lines), ("helpers", helper_lines), ("context", broad_lines)]:
        if not line_set:
            continue
        section = _format_range(line_set)
        if used_chars + len(section) > budget:
            remaining = budget - used_chars
            if remaining > 200:
                section = section[:remaining] + "\n... (gekürzt)"
                result_parts.append(section)
            break
        result_parts.append(section)
        used_chars += len(section) + 2  # +2 for \n\n separator

    return "\n\n".join(result_parts)


def _load_error_context(skill: str, action: str, settings: Settings, error_message: str = "") -> str:
    """Load relevant source code for error context.

    For large files, extracts only the sections relevant to the error
    instead of blind truncation.

    Args:
        skill: Skill name
        action: Action that failed
        settings: Application settings
        error_message: The error message for targeted extraction

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
            if len(content) > 8000:
                # Large file: extract relevant sections instead of blind truncation
                content = _extract_relevant_sections(content, action, error_message)
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

    # Validate syntax of all modified Python files BEFORE returning success
    # This prevents committing corrupted code
    applied_files = result.get("applied", [])
    for rel_path in applied_files:
        file_path = settings.project_root / rel_path
        is_valid, syntax_error = validate_python_syntax(file_path)
        if not is_valid:
            logger.error(f"Syntax error in {rel_path}: {syntax_error}")
            return {
                "success": False,
                "error": f"Syntax-Fehler in {rel_path}: {syntax_error}",
                "syntax_error": True,
            }

    return {
        "success": True,
        "files": applied_files,
        "commit_message": fix_data.get("commit_message", "fix: auto-generated fix"),
    }
