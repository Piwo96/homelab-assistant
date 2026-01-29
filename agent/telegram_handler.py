"""Telegram message and callback handling."""

import logging
import httpx
from typing import Optional, Dict, Any

from .config import Settings
from .models import TelegramUser

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


def verify_webhook_signature(secret_header: Optional[str], expected_secret: str) -> bool:
    """Verify Telegram webhook signature.

    Args:
        secret_header: X-Telegram-Bot-Api-Secret-Token header value
        expected_secret: Expected secret from settings

    Returns:
        True if signature is valid
    """
    if not secret_header or not expected_secret:
        return False
    return secret_header == expected_secret


def parse_telegram_user(user_data: Dict[str, Any]) -> TelegramUser:
    """Parse Telegram user data into TelegramUser model."""
    return TelegramUser(
        id=user_data.get("id", 0),
        first_name=user_data.get("first_name", "Unknown"),
        last_name=user_data.get("last_name"),
        username=user_data.get("username"),
    )


# Telegram message limit (official: 4096 UTF-8 chars, leave margin)
_TELEGRAM_MAX_LEN = 4000


async def send_message(
    chat_id: int,
    text: str,
    settings: Settings,
    parse_mode: str = "Markdown",
    reply_markup: Optional[Dict] = None,
) -> Optional[int]:
    """Send a message to a Telegram chat.

    Automatically splits messages that exceed Telegram's 4096 char limit.

    Args:
        chat_id: Telegram chat ID
        text: Message text (supports Markdown)
        settings: Application settings
        parse_mode: Parse mode (Markdown, HTML, or None)
        reply_markup: Optional inline keyboard markup

    Returns:
        Message ID of the last sent message if successful, None otherwise
    """
    # Auto-split long messages
    if len(text) > _TELEGRAM_MAX_LEN:
        parts = _split_message(text, _TELEGRAM_MAX_LEN)
        logger.info(f"Splitting message ({len(text)} chars) into {len(parts)} parts")
        last_msg_id = None
        for i, part in enumerate(parts):
            # Only attach reply_markup to the last part
            markup = reply_markup if i == len(parts) - 1 else None
            last_msg_id = await send_message(chat_id, part, settings, parse_mode, markup)
        return last_msg_id

    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/sendMessage",
                json=payload,
            )
            result = response.json()
            if result.get("ok"):
                return result.get("result", {}).get("message_id")
            else:
                # If Markdown parsing failed, retry without parse_mode
                error_desc = result.get("description", "")
                if "can't parse entities" in error_desc and parse_mode:
                    logger.warning(f"Markdown parsing failed, retrying without formatting")
                    payload.pop("parse_mode", None)
                    response = await client.post(
                        f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/sendMessage",
                        json=payload,
                    )
                    result = response.json()
                    if result.get("ok"):
                        return result.get("result", {}).get("message_id")
                logger.error(f"Telegram API error: {result}")
    except httpx.RequestError as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending message: {e}")

    return None


async def send_approval_request(
    admin_id: int,
    text: str,
    request_id: str,
    settings: Settings,
) -> Optional[int]:
    """Send a message with inline keyboard for approval.

    Args:
        admin_id: Admin's Telegram user ID
        text: Message text
        request_id: Unique approval request ID
        settings: Application settings

    Returns:
        Message ID if successful, None otherwise
    """
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Ja, erstellen", "callback_data": f"approve:{request_id}"},
                {"text": "❌ Nein", "callback_data": f"reject:{request_id}"},
            ]
        ]
    }

    return await send_message(
        chat_id=admin_id,
        text=text,
        settings=settings,
        reply_markup=reply_markup,
    )


async def answer_callback_query(
    callback_query_id: str,
    text: str,
    settings: Settings,
    show_alert: bool = False,
) -> bool:
    """Answer a callback query (removes loading indicator on button).

    Args:
        callback_query_id: Callback query ID from Telegram
        text: Text to show (toast notification)
        settings: Application settings
        show_alert: If True, show as alert popup instead of toast

    Returns:
        True if successful
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/answerCallbackQuery",
                json={
                    "callback_query_id": callback_query_id,
                    "text": text,
                    "show_alert": show_alert,
                },
            )
            return response.json().get("ok", False)
    except httpx.RequestError as e:
        logger.error(f"Failed to answer callback query: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in answer_callback_query: {e}")
        return False


async def edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    settings: Settings,
    parse_mode: str = "Markdown",
    reply_markup: Optional[Dict] = None,
) -> bool:
    """Edit an existing message.

    Args:
        chat_id: Chat ID containing the message
        message_id: Message ID to edit
        text: New text content
        settings: Application settings
        parse_mode: Parse mode for text
        reply_markup: Optional new inline keyboard

    Returns:
        True if successful
    """
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/editMessageText",
                json=payload,
            )
            return response.json().get("ok", False)
    except httpx.RequestError as e:
        logger.error(f"Failed to edit message {message_id} in chat {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in edit_message_text: {e}")
        return False


async def delete_message(
    chat_id: int,
    message_id: int,
    settings: Settings,
) -> bool:
    """Delete a message.

    Args:
        chat_id: Chat ID containing the message
        message_id: Message ID to delete
        settings: Application settings

    Returns:
        True if successful
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{TELEGRAM_API_BASE}{settings.telegram_bot_token}/deleteMessage",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                },
            )
            return response.json().get("ok", False)
    except httpx.RequestError as e:
        logger.error(f"Failed to delete message {message_id} in chat {chat_id}: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error in delete_message: {e}")
        return False


# Help text for /help command
HELP_TEXT = """🏠 *Homelab Assistant*

Ich steuere dein Smart Home und Homelab. Frag einfach drauf los.

*Beispiele:*
• "Mach das Licht im Wohnzimmer an"
• "Wer ist im WLAN?"
• "Welche Kameras haben wir?"
• "Wie ist der Server-Status?"
• "Wie viele Werbungen wurden geblockt?"
• "Was war letztens vor der Tür?"

*Befehle:*
/help - Diese Hilfe anzeigen
/wake - Gaming-PC aufwecken
/skills - Geladene Skills anzeigen
/clear - Chat-Verlauf löschen"""


def _split_message(text: str, max_len: int) -> list[str]:
    """Split a long message into parts that fit Telegram's limit.

    Tries to split at paragraph boundaries, then newlines.
    """
    if len(text) <= max_len:
        return [text]

    parts = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break

        # Find a good split point
        chunk = remaining[:max_len]

        # Try paragraph break (double newline)
        split_at = chunk.rfind("\n\n")
        if split_at < max_len // 3:
            # Try single newline
            split_at = chunk.rfind("\n")
        if split_at < max_len // 3:
            # Hard cut at max_len
            split_at = max_len

        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return parts
