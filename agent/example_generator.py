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

GENERATE_PROMPT = """/no_think
Analysiere diese Skill-Dokumentation und generiere Beispielphrasen.

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
- Die Beispiele MUESSEN zum Skill passen (z.B. Kamera-Skill = Kamera-Phrasen, nicht VM-Phrasen)

**JSON-Format:**
```json
{{
  "examples": [
    {{"phrase": "<DEINE_PHRASE_HIER>", "action": "<COMMAND_NAME>"}},
    {{"phrase": "<PHRASE_MIT_PARAMETER>", "action": "<COMMAND>", "args": {{"<PARAM>": "<WERT>"}}}}
  ]
}}
```

KRITISCH:
- Ersetze die Platzhalter (<DEINE_PHRASE_HIER> etc.) mit ECHTEN Phrasen fuer DIESEN Skill
- Die Phrasen muessen zu den Commands in der Skill-Dokumentation passen
- Antworte NUR mit dem JSON-Objekt, keine Erklaerungen"""


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
                    "max_tokens": 4000,  # Increased for complex skills
                },
            )

            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0]["message"]

                # Get content field (standard response)
                raw_content = (message.get("content") or "").strip()

                # For thinking models: also check reasoning_content
                reasoning_content = (message.get("reasoning_content") or "").strip()

                # Log what we received
                logger.debug(
                    f"LM response for {skill_path.name}: "
                    f"content={len(raw_content)} chars, "
                    f"reasoning={len(reasoning_content)} chars"
                )

                # Try content first (strip thinking tags if present)
                result = _strip_thinking_tags(raw_content) if raw_content else ""

                # If content empty, try to extract JSON from reasoning_content
                if not result and reasoning_content:
                    logger.debug(f"Content empty, checking reasoning_content for JSON")
                    # Look for JSON object at the end of reasoning
                    result = _extract_json_from_reasoning(reasoning_content)

                if not result:
                    logger.warning(
                        f"No usable response for {skill_path.name}. "
                        f"Content: '{raw_content[:200]}', "
                        f"Reasoning tail: '{reasoning_content[-300:] if reasoning_content else 'N/A'}'"
                    )
                    return []

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


def _extract_json_from_reasoning(reasoning: str) -> str:
    """Extract JSON from reasoning_content of thinking models.

    Some thinking models output the final answer within their reasoning
    process rather than in the content field.

    Args:
        reasoning: The reasoning_content from the model

    Returns:
        Extracted JSON string or empty string
    """
    # Look for JSON object with "examples" key
    match = re.search(r'\{[^{}]*"examples"[^{}]*\[[\s\S]*?\]\s*\}', reasoning)
    if match:
        return match.group()

    # Look for any JSON object near the end (last 1000 chars)
    tail = reasoning[-1500:] if len(reasoning) > 1500 else reasoning
    match = re.search(r'\{[\s\S]*"examples"[\s\S]*\}', tail)
    if match:
        return match.group()

    return ""


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
        force_regenerate: If True, regenerate and MERGE with existing examples

    Returns:
        List of examples
    """
    # Load existing examples
    existing = load_examples(skill_path)

    # If examples exist and we're not forcing regeneration, return them
    if existing and not force_regenerate:
        return existing

    # Generate new examples
    new_examples = await extract_examples_from_skill(
        skill_path, lm_studio_url, lm_studio_model, commands
    )

    if new_examples:
        # Merge with existing examples (avoids duplicates)
        if existing:
            merged = merge_examples(existing, new_examples)
            logger.info(f"Merged {len(new_examples)} new + {len(existing)} existing = {len(merged)} examples")
            save_examples(skill_path, merged)
            return merged
        else:
            save_examples(skill_path, new_examples)
            return new_examples

    return existing or []
