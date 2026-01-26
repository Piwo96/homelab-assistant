"""Example generation for skills using LM Studio.

Automatically generates example phrases from SKILL.md files
for intent classification training.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GENERATE_PROMPT = """Analysiere diese Skill-Dokumentation und generiere Beispielphrasen.

## Skill-Dokumentation
{skill_content}

## Verfuegbare Commands
{commands}

## Aufgabe
Generiere 3-5 Beispielphrasen pro Command/Action die ein deutschsprachiger User nutzen wuerde.

**Wichtig:**
- Deutsche Alltagssprache, keine technischen Befehle
- Natuerliche Formulierungen wie "Zeig mir...", "Was ist...", "Mach..."
- Variationen: Fragen, Imperative, informelle Sprache
- Fuer actions mit Parametern: mindestens 1 Beispiel MIT args (entity_id, name, vmid, etc.)
- Keine generischen Phrasen die auf mehrere Skills passen

**Format (NUR JSON, keine Erklaerung):**
```json
{{
  "examples": [
    {{"phrase": "Zeig mir alle VMs", "action": "overview"}},
    {{"phrase": "Starte VM 100", "action": "start", "args": {{"vmid": 100}}}},
    {{"phrase": "Wie viel RAM hat der Server?", "action": "status"}}
  ]
}}
```

