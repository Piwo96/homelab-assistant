"""Keyword extraction for skills using LM Studio.

Automatically extracts relevant keywords from SKILL.md files
for homelab-related message detection.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """/no_think
Analysiere diese Skill-Dokumentation und extrahiere relevante Keywords.

## Skill-Dokumentation
{skill_content}

## Aufgabe
Extrahiere 10-30 Keywords die ein User nutzen würde wenn er nach dieser Funktionalität fragt.

**Wichtig:**
- Deutsche UND englische Begriffe
- Technische Begriffe (z.B. "VM", "Container", "VLAN")
- Alltagsbegriffe (z.B. "Server", "Kamera", "Licht")
- Verben (z.B. "starten", "stoppen", "zeigen")
- Keine generischen Wörter wie "was", "wie", "ist"

**Beispiel für einen Kamera-Skill:**
["kamera", "camera", "bewegung", "motion", "aufnahme", "recording", "video", "überwachung", "ereignis", "event"]

Antworte NUR mit einem JSON-Array der Keywords, keine Erklärung:
["keyword1", "keyword2", ...]"""


async def extract_keywords_from_skill(
    skill_path: Path,
    lm_studio_url: str,
    lm_studio_model: str,
) -> list[str]:
    """Extract keywords from a skill's SKILL.md using LM Studio.

    Args:
        skill_path: Path to skill directory containing SKILL.md
        lm_studio_url: LM Studio API URL
        lm_studio_model: Model to use

    Returns:
        List of extracted keywords
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

    prompt = EXTRACT_PROMPT.format(skill_content=content)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{lm_studio_url}/v1/chat/completions",
                json={
                    "model": lm_studio_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 500,
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

                # Strip thinking tags from content if present
                result = _strip_thinking_tags(raw_content) if raw_content else ""

                # If content empty, try to extract JSON array from reasoning_content
                if not result and reasoning_content:
                    logger.debug(f"Content empty, checking reasoning_content for JSON array")
                    result = _extract_array_from_reasoning(reasoning_content)

                if not result:
                    logger.warning(
                        f"No usable response for {skill_path.name}. "
                        f"Content: '{raw_content[:200]}', "
                        f"Reasoning tail: '{reasoning_content[-300:] if reasoning_content else 'N/A'}'"
                    )
                    return []

                # Parse JSON array from response
                keywords = _parse_keywords(result)
                logger.info(f"Extracted {len(keywords)} keywords for {skill_path.name}")
                return keywords
            else:
                logger.warning(f"LM Studio error: {response.status_code}")
                return []

    except httpx.TimeoutException:
        logger.warning(f"Timeout extracting keywords for {skill_path.name} (LM Studio not responding)")
        return []
    except httpx.ConnectError:
        logger.warning(f"Connection error extracting keywords for {skill_path.name} (LM Studio not reachable)")
        return []
    except Exception as e:
        logger.warning(f"Error extracting keywords for {skill_path.name}: {type(e).__name__}: {e}")
        return []


def _parse_keywords(response: str) -> list[str]:
    """Parse keywords from LLM response.

    Args:
        response: LLM response text

    Returns:
        List of keywords
    """
    # Look for array pattern
    match = re.search(r'\[.*?\]', response, re.DOTALL)
    if match:
        try:
            keywords = json.loads(match.group())
            # Normalize: lowercase, strip whitespace
            return [k.lower().strip() for k in keywords if isinstance(k, str)]
        except json.JSONDecodeError:
            pass

    # Fallback: split by comma if no valid JSON
    logger.warning("Failed to parse keywords as JSON, using fallback")
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


def _extract_array_from_reasoning(reasoning: str) -> str:
    """Extract JSON array from reasoning_content of thinking models.

    Args:
        reasoning: The reasoning_content from the model

    Returns:
        Extracted JSON array string or empty string
    """
    # Look for JSON array in the last part of reasoning (final answer)
    tail = reasoning[-1500:] if len(reasoning) > 1500 else reasoning
    match = re.search(r'\[[^\[\]]*\]', tail, re.DOTALL)
    if match:
        return match.group()
    return ""


def load_keywords(skill_path: Path) -> list[str]:
    """Load keywords from keywords.json if it exists.

    Args:
        skill_path: Path to skill directory

    Returns:
        List of keywords or empty list
    """
    keywords_file = skill_path / "keywords.json"
    if keywords_file.exists():
        try:
            with open(keywords_file) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [k.lower() for k in data]
                elif isinstance(data, dict) and "keywords" in data:
                    return [k.lower() for k in data["keywords"]]
        except Exception as e:
            logger.warning(f"Failed to load keywords from {keywords_file}: {e}")

    return []


def save_keywords(skill_path: Path, keywords: list[str]) -> bool:
    """Save keywords to keywords.json.

    Args:
        skill_path: Path to skill directory
        keywords: List of keywords

    Returns:
        True if saved successfully
    """
    keywords_file = skill_path / "keywords.json"
    try:
        with open(keywords_file, "w") as f:
            json.dump({"keywords": keywords, "auto_generated": True}, f, indent=2)
        logger.info(f"Saved {len(keywords)} keywords to {keywords_file}")
        return True
    except Exception as e:
        logger.warning(f"Failed to save keywords: {e}")
        return False


def merge_keywords(existing: list[str], new: list[str]) -> list[str]:
    """Merge new keywords into existing, avoiding duplicates.

    Args:
        existing: Existing keywords list
        new: New keywords to add

    Returns:
        Merged list with no duplicate keywords
    """
    # Use set for deduplication (all already lowercase)
    merged_set = set(existing) | set(new)
    return sorted(merged_set)


async def ensure_keywords(
    skill_path: Path,
    lm_studio_url: str,
    lm_studio_model: str,
    force_regenerate: bool = False,
) -> list[str]:
    """Ensure keywords exist for a skill, generating if needed.

    Args:
        skill_path: Path to skill directory
        lm_studio_url: LM Studio API URL
        lm_studio_model: Model to use
        force_regenerate: If True, regenerate and MERGE with existing keywords

    Returns:
        List of keywords
    """
    # Load existing keywords
    existing = load_keywords(skill_path)

    # If keywords exist and we're not forcing regeneration, return them
    if existing and not force_regenerate:
        return existing

    # Generate new keywords
    new_keywords = await extract_keywords_from_skill(
        skill_path, lm_studio_url, lm_studio_model
    )

    if new_keywords:
        # Merge with existing keywords (avoids duplicates)
        if existing:
            merged = merge_keywords(existing, new_keywords)
            logger.info(f"Merged {len(new_keywords)} new + {len(existing)} existing = {len(merged)} keywords")
            save_keywords(skill_path, merged)
            return merged
        else:
            save_keywords(skill_path, new_keywords)
            return new_keywords

    return existing or []
