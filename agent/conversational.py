"""Conversational follow-up detection and handling.

Detects messages that reference previous conversation context
and handles them appropriately without triggering skill classification.
"""

import logging
import re
from typing import Optional

import httpx

from .config import Settings
from .chat_history import get_history
from .wol import ensure_lm_studio_available

logger = logging.getLogger(__name__)

# Patterns that indicate a conversational follow-up referencing previous context
FOLLOWUP_PATTERNS = [
    # Understanding issues
    r"versteh.*nicht",
    r"nicht verstanden",
    r"was mein(st|t) du",
    r"wie mein(st|t) du das",
    r"erklär.*genauer",
    r"erklär.*nochmal",
    r"erklär.*bitte",
    r"kannst du.*erklären",
    r"was bedeutet das",
    r"was heißt das",
    r"was soll das heißen",
    # References to previous message
    r"^das\s",  # "Das verstehe ich nicht"
    r"^die(se)?\s",  # "Diese Antwort..."
    r"^der\s",
    r"damit\b",  # "Was meinst du damit"
    r"davon\b",  # "Was meinst du davon"
    # Simple follow-ups
    r"^warum\??$",
    r"^wieso\??$",
    r"^und\s+(jetzt|dann|weiter)",
    r"mehr dazu",
    r"mehr details",
    r"genauer bitte",
    # Requests for clarification
    r"nochmal bitte",
    r"sag.*nochmal",
    r"wiederhol",
    # Confirmations/negations that need context
    r"^ja,?\s+aber",
    r"^nein,?\s+ich",
    r"^ok(ay)?,?\s+aber",
    # Refinements/corrections - user wants to narrow down previous response
    r"^ich wollte nur",  # "Ich wollte nur den Garten"
    r"^ich meinte nur",  # "Ich meinte nur die Einfahrt"
    r"^nur (den|die|das|im|in|am|an)\b",  # "Nur den Garten", "Nur im Wohnzimmer"
    r"^zeig.*nur",  # "Zeig mir nur..."
    r"^ich brauch.*nur",  # "Ich brauche nur..."
    r"^nicht alles",  # "Nicht alles, nur..."
    r"^ich.*nicht (alle|alles)",  # "Ich wollte nicht alle"
    r"^filter.*auf",  # "Filter auf Garten"
    r"^nur (garten|einfahrt|wohnzimmer|küche|flur|schlafzimmer|bad|keller|garage)",
    r"^(garten|einfahrt|wohnzimmer|küche|flur|schlafzimmer|bad|keller|garage) nur",
]

# Compiled patterns for performance
_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in FOLLOWUP_PATTERNS]


def is_conversational_followup(message: str, chat_id: int) -> bool:
    """Check if a message is a conversational follow-up.

    Args:
        message: User message
        chat_id: Chat ID for history lookup

    Returns:
        True if this looks like a follow-up that needs previous context
    """
    # Check if message is short (likely a follow-up)
    if len(message) > 100:
        return False  # Long messages are probably new requests

    # Check if we have conversation history
    history = get_history(chat_id)
    if not history:
        return False  # No context to follow up on

    # Check against follow-up patterns
    message_lower = message.lower().strip()
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(message_lower):
            logger.info(f"Detected conversational follow-up: '{message[:50]}...'")
            return True

    return False


def get_pending_skill_request(chat_id: int) -> Optional[str]:
    """Check if there's a pending skill creation request.

    Args:
        chat_id: Chat ID for history lookup

    Returns:
        The original user request if pending, None otherwise
    """
    history = get_history(chat_id)
    if not history:
        return None

    # Look for PENDING_SKILL_REQUEST marker in recent history
    for entry in reversed(history[-5:]):
        if entry.get("role") == "system":
            content = entry.get("content", "")
            if content.startswith("PENDING_SKILL_REQUEST:"):
                return content.replace("PENDING_SKILL_REQUEST:", "")

    return None


def is_skill_creation_confirmation(message: str) -> bool:
    """Check if message is a confirmation for skill creation.

    Args:
        message: User message

    Returns:
        True if user is confirming skill creation
    """
    message_lower = message.lower().strip()
    confirmations = [
        "ja", "ja!", "ja.", "ja,", "jap", "jo", "yes",
        "ok", "okay", "klar", "mach", "gerne", "bitte",
        "ja bitte", "ja gerne", "mach das", "leg an",
    ]
    return message_lower in confirmations or message_lower.startswith("ja ")


FOLLOWUP_PROMPT = """Du bist ein freundlicher Smart Home Assistant.

## Konversationsverlauf
{history}

## Aktuelle Nachricht des Users
"{message}"

## Deine Aufgabe
Der User bezieht sich auf die vorherige Nachricht. Beantworte seine Frage oder Bitte
basierend auf dem Konversationsverlauf.

**Regeln:**
1. Beziehe dich auf den Kontext der vorherigen Nachrichten
2. Wenn der User eine **Einschränkung** möchte ("nur Garten", "ich wollte nur..."):
   - Filtere die vorherige Antwort auf den gewünschten Teil
   - Zeige NUR den relevanten Ausschnitt, nicht alles nochmal
3. Erkläre oder verdeutliche was gemeint war
4. Wenn der User etwas nicht verstanden hat, formuliere es einfacher um
5. Bleibe freundlich und hilfsbereit
6. Antworte auf Deutsch
7. Erwähne NIEMALS interne Begriffe wie "Skills", "Tools", "API", "System"

**Beispiele für Einschränkungen:**
- User: "Ich wollte nur den Garten" → Zeige NUR Garten-Events aus der vorherigen Antwort
- User: "Nur die Personen" → Filtere auf Person-Detektionen
- User: "Nur heute" → Zeige nur heutige Events

Antworte direkt und natürlich."""


async def handle_conversational_followup(
    message: str,
    chat_id: int,
    settings: Settings,
) -> Optional[str]:
    """Handle a conversational follow-up message.

    Args:
        message: User message
        chat_id: Chat ID for history lookup
        settings: Application settings

    Returns:
        Response string, or None if handling failed
    """
    history = get_history(chat_id)

    # Format history for prompt
    history_text = "\n".join([
        f"{'User' if h['role'] == 'user' else 'Assistant'}: {h['content']}"
        for h in history[-6:]  # Last 3 exchanges
    ])

    # Ensure LM Studio is available
    await ensure_lm_studio_available(settings)

    prompt = FOLLOWUP_PROMPT.format(
        history=history_text,
        message=message,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.lm_studio_url}/v1/chat/completions",
                json={
                    "model": settings.lm_studio_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
            )

            if response.status_code == 200:
                data = response.json()
                result = data["choices"][0]["message"]["content"].strip()

                # Filter bad responses
                bad_keywords = [
                    "skill", "tool", "api", "system", "feature",
                    "self-annealing", "funktion",
                ]
                if any(kw in result.lower() for kw in bad_keywords):
                    logger.warning(f"Filtered bad followup response: {result[:100]}...")
                    return (
                        "Entschuldige, das habe ich nicht gut erklärt. "
                        "Was genau möchtest du wissen?"
                    )

                logger.debug(f"Followup response: {result[:100]}...")
                return result
            else:
                logger.warning(f"LLM followup failed: {response.status_code}")
                return None

    except Exception as e:
        logger.warning(f"Error in followup handling: {e}")
        return None