Antworte NUR mit dem JSON-Objekt."""


async def extract_examples_from_skill(
    skill_path: Path,
    lm_studio_url: str,
    lm_studio_model: str,
    commands: list[dict] | None = None,
) -> list[dict]:
    """Extract example phrases from a skill using LM Studio.

    Args:
        skill_path: Path to skill directory containing SKILL.md
        lm_studio_url: LM Studio API URL
        lm_studio_model: Model to use
        commands: Optional list of command dicts with name/description

    Returns:
        List of example dicts with phrase, action, and optional args
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        logger.warning(f"No SKILL.md found in {skill_path}")
        return []

    try:
        content = skill_md.read_text(encoding="utf-8")
        # Truncate if too long
        if len(content) > 6000:
            content = content[:6000] + "\n... (truncated)"
    except Exception as e:
        logger.warning(f"Failed to read {skill_md}: {e}")
        return []

    # Format commands for prompt
    commands_str = "Keine Commands definiert"
    if commands:
        commands_str = "\n".join([
            f"- {cmd.get('name', 'unknown')}: {cmd.get('description', '')}"
            for cmd in commands
        ])

    prompt = GENERATE_PROMPT.format(skill_content=content, commands=commands_str)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{lm_studio_url}/v1/chat/completions",
                json={
                    "model": lm_studio_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,  # Etwas mehr Kreativitaet fuer Variationen
                    "max_tokens": 2000,
                },
            )

            if response.status_code == 200:
                data = response.json()
                raw_result = data["choices"][0]["message"]["content"].strip()
                # Log raw response for debugging
                logger.debug(f"Raw LM response for {skill_path.name}: {raw_result[:500]}")
                # Strip thinking tags from thinking models
                result = _strip_thinking_tags(raw_result)
                if not result:
                    logger.warning(f"Response empty after stripping think tags. Raw: {raw_result[:300]}")
                examples = _parse_examples(result)
                logger.info(f"Generated {len(examples)} examples for {skill_path.name}")
                return examples
            else:
                logger.warning(f"LM Studio error: {response.status_code}")
                return []

    except httpx.TimeoutException:
        logger.warning(f"Timeout generating examples for {skill_path.name} (LM Studio not responding)")
        return []
    except httpx.ConnectError:
        logger.warning(f"Connection error generating examples for {skill_path.name} (LM Studio not reachable)")
        return []
    except Exception as e:
        logger.warning(f"Error generating examples for {skill_path.name}: {type(e).__name__}: {e}")
        return []


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> tags from thinking model output.

    Args:
        text: Raw model output that may contain thinking tags

    Returns:
        Text with thinking sections removed
    """
    # Remove <think>...</think> blocks (including multiline)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Also handle unclosed think tags (model cut off mid-thinking)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    return text.strip()


def _parse_examples(response: str) -> list[dict]:
    """Parse examples from LLM response.

    Args:
        response: LLM response text

    Returns:
        List of example dicts
    """
    # Try to find JSON object in response (with "examples" key)
    match = re.search(r'\{[\s\S]*"examples"[\s\S]*\}', response)
    if match:
        try:
            data = json.loads(match.group())
            examples = data.get("examples", [])
            # Validate structure
            valid_examples = []
            for ex in examples:
                if isinstance(ex, dict) and ex.get("phrase") and ex.get("action"):
                    example = {
                        "phrase": str(ex["phrase"]).strip(),
                        "action": str(ex["action"]).strip(),
                    }
                    # Include args if present and valid
                    if ex.get("args") and isinstance(ex["args"], dict):
                        example["args"] = ex["args"]
                    valid_examples.append(example)
            return valid_examples
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse examples JSON: {e}")

    # Try to find JSON array as fallback
    match = re.search(r'\[[\s\S]*\]', response)
    if match:
        try:
            examples = json.loads(match.group())
            valid_examples = []
            for ex in examples:
                if isinstance(ex, dict) and ex.get("phrase") and ex.get("action"):
                    example = {
                        "phrase": str(ex["phrase"]).strip(),
                        "action": str(ex["action"]).strip(),
                    }
                    if ex.get("args") and isinstance(ex["args"], dict):
                        example["args"] = ex["args"]
                    valid_examples.append(example)
            return valid_examples
        except json.JSONDecodeError:
            pass

    logger.warning(f"Failed to parse examples as JSON. Response (first 500 chars): {response[:500]}")
    return []


def load_examples(skill_path: Path) -> list[dict]:
    """Load examples from examples.json if it exists.

    Args:
        skill_path: Path to skill directory

    Returns:
        List of example dicts or empty list
    """
    examples_file = skill_path / "examples.json"
    if examples_file.exists():
        try:
            with open(examples_file) as f:
                data = json.load(f)
                if isinstance(data, dict) and "examples" in data:
                    return data["examples"]
                elif isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"Failed to load examples from {examples_file}: {e}")
    return []


def save_examples(skill_path: Path, examples: list[dict]) -> bool:
    """Save examples to examples.json.

    Args:
        skill_path: Path to skill directory
        examples: List of example dicts

    Returns:
        True if saved successfully
    """
    examples_file = skill_path / "examples.json"
    try:
        with open(examples_file, "w", encoding="utf-8") as f:
            json.dump({
                "examples": examples,
                "auto_generated": True
            }, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(examples)} examples to {examples_file}")
        return True
    except Exception as e:
        logger.warning(f"Failed to save examples: {e}")
        return False


def merge_examples(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new examples into existing, avoiding duplicates.

    Args:
        existing: Existing examples list
        new: New examples to add

    Returns:
        Merged list with no duplicate phrases
    """
    # Build set of existing phrases (lowercase for comparison)
    existing_phrases = {ex.get("phrase", "").lower().strip() for ex in existing}

    merged = list(existing)
    for ex in new:
        phrase = ex.get("phrase", "").lower().strip()
        if phrase and phrase not in existing_phrases:
            merged.append(ex)
            existing_phrases.add(phrase)

    return merged


async def ensure_examples(
    skill_path: Path,
    lm_studio_url: str,
    lm_studio_model: str,
    commands: list[dict] | None = None,
    force_regenerate: bool = False,
) -> list[dict]:
    """Ensure examples exist for a skill, generating if needed.

    Args:
        skill_path: Path to skill directory
        lm_studio_url: LM Studio API URL
        lm_studio_model: Model to use
        commands: Optional list of commands from skill
        force_regenerate: Force regeneration even if examples exist

    Returns:
        List of examples
    """
    # Try loading existing examples first
    if not force_regenerate:
        existing = load_examples(skill_path)
        if existing:
            return existing

    # Generate new examples
    examples = await extract_examples_from_skill(
        skill_path, lm_studio_url, lm_studio_model, commands
    )

    if examples:
        save_examples(skill_path, examples)

    return examples
