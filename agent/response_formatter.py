"""Response formatting - LLM post-processes raw script output.

Takes raw script output and original user question, returns a
conversational response that directly answers the user's question.
"""

import logging

import httpx

from .config import Settings
from .wol import ensure_lm_studio_available

logger = logging.getLogger(__name__)

# Prompt for formatting responses - kept simple for local LLMs
FORMAT_PROMPT = """Frage: "{user_question}"

Daten:
{raw_output}

Aufgabe: Beantworte die Frage basierend auf den Daten. Zeige NUR den relevanten Teil.

Beispiel:
- Frage "Was war im Garten?" → Zeige nur Garten-Events
- Frage "Läuft mein NAS?" → Antworte "Ja" oder "Nein" mit kurzer Info

Antwort:"""


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

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.lm_studio_url}/v1/chat/completions",
                json={
                    "model": settings.lm_studio_model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.5,  # Slightly higher for local LLMs
                    "max_tokens": 500,  # Shorter responses expected
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
                    logger.warning(f"LLM response was: '{formatted}'")
                    return raw_output
            else:
                body = response.text[:500] if response.text else "(empty)"
                logger.warning(f"LLM formatting failed: HTTP {response.status_code}, body: {body}")
                return raw_output

    except Exception as e:
        logger.warning(f"Error formatting response: {e}")
        # Fall back to raw output on any error
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
