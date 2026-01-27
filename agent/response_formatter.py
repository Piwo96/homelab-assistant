"""Response formatting - LLM post-processes raw script output.

Takes raw script output and original user question, returns a
conversational response that directly answers the user's question.
"""

import logging

import httpx

from .config import Settings
from .wol import ensure_lm_studio_available

logger = logging.getLogger(__name__)

# Prompt for formatting responses - encourages friendly, conversational tone
FORMAT_PROMPT = """Du bist ein Homelab-Assistent. Beantworte die Frage basierend auf den Daten.

## Stil
- Sachlich und präzise
- Kurze Sätze, kein Fachchinesisch
- Keine Emojis verwenden!
- Fasse zusammen statt aufzulisten (außer bei vielen Einträgen)
- Fokus auf die Fakten, wenig Floskeln

## Beispiele für gute Antworten
Schlecht: "- 14:03 - Person\\n- 14:04 - Person"
Gut: "Im Garten waren heute zwei Personen zu sehen, zuletzt um 14:04 Uhr."

Schlecht: "CPU: 2,5%\\nRAM: 6,0 GB / 15,5 GB"
Gut: "Proxmox läuft stabil. CPU bei 2,5%, RAM etwa ein Drittel belegt."

Schlecht: "Ja, VM 100 läuft."
Gut: "Ja, die Windows-VM läuft."

## Frage
{user_question}

## Daten
{raw_output}

## Deine Antwort (freundlich, natürlich, auf den Punkt):"""


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
                        "temperature": 0.5,
                        "max_tokens": max_tokens,
                    },
                )

                if response.status_code == 200:
                    data = response.json()
                    formatted = data["choices"][0]["message"]["content"].strip()

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

    Args:
        user_question: Original user question
        raw_output: Raw output from skill script
        skill: Skill that was executed

    Returns:
        True if formatting is recommended
    """
    # Always format if output is long or complex
    if len(raw_output) > 200:
        logger.debug(f"Format needed: output > 200 chars ({len(raw_output)})")
        return True

    # Always format if output has multiple lines
    if raw_output.count("\n") > 3:
        logger.debug(f"Format needed: output has {raw_output.count(chr(10))} newlines")
        return True

    # Always format for certain skills that return technical/complex data
    technical_skills = ["unifi-network", "unifi-protect", "proxmox", "pihole", "homeassistant"]
    if skill in technical_skills:
        logger.debug(f"Format needed: technical skill {skill}")
        return True

    # Format if question is specific but output is general
    specific_keywords = [
        # Locations (cameras, rooms)
        "garten", "einfahrt", "wohnzimmer", "küche", "flur", "schlafzimmer",
        "bad", "keller", "garage", "terrasse", "balkon", "grünstreifen",
        # Time filters
        "heute", "gestern", "letzte", "letzten", "vor einer stunde", "diese woche",
        # Specific queries
        "nur", "wieviel", "wie viele", "wie viel", "zähl", "zeig mir",
        # Entity types
        "person", "tier", "auto", "fahrzeug", "paket", "gesicht",
    ]
    if any(kw in user_question.lower() for kw in specific_keywords):
        logger.debug("Format needed: specific keyword in question")
        return True

    logger.debug("No formatting needed")
    return False
