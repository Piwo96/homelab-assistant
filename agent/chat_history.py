"""In-memory chat history storage for conversation context.

Stores message history per chat_id to provide context for LLM calls.
History is stored in memory and will be lost on restart.
"""

from typing import Dict, List
from collections import deque

from .config import get_settings

# Type alias for message format (OpenAI compatible)
Message = Dict[str, str]  # {"role": "user"|"assistant", "content": str}

# Storage: chat_id -> deque of messages (deque for efficient FIFO)
_histories: Dict[int, deque] = {}

# Keywords that indicate bad responses that should be filtered from history
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
    """Get conversation history for a chat, filtered of bad responses.

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

    # Process messages and remove bad responses along with their preceding user message
    for msg in messages:
        if msg["role"] == "assistant" and _is_bad_response(msg["content"]):
            # Skip this bad response and mark to skip preceding user message
            if filtered and filtered[-1]["role"] == "user":
                filtered.pop()  # Remove the user message that led to bad response
            continue
        filtered.append(msg)

    return filtered


def add_message(chat_id: int, role: str, content: str) -> None:
    """Add a message to the conversation history.

    Automatically trims history to configured limit.

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


def clear_history(chat_id: int) -> bool:
    """Clear conversation history for a chat.

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
    """Get statistics about stored histories.

    Returns:
        Dict with chat_count and total_messages
    """
    total_messages = sum(len(h) for h in _histories.values())
    return {
        "chat_count": len(_histories),
        "total_messages": total_messages,
    }
