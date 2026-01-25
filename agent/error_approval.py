"""Error fix approval workflow with persistent storage.

When an error occurs during skill execution:
1. Error is logged and approval request sent to admin
2. Request is stored in JSON file (persists across restarts)
3. No timeout - admin can approve whenever
4. On approval, self-annealing process runs
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Settings
from .models import ApprovalStatus, ErrorFixRequest
from .telegram_handler import send_message, send_approval_request, edit_message_text
from . import self_annealing

logger = logging.getLogger(__name__)

# File-based storage for pending error fixes (persists across restarts)
PENDING_ERRORS_FILE = Path(__file__).parent.parent / ".claude" / "pending_errors.json"


def _load_pending_errors() -> dict[str, dict]:
    """Load pending errors from file."""
    if not PENDING_ERRORS_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_ERRORS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load pending errors: {e}")
        return {}


def _save_pending_errors(errors: dict[str, dict]) -> None:
    """Save pending errors to file."""
    try:
        PENDING_ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_ERRORS_FILE.write_text(json.dumps(errors, indent=2, default=str))
    except OSError as e:
        logger.error(f"Failed to save pending errors: {e}")


def _error_to_dict(error: ErrorFixRequest) -> dict:
    """Convert ErrorFixRequest to dict for JSON storage."""
    return {
        "request_id": error.request_id,
        "error_type": error.error_type,
        "error_message": error.error_message,
        "skill": error.skill,
        "action": error.action,
        "context": error.context,
        "created_at": error.created_at.isoformat(),
        "message_id": error.message_id,
        "status": error.status.value,
    }


def _dict_to_error(data: dict) -> ErrorFixRequest:
    """Convert dict to ErrorFixRequest."""
    return ErrorFixRequest(
        request_id=data["request_id"],
        error_type=data["error_type"],
        error_message=data["error_message"],
        skill=data["skill"],
        action=data["action"],
        context=data["context"],
        created_at=datetime.fromisoformat(data["created_at"]),
        message_id=data.get("message_id"),
        status=ApprovalStatus(data.get("status", "pending")),
    )


async def request_error_fix_approval(
    error_type: str,
    error_message: str,
    skill: str,
    action: str,
    context: str,
    settings: Settings,
) -> Optional[str]:
    """Request admin approval for an error fix.

    Args:
        error_type: Type of error (e.g., "ScriptError", "TimeoutExpired")
        error_message: The error message
        skill: Which skill failed
        action: Which action failed
        context: Additional context (command executed, etc.)
        settings: Application settings

    Returns:
        Request ID if sent successfully, None otherwise
    """
    request_id = f"err_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"

    error_request = ErrorFixRequest(
        request_id=request_id,
        error_type=error_type,
        error_message=error_message[:500],  # Truncate long errors
        skill=skill,
        action=action,
        context=context[:500],  # Truncate long context
        created_at=datetime.now(),
    )

    # Send approval request to admin
    approval_text = (
        f"🔴 *Fehler aufgetreten*\n\n"
        f"**Skill:** {skill}\n"
        f"**Aktion:** {action}\n"
        f"**Fehler:** `{error_type}`\n\n"
        f"```\n{error_message[:300]}\n```\n\n"
        f"Soll ich versuchen, diesen Fehler zu beheben?"
    )

    message_id = await send_approval_request(
        admin_id=settings.admin_telegram_id,
        text=approval_text,
        request_id=request_id,
        settings=settings,
    )

    if message_id:
        error_request.message_id = message_id

    # Store in persistent file
    pending = _load_pending_errors()
    pending[request_id] = _error_to_dict(error_request)
    _save_pending_errors(pending)

    logger.info(f"Error fix requested: {request_id} - {skill}:{action} - {error_type}")

    return request_id


async def handle_error_fix_approval(
    request_id: str,
    approved: bool,
    settings: Settings,
) -> str:
    """Handle admin's approval or rejection of an error fix.

    Args:
        request_id: The error fix request ID
        approved: True if approved, False if rejected
        settings: Application settings

    Returns:
        Status message
    """
    pending = _load_pending_errors()

    if request_id not in pending:
        return "❌ Fehler-Anfrage nicht gefunden."

    error_data = pending.pop(request_id)
    _save_pending_errors(pending)

    error_request = _dict_to_error(error_data)

    if not approved:
        error_request.status = ApprovalStatus.REJECTED
        logger.info(f"Error fix {request_id} rejected")

        # Update admin message
        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"❌ *Abgelehnt*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`",
                settings=settings,
            )

        return "Fehler-Fix abgelehnt."

    # Approved - run self-annealing
    error_request.status = ApprovalStatus.APPROVED
    logger.info(f"Error fix {request_id} approved, running self-annealing...")

    # Update admin message to show processing
    if error_request.message_id:
        await edit_message_text(
            chat_id=settings.admin_telegram_id,
            message_id=error_request.message_id,
            text=f"⏳ *Wird behoben...*\n\n"
                 f"**Skill:** {error_request.skill}\n"
                 f"**Fehler:** `{error_request.error_type}`",
            settings=settings,
        )

    try:
        # Log the error in self-annealing
        log_result = await self_annealing.log_error(
            error=error_request.error_type,
            context=f"{error_request.skill}:{error_request.action} - {error_request.error_message}",
            settings=settings,
        )

        error_id = log_result.get("error_id")
        result_text = f"Fehler geloggt: {error_id}" if error_id else "Fehler geloggt"

        # Update admin message with result
        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"✅ *Fehler dokumentiert*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"Der Fehler wurde im Self-Annealing-System erfasst.",
                settings=settings,
            )

        logger.info(f"Error fix completed: {request_id}")
        return result_text

    except Exception as e:
        logger.error(f"Error during self-annealing: {e}")

        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"❌ *Fehler bei der Behebung*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"Fehler: {str(e)}",
                settings=settings,
            )

        return f"Fehler: {str(e)}"


def get_pending_error_fixes() -> list[ErrorFixRequest]:
    """Get all pending error fix requests.

    Returns:
        List of pending ErrorFixRequest objects
    """
    pending = _load_pending_errors()
    return [
        _dict_to_error(data)
        for data in pending.values()
        if data.get("status") == "pending"
    ]


def is_error_request(request_id: str) -> bool:
    """Check if a request ID is an error fix request.

    Args:
        request_id: The request ID to check

    Returns:
        True if it's an error fix request
    """
    return request_id.startswith("err_")
