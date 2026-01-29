"""Conversational utilities for follow-up detection and skill creation workflow.

Provides helpers for:
- Detecting follow-up messages and enriching them with context
- Detecting pending skill creation requests and user confirmations
"""

import logging
import re
from typing import Optional

from .chat_history import get_history

logger = logging.getLogger(__name__)

# Patterns that indicate a follow-up referencing the previous conversation topic.
# These are short phrases where the user implicitly continues the previous question.
_FOLLOWUP_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # Topic continuation: "Und was war in der Einfahrt?"
        r"^und\s+(was|wer|wie|wo|welche|wann)",
        r"^und\s+(im|in|bei|der|die|das|den|dem)\s+",
        # Asking about a different target: "Was ist mit dem Garten?"
        r"^was ist mit\s+",
        r"^wie sieht.?s (im|in|bei|am)\s+",
        # Same question, different target: "Im Garten?", "In der Einfahrt?"
        r"^(im|in|bei|am|an der|an dem|vor der|vor dem)\s+\w+(\s+\w+)?\??\s*$",
    ]
]


def enrich_followup_message(message: str, chat_id: int) -> str:
    """Enrich a follow-up message with context from the previous exchange.

    If the message looks like a follow-up question (e.g., "Und was war in der
    Einfahrt?" after asking about recordings in another room), prepend context
    from the last user message so the intent classifier can route correctly.

    Args:
        message: Current user message
        chat_id: Chat ID for history lookup

    Returns:
        Enriched message with context hint, or original message if not a follow-up
    """
    # Only short messages can be follow-ups
    if len(message) > 120:
        return message

    # Check against follow-up patterns
    if not any(p.search(message) for p in _FOLLOWUP_PATTERNS):
        return message

    # Need conversation history to extract context
    history = get_history(chat_id)
    if not history:
        return message

    # Find the last user message as context
    last_user_msg = None
    for entry in reversed(history):
        if entry.get("role") == "user":
            last_user_msg = entry["content"]
            break

    if not last_user_msg:
        return message

    logger.info(
        f"Follow-up detected: '{message[:60]}' "
        f"(context: '{last_user_msg[:60]}')"
    )

    # Add explicit context hint for the classifier
    return (
        f"{message}\n\n"
        f"(Kontext: Der User hat zuvor gefragt: \"{last_user_msg}\" "
        f"- die aktuelle Frage ist eine Nachfrage zum selben Thema.)"
    )


def get_pending_skill_request(chat_id: int) -> tuple[Optional[str], Optional[str]]:
    """Check if there's a pending skill creation request.

    Args:
        chat_id: Chat ID for history lookup

    Returns:
        Tuple of (user_request, skill_to_extend) - skill_to_extend is None for new skills
    """
    history = get_history(chat_id)
    if not history:
        return None, None

    # Look for PENDING_SKILL_REQUEST marker in recent history
    for entry in reversed(history[-5:]):
        if entry.get("role") == "system":
            content = entry.get("content", "")
            if content.startswith("PENDING_SKILL_REQUEST:"):
                # Format: PENDING_SKILL_REQUEST:request|EXTEND:skill_name or just PENDING_SKILL_REQUEST:request
                payload = content.replace("PENDING_SKILL_REQUEST:", "")
                if "|EXTEND:" in payload:
                    parts = payload.split("|EXTEND:", 1)
                    return parts[0], parts[1]
                return payload, None

    return None, None


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
