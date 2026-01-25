"""Error fix approval workflow with automatic PR creation.

When an error occurs during skill execution:
1. Claude API analyzes the error and proposes a fix
2. A fix branch is created with the changes
3. A Pull Request is created on GitHub
4. Admin receives Telegram notification with PR link
5. On approval, PR is merged and changes pulled
6. On rejection, PR is closed and branch deleted
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add skills path to import git_api
_git_scripts_path = str(Path(__file__).parent.parent / ".claude" / "skills" / "git" / "scripts")
if _git_scripts_path not in sys.path:
    sys.path.insert(0, _git_scripts_path)

from .config import Settings
from .models import ApprovalStatus, ErrorFixRequest
from .telegram_handler import send_message, send_approval_request, edit_message_text
from .fix_generator import generate_fix, apply_fix
from . import self_annealing

logger = logging.getLogger(__name__)

# File-based storage for pending error fixes (persists across restarts)
PENDING_ERRORS_FILE = Path(__file__).parent.parent / ".claude" / "pending_errors.json"

# Minimum confidence for auto-PR creation
MIN_FIX_CONFIDENCE = 0.5


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


def _error_to_dict(error: ErrorFixRequest, extra: dict = None) -> dict:
    """Convert ErrorFixRequest to dict for JSON storage."""
    data = {
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
    if extra:
        data.update(extra)
    return data


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
    """Request admin approval for an error fix with automatic PR creation.

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
    from git_api import GitAPI

    request_id = f"err_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    branch_name = f"fix/{request_id}"

    error_request = ErrorFixRequest(
        request_id=request_id,
        error_type=error_type,
        error_message=error_message[:500],
        skill=skill,
        action=action,
        context=context[:500],
        created_at=datetime.now(),
    )

    extra_data = {}

    # Try to generate a fix via Claude API
    logger.info(f"Generating fix for {skill}:{action} - {error_type}")

    fix_data = await generate_fix(
        error_type=error_type,
        error_message=error_message,
        skill=skill,
        action=action,
        context=context,
        settings=settings,
    )

    if not fix_data or fix_data.get("confidence", 0) < MIN_FIX_CONFIDENCE:
        # Low confidence or no fix - just notify admin without PR
        analysis = fix_data.get("analysis", "Automatischer Fix nicht möglich") if fix_data else "Fix-Generierung fehlgeschlagen"

        approval_text = (
            f"🔴 *Fehler aufgetreten*\n\n"
            f"**Skill:** {skill}\n"
            f"**Aktion:** {action}\n"
            f"**Fehler:** `{error_type}`\n\n"
            f"```\n{error_message[:200]}\n```\n\n"
            f"**Analyse:** {analysis}\n\n"
            f"_Kein automatischer Fix möglich._"
        )

        extra_data["fix_analysis"] = analysis
        extra_data["has_pr"] = False

        await send_message(settings.admin_telegram_id, approval_text, settings)

        # Store for reference (no approval needed)
        pending = _load_pending_errors()
        pending[request_id] = _error_to_dict(error_request, extra_data)
        _save_pending_errors(pending)

        logger.info(f"Error logged without PR: {request_id} - {analysis}")
        return request_id

    # High confidence fix - create PR
    logger.info(f"Fix generated with confidence {fix_data.get('confidence')}, creating PR...")

    git = GitAPI()
    original_branch = git.get_current_branch()

    try:
        # Create fix branch
        branch_result = git.create_branch(branch_name)
        if not branch_result.get("success"):
            raise Exception(f"Branch creation failed: {branch_result.get('error')}")

        # Apply the fix
        apply_result = await apply_fix(fix_data, settings)
        if not apply_result.get("success"):
            raise Exception(f"Fix application failed: {apply_result.get('error')}")

        # Commit changes
        commit_msg = fix_data.get("commit_message", f"fix({skill}): auto-fix for {error_type}")
        commit_result = git.commit(message=commit_msg, add_all=True)
        if not commit_result.get("success"):
            raise Exception(f"Commit failed: {commit_result.get('error')}")

        # Push branch
        push_result = git.push(set_upstream=True)
        if not push_result.get("success"):
            raise Exception(f"Push failed: {push_result.get('error')}")

        # Create PR
        pr_body = f"""## Automatisch generierter Fix

**Fehler:** `{error_type}`
**Skill:** {skill}
**Aktion:** {action}

### Analyse
{fix_data.get('analysis', 'Keine Analyse verfügbar')}

### Änderungen
{fix_data.get('fix_description', 'Keine Beschreibung verfügbar')}

### Geänderte Dateien
{chr(10).join('- ' + f for f in apply_result.get('files', []))}

---
_Automatisch generiert von Homelab Assistant_
"""
        pr_result = git.create_pr(
            title=commit_msg,
            body=pr_body,
            base=original_branch,
        )

        if not pr_result.get("success"):
            raise Exception(f"PR creation failed: {pr_result.get('error')}")

        # Store PR info
        extra_data = {
            "pr_url": pr_result.get("url"),
            "pr_number": pr_result.get("number"),
            "branch_name": branch_name,
            "fix_analysis": fix_data.get("analysis"),
            "has_pr": True,
        }

        # Switch back to original branch
        git.checkout(original_branch)

        # Send approval request to admin with PR link
        approval_text = (
            f"🔧 *Fix bereit zur Überprüfung*\n\n"
            f"**Skill:** {skill}\n"
            f"**Fehler:** `{error_type}`\n\n"
            f"**Analyse:** {fix_data.get('analysis', '')}\n\n"
            f"**Fix:** {fix_data.get('fix_description', '')}\n\n"
            f"🔗 [Pull Request #{pr_result.get('number')}]({pr_result.get('url')})\n\n"
            f"_Confidence: {fix_data.get('confidence', 0):.0%}_"
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
        pending[request_id] = _error_to_dict(error_request, extra_data)
        _save_pending_errors(pending)

        logger.info(f"PR created: {pr_result.get('url')} for {request_id}")
        return request_id

    except Exception as e:
        logger.error(f"Failed to create fix PR: {e}")

        # Cleanup: switch back to original branch and delete fix branch
        try:
            git.checkout(original_branch)
            git.delete_branch(branch_name, force=True)
        except Exception:
            pass

        # Notify admin about failure
        await send_message(
            settings.admin_telegram_id,
            f"❌ *Fix-PR Erstellung fehlgeschlagen*\n\n"
            f"**Skill:** {skill}\n"
            f"**Fehler:** `{error_type}`\n\n"
            f"```\n{str(e)[:300]}\n```",
            settings,
        )

        return None


async def handle_error_fix_approval(
    request_id: str,
    approved: bool,
    settings: Settings,
) -> str:
    """Handle admin's approval or rejection of an error fix PR.

    Args:
        request_id: The error fix request ID
        approved: True if approved, False if rejected
        settings: Application settings

    Returns:
        Status message
    """
    from git_api import GitAPI

    pending = _load_pending_errors()

    if request_id not in pending:
        return "❌ Fehler-Anfrage nicht gefunden."

    error_data = pending.pop(request_id)
    _save_pending_errors(pending)

    error_request = _dict_to_error(error_data)

    # Check if this has a PR
    pr_number = error_data.get('pr_number')
    has_pr = error_data.get('has_pr', False)

    if not has_pr or not pr_number:
        # No PR - this was just a notification
        return "ℹ️ Keine Aktion erforderlich (kein PR vorhanden)."

    git = GitAPI()

    if not approved:
        # Rejected - close PR and delete branch
        logger.info(f"Error fix {request_id} rejected, closing PR #{pr_number}")

        close_result = git.close_pr(pr_number, delete_branch=True)

        # Update admin message
        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"❌ *Abgelehnt*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"PR #{pr_number} geschlossen.",
                settings=settings,
            )

        return f"PR #{pr_number} geschlossen und Branch gelöscht."

    # Approved - merge PR
    logger.info(f"Error fix {request_id} approved, merging PR #{pr_number}")

    # Update admin message to show processing
    if error_request.message_id:
        await edit_message_text(
            chat_id=settings.admin_telegram_id,
            message_id=error_request.message_id,
            text=f"⏳ *Wird gemerged...*\n\n"
                 f"**Skill:** {error_request.skill}\n"
                 f"**Fehler:** `{error_request.error_type}`",
            settings=settings,
        )

    try:
        merge_result = git.merge_pr(pr_number, delete_branch=True)

        if not merge_result.get("success"):
            raise Exception(merge_result.get("error"))

        # Pull changes to local
        status = git.status()
        if status.get("branch") != "master":
            git.checkout("master")

        # Pull merged changes
        await self_annealing.git_pull(settings)

        # Reload skills
        from .tool_registry import reload_registry
        reload_registry(settings)

        # Update admin message with success
        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"✅ *Fix angewendet*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"PR #{pr_number} gemerged. Skills neu geladen.",
                settings=settings,
            )

        logger.info(f"Error fix merged: {request_id}")
        return f"PR #{pr_number} gemerged und Skills neu geladen."

    except Exception as e:
        logger.error(f"Error merging PR: {e}")

        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"❌ *Merge fehlgeschlagen*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"Fehler: {str(e)[:200]}",
                settings=settings,
            )

        return f"Merge fehlgeschlagen: {str(e)}"


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
