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

    # High confidence fix - create branch
    logger.info(f"Fix generated with confidence {fix_data.get('confidence')}, creating fix branch...")

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

        # Push branch to remote
        push_result = git.push(set_upstream=True)
        if not push_result.get("success"):
            raise Exception(f"Push failed: {push_result.get('error')}")

        # Generate compare URL (shows diff on GitHub)
        compare_url = git.get_github_compare_url(original_branch, branch_name)

        # Store branch info
        extra_data = {
            "compare_url": compare_url,
            "branch_name": branch_name,
            "original_branch": original_branch,
            "fix_analysis": fix_data.get("analysis"),
            "commit_message": commit_msg,
            "files_changed": apply_result.get("files", []),
            "has_fix": True,
        }

        # Switch back to original branch
        git.checkout(original_branch)

        # Send approval request to admin with compare link
        files_list = ", ".join(apply_result.get("files", []))
        approval_text = (
            f"🔧 *Fix bereit zur Überprüfung*\n\n"
            f"**Skill:** {skill}\n"
            f"**Fehler:** `{error_type}`\n\n"
            f"**Analyse:** {fix_data.get('analysis', '')}\n\n"
            f"**Fix:** {fix_data.get('fix_description', '')}\n\n"
            f"**Dateien:** {files_list}\n\n"
            f"🔗 [Änderungen ansehen]({compare_url})\n\n"
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

        logger.info(f"Fix branch created: {compare_url} for {request_id}")
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
    """Handle admin's approval or rejection of an error fix branch.

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

    # Check if this has a fix branch
    branch_name = error_data.get('branch_name')
    has_fix = error_data.get('has_fix', False)

    if not has_fix or not branch_name:
        # No fix branch - this was just a notification
        return "ℹ️ Keine Aktion erforderlich (kein Fix vorhanden)."

    git = GitAPI()
    original_branch = error_data.get('original_branch', 'master')

    if not approved:
        # Rejected - delete fix branch (local and remote)
        logger.info(f"Error fix {request_id} rejected, deleting branch {branch_name}")

        # Delete remote branch
        git.delete_remote_branch(branch_name)
        # Delete local branch
        git.delete_branch(branch_name, force=True)

        # Update admin message
        if error_request.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=error_request.message_id,
                text=f"❌ *Abgelehnt*\n\n"
                     f"**Skill:** {error_request.skill}\n"
                     f"**Fehler:** `{error_request.error_type}`\n\n"
                     f"Branch `{branch_name}` gelöscht.",
                settings=settings,
            )

        return f"Branch {branch_name} gelöscht."

    # Approved - merge branch locally and push
    logger.info(f"Error fix {request_id} approved, merging branch {branch_name}")

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
        # Ensure we're on the original branch (usually master)
        current = git.get_current_branch()
        if current != original_branch:
            checkout_result = git.checkout(original_branch)
            if not checkout_result.get("success"):
                raise Exception(f"Checkout failed: {checkout_result.get('error')}")

        # Merge the fix branch
        merge_result = git.merge_branch(branch_name)
        if not merge_result.get("success"):
            raise Exception(f"Merge failed: {merge_result.get('error')}")

        # Push to remote
        push_result = git.push()
        if not push_result.get("success"):
            raise Exception(f"Push failed: {push_result.get('error')}")

        # Delete remote fix branch
        git.delete_remote_branch(branch_name)
        # Delete local fix branch
        git.delete_branch(branch_name, force=True)

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
                     f"Branch gemerged und gepusht. Skills neu geladen.",
                settings=settings,
            )

        logger.info(f"Error fix merged: {request_id}")
        return f"Branch {branch_name} gemerged und gepusht. Skills neu geladen."

    except Exception as e:
        logger.error(f"Error merging branch: {e}")

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
