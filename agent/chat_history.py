"""Chat history storage with in-memory cache and SQLite persistence.

Combines fast in-memory access for LLM context with persistent
SQLite storage for analysis and self-improvement.
"""

import logging
from collections import deque
from typing import Dict, List, Optional

from .config import get_settings

logger = logging.getLogger(__name__)

# Type alias for message format (OpenAI compatible)
Message = Dict[str, str]  # {"role": "user"|"assistant", "content": str}

# In-memory cache: chat_id -> deque of messages (fast access for LLM)
_histories: Dict[int, deque] = {}

# Keywords that indicate bad responses that should be filtered from LLM context
BAD_RESPONSE_KEYWORDS = [
    "self-annealing", "self_annealing", "selbstverbesserung",
    "skill updates", "skill-updates", "neue features einbauen",
    "fehlerbehebung", "github sync", "error tracking",
    "können wir automatisch", "durch die selbstverbesserung",
    "automatisch neue skills", "selbstverbesserungsfunktion",
]


def _is_bad_response(content: str) -> bool:
    """Check if a message contains bad response patterns.

    Args:
        content: Message content to check

    Returns:
        True if the message contains problematic patterns
    """
    content_lower = content.lower()
    return any(kw in content_lower for kw in BAD_RESPONSE_KEYWORDS)


def get_history(chat_id: int) -> List[Message]:
    """Get conversation history for LLM context, filtered of bad responses.

    Uses in-memory cache for fast access. Bad responses are filtered
    to prevent the LLM from learning bad patterns.

    Args:
        chat_id: Telegram chat ID

    Returns:
        List of messages in chronological order, with bad responses removed
    """
    if chat_id not in _histories:
        return []

    # Filter out bad assistant responses and their preceding user messages
    messages = list(_histories[chat_id])
    filtered = []

    for msg in messages:
        if msg["role"] == "assistant" and _is_bad_response(msg["content"]):
            # Skip bad response and remove preceding user message
            if filtered and filtered[-1]["role"] == "user":
                filtered.pop()
            continue
        filtered.append(msg)

    return filtered


def add_message(chat_id: int, role: str, content: str) -> None:
    """Add a message to the in-memory conversation history.

    Note: This only updates the in-memory cache for LLM context.
    Full conversation data with intent info is saved separately
    via save_conversation_to_db().

    Args:
        chat_id: Telegram chat ID
        role: Message role ("user" or "assistant")
        content: Message content
    """
    settings = get_settings()
    limit = settings.chat_history_limit

    if chat_id not in _histories:
        _histories[chat_id] = deque(maxlen=limit)

    _histories[chat_id].append({"role": role, "content": content})


def save_conversation_to_db(
    chat_id: int,
    user_message: str,
    assistant_response: str,
    user_id: Optional[int] = None,
    intent_skill: Optional[str] = None,
    intent_action: Optional[str] = None,
    intent_target: Optional[str] = None,
    intent_confidence: Optional[float] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> Optional[int]:
    """Save full conversation data to SQLite database.

    Args:
        chat_id: Telegram chat ID
        user_message: User's message
        assistant_response: Bot's response
        user_id: Telegram user ID
        intent_skill: Detected skill name
        intent_action: Detected action
        intent_target: Detected target
        intent_confidence: Classification confidence
        success: Whether the response was successful
        error_message: Error message if failed

    Returns:
        Conversation ID if saved, None if database not initialized
    """
    try:
        from .database import save_conversation
        return save_conversation(
            chat_id=chat_id,
            user_message=user_message,
            assistant_response=assistant_response,
            user_id=user_id,
            intent_skill=intent_skill,
            intent_action=intent_action,
            intent_target=intent_target,
            intent_confidence=intent_confidence,
            success=success,
            error_message=error_message,
        )
    except RuntimeError:
        # Database not initialized yet
        logger.debug("Database not initialized, skipping conversation save")
        return None
    except Exception as e:
        logger.warning(f"Failed to save conversation to database: {e}")
        return None


def clear_history(chat_id: int) -> bool:
    """Clear in-memory conversation history for a chat.

    Note: Database records are preserved for analysis.

    Args:
        chat_id: Telegram chat ID

    Returns:
        True if history existed and was cleared, False if no history
    """
    if chat_id in _histories:
        del _histories[chat_id]
        return True
    return False


def get_history_stats() -> Dict[str, int]:
    """Get statistics about in-memory histories.

    Returns:
        Dict with chat_count and total_messages
    """
    total_messages = sum(len(h) for h in _histories.values())
    return {
        "chat_count": len(_histories),
        "total_messages": total_messages,
    }
