"""Response formatting - LLM post-processes raw script output.

Takes raw script output and original user question, returns a
conversational response that directly answers the user's question.
"""

import logging

import httpx

from .config import Settings
from .wol import ensure_lm_studio_available

logger = logging.getLogger(__name__)

# Prompt for formatting responses
FORMAT_PROMPT = """Du bist ein freundlicher Smart Home Assistant.

## User-Frage
"{user_question}"

## System-Daten
{raw_output}

## Deine Aufgabe

Beantworte die Frage des Users basierend auf den Daten.

**Regeln:**
1. Beantworte NUR was gefragt wurde
2. Wenn nach einem bestimmten Ort/Gerät gefragt wurde, zeige NUR diesen Teil
3. Behalte die Formatierung bei (Emojis, Listen) - aber nur für relevante Teile
4. Bei Ja/Nein-Fragen: Antworte kurz und klar
5. Wenn die Daten die Frage nicht beantworten können, sag das ehrlich

**Beispiele:**

Frage: "Was war im Garten los?"
→ Zeige NUR die Garten-Events, nicht alle Kameras

Frage: "Läuft mein NAS?"
→ Kurze Antwort: "Ja, dein NAS (VM 102) läuft." oder "Nein, VM 102 ist gestoppt."

Frage: "Haben wir Zugriff auf die Videos?"
→ Erkläre kurz ob/wie man auf Videos zugreifen kann, keine Event-Liste

Frage: "Wie viele Bewegungen heute?"
→ Zähle zusammen und antworte mit der Zahl

Antworte direkt und natürlich auf Deutsch."""


async def format_response(
    user_question: str,
    raw_output: str,
    settings: Settings,
    skill: str = "",  # noqa: ARG001
    action: str = "",  # noqa: ARG001
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
    # If output is short and simple, just return it
    if len(raw_output) < 100 and "\n" not in raw_output:
        return raw_output

    # Ensure LM Studio is available
    await ensure_lm_studio_available(settings)

    prompt = FORMAT_PROMPT.format(
        user_question=user_question,
        raw_output=raw_output[:4000],  # Truncate if too long
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.lm_studio_url}/v1/chat/completions",
                json={
                    "model": settings.lm_studio_model,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,  # Low temperature for consistent responses
                    "max_tokens": 1000,
                },
            )

            if response.status_code == 200:
                data = response.json()
                formatted = data["choices"][0]["message"]["content"].strip()

                # Validate response isn't empty or too short
                if len(formatted) > 5:
                    logger.debug(f"Formatted response: {formatted[:100]}...")
                    return formatted
                else:
                    logger.warning("LLM returned empty/short response, using raw output")
                    return raw_output
            else:
                logger.warning(f"LLM formatting failed: {response.status_code}")
                return raw_output

    except Exception as e:
        logger.warning(f"Error formatting response: {e}")
        # Fall back to raw output on any error
        return raw_output


async def should_format_response(
    user_question: str,
    raw_output: str,
    skill: str,  # noqa: ARG001
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
        return True

    # Always format if output has multiple lines
    if raw_output.count("\n") > 3:
        return True

    # Format if question is specific but output is general
    specific_keywords = [
        "garten", "einfahrt", "wohnzimmer", "küche",  # Locations
        "heute", "gestern", "letzte",  # Time
        "nur", "wieviel", "wie viele",  # Specific queries
    ]
    if any(kw in user_question.lower() for kw in specific_keywords):
        return True

    return False
