"""Conversational utilities for skill creation workflow.

Provides helpers for detecting pending skill creation requests
and user confirmations in chat history.
"""

import logging
from typing import Optional

from .chat_history import get_history

logger = logging.getLogger(__name__)


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
