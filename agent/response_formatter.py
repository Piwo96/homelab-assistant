"""Response formatting - LLM post-processes raw script output.

Takes raw script output and original user question, returns a
conversational response that directly answers the user's question.
"""

import logging
import re

import httpx

from .config import Settings
from .wol import ensure_lm_studio_available

logger = logging.getLogger(__name__)

# Prompt for formatting responses - converts JSON data to natural language
FORMAT_PROMPT = """Du bist ein Homelab-Assistent. Beantworte die Frage basierend auf den JSON-Daten.

## Regeln
- Antworte auf Deutsch, sachlich und präzise
- Kurze Sätze, kein Fachchinesisch
- Keine Emojis!
- Fasse zusammen statt aufzulisten (außer bei vielen Einträgen)
- Gib NUR Informationen aus den Daten wieder, erfinde NICHTS dazu
- Bei JSON-Daten: extrahiere die relevanten Felder und formuliere natürlich

## Beispiele
Frage: "Wann war jemand im Garten?"
Daten: [{{"type": "motion", "camera": "Garten", "timestamp": "14:03", "smart": ["person"]}}]
Gut: "Im Garten wurde zuletzt um 14:03 Uhr eine Person erkannt."

Frage: "Wie ist der Server-Status?"
Daten: {{"cpu": 0.025, "memory": {{"used": 6442450944, "total": 16642998272}}, "uptime": 864000}}
Gut: "Proxmox läuft stabil. CPU bei 2,5%, RAM bei 6 von 16 GB. Uptime: 10 Tage."

Frage: "Welche Geräte sind im Netzwerk?"
Daten: [{{"name": "iPhone", "type": "WIRELESS"}}, {{"name": "NAS", "type": "WIRED"}}]
Gut: "Zwei Geräte im Netzwerk: iPhone (WLAN) und NAS (kabelgebunden)."

## Frage
{user_question}

## Daten
{raw_output}

## Deine Antwort (natürlich, auf den Punkt, NUR basierend auf den Daten):"""


async def format_response(
    user_question: str,
    raw_output: str,
    settings: Settings,
    skill: str = "",
    action: str = "",
) -> str:
    """Format raw script output into a conversational response.

    Args:
        user_question: Original user question
        raw_output: Raw output from skill script
        settings: Application settings
        skill: Skill that was executed (for context)
        action: Action that was executed (for context)

    Returns:
        Formatted conversational response
    """
    logger.info(f"Formatting response for skill={skill}, action={action}, output_len={len(raw_output)}")

    # If output is short and simple, just return it
    if len(raw_output) < 100 and "\n" not in raw_output:
        logger.debug("Short/simple output - returning as-is")
        return raw_output

    # Ensure LM Studio is available
    await ensure_lm_studio_available(settings)

    prompt = FORMAT_PROMPT.format(
        user_question=user_question,
        raw_output=raw_output[:2000],  # Truncate if too long - shorter for local LLMs
    )

    logger.info(f"Format prompt length: {len(prompt)} chars")

    # Token limits for retry: start low, increase on context errors
    token_limits = [2048, 4096, 8192]

    for attempt, max_tokens in enumerate(token_limits):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{settings.lm_studio_url}/v1/chat/completions",
                    json={
                        "model": settings.lm_studio_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": max_tokens,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    formatted = data["choices"][0]["message"]["content"].strip()

                    # Strip <think> tags from reasoning models (no-op for others)
                    formatted = re.sub(r"<think>.*?</think>", "", formatted, flags=re.DOTALL).strip()

                    # Validate response isn't empty or too short
                    if len(formatted) > 5:
                        logger.info(f"Formatted {len(raw_output)} chars -> {len(formatted)} chars")
                        logger.info(f"Formatted response preview: {formatted[:150]}...")
                        return formatted
                    else:
                        logger.warning(f"LLM returned empty/short response ({len(formatted)} chars), using raw output")
                        return raw_output

                # Check for context/token errors that might benefit from retry
                body = response.text[:500] if response.text else ""
                is_context_error = (
                    response.status_code == 400
                    and any(kw in body.lower() for kw in ["context", "token", "length", "exceed"])
                )

                if is_context_error and attempt < len(token_limits) - 1:
                    logger.warning(f"Context error with max_tokens={max_tokens}, retrying with {token_limits[attempt + 1]}")
                    continue

                logger.warning(f"LLM formatting failed: HTTP {response.status_code}, body: {body}")
                return raw_output

        except Exception as e:
            logger.warning(f"Error formatting response: {e}")
            return raw_output

    return raw_output


async def should_format_response(
    user_question: str,
    raw_output: str,
    skill: str,
) -> bool:
    """Determine if response should be formatted by LLM.

    With JSON output from scripts, we almost always need formatting
    to convert structured data into natural language.

    Args:
        user_question: Original user question
        raw_output: Raw output from skill script
        skill: Skill that was executed

    Returns:
        True if formatting is recommended
    """
    # JSON output always needs formatting into natural language
    stripped = raw_output.strip()
    if stripped.startswith(("{", "[")):
        logger.debug("Format needed: JSON output detected")
        return True

    # Short, simple non-JSON output can be passed through
    if len(raw_output) < 80 and "\n" not in raw_output and not stripped.startswith(("{", "[")):
        logger.debug("No formatting needed: short simple output")
        return False

    # Multi-line or long output needs formatting
    if len(raw_output) > 200 or raw_output.count("\n") > 3:
        logger.debug(f"Format needed: output length={len(raw_output)}, lines={raw_output.count(chr(10))}")
        return True

    # Technical skills always format
    technical_skills = ["unifi-network", "unifi-protect", "proxmox", "pihole", "homeassistant"]
    if skill in technical_skills:
        logger.debug(f"Format needed: technical skill {skill}")
        return True

    logger.debug("No formatting needed")
    return False
