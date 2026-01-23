"""Skill creation via Claude API with admin approval workflow."""

import asyncio
import uuid
import logging
from datetime import datetime
from pathlib import Path

from .config import Settings
from .models import ApprovalRequest, ApprovalStatus
from .telegram_handler import send_message, send_approval_request, edit_message_text

logger = logging.getLogger(__name__)

# In-memory storage for pending approvals
# In production, consider using Redis or a database
pending_approvals: dict[str, ApprovalRequest] = {}
_approvals_lock = asyncio.Lock()


async def request_skill_creation(
    user_request: str,
    requester_name: str,
    requester_id: int,
    chat_id: int,
    settings: Settings,
) -> str:
    """Request admin approval for skill creation.

    Args:
        user_request: Original user message
        requester_name: Name of the user making the request
        requester_id: Telegram user ID of the requester
        chat_id: Chat ID to respond to
        settings: Application settings

    Returns:
        Message to send to the user
    """
    request_id = str(uuid.uuid4())[:8]

    approval = ApprovalRequest(
        request_id=request_id,
        user_request=user_request,
        requester_name=requester_name,
        requester_id=requester_id,
        chat_id=chat_id,
        created_at=datetime.now(),
    )

    async with _approvals_lock:
        pending_approvals[request_id] = approval

    # Send approval request to admin
    approval_text = (
        f"🔔 *Neue Skill-Anfrage*\n\n"
        f"Von: {requester_name}\n"
        f"Anfrage: \"{user_request}\"\n\n"
        f"Soll ich einen neuen Skill erstellen/erweitern?"
    )

    message_id = await send_approval_request(
        admin_id=settings.admin_telegram_id,
        text=approval_text,
        request_id=request_id,
        settings=settings,
    )

    if message_id:
        approval.message_id = message_id

    # Start timeout task
    asyncio.create_task(approval_timeout(request_id, settings))

    logger.info(f"Skill creation requested: {request_id} - {user_request[:50]}")

    return "⏳ Deine Anfrage wurde an den Admin gesendet. Du bekommst Bescheid!"


async def approval_timeout(request_id: str, settings: Settings):
    """Auto-reject approval after timeout.

    Args:
        request_id: The approval request ID
        settings: Application settings
    """
    await asyncio.sleep(settings.approval_timeout_minutes * 60)

    async with _approvals_lock:
        if request_id not in pending_approvals:
            return  # Already handled

        approval = pending_approvals.pop(request_id)
        approval.status = ApprovalStatus.EXPIRED

    logger.info(f"Approval request {request_id} expired")

    # Notify user
    await send_message(
        approval.chat_id,
        f"⏰ Anfrage abgelaufen (keine Admin-Antwort):\n\"{approval.user_request}\"",
        settings,
    )

    # Update admin message if we have the ID
    if approval.message_id:
        await edit_message_text(
            chat_id=settings.admin_telegram_id,
            message_id=approval.message_id,
            text=f"⏰ *Abgelaufen*\n\n"
                 f"Von: {approval.requester_name}\n"
                 f"Anfrage: \"{approval.user_request}\"",
            settings=settings,
        )


async def handle_approval(request_id: str, approved: bool, settings: Settings) -> str:
    """Handle admin's approval or rejection decision.

    Args:
        request_id: The approval request ID
        approved: True if approved, False if rejected
        settings: Application settings

    Returns:
        Status message
    """
    async with _approvals_lock:
        if request_id not in pending_approvals:
            return "❌ Anfrage nicht gefunden oder bereits abgelaufen."

        approval = pending_approvals.pop(request_id)

    if not approved:
        approval.status = ApprovalStatus.REJECTED
        logger.info(f"Approval request {request_id} rejected")

        # Notify user
        await send_message(
            approval.chat_id,
            f"❌ Deine Anfrage wurde abgelehnt:\n\"{approval.user_request}\"",
            settings,
        )

        # Update admin message
        if approval.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=approval.message_id,
                text=f"❌ *Abgelehnt*\n\n"
                     f"Von: {approval.requester_name}\n"
                     f"Anfrage: \"{approval.user_request}\"",
                settings=settings,
            )

        return "Anfrage abgelehnt."

    # Approved - create skill via Claude API
    approval.status = ApprovalStatus.APPROVED
    logger.info(f"Approval request {request_id} approved, creating skill...")

    # Update admin message to show processing
    if approval.message_id:
        await edit_message_text(
            chat_id=settings.admin_telegram_id,
            message_id=approval.message_id,
            text=f"⏳ *Wird erstellt...*\n\n"
                 f"Von: {approval.requester_name}\n"
                 f"Anfrage: \"{approval.user_request}\"",
            settings=settings,
        )

    try:
        result = await create_skill(approval.user_request, settings)

        # Notify user
        await send_message(
            approval.chat_id,
            f"✅ Skill erstellt! Du kannst es jetzt nochmal versuchen:\n\"{approval.user_request}\"",
            settings,
        )

        # Update admin message with result
        if approval.message_id:
            # Truncate result for Telegram
            truncated_result = result[:1500] + "..." if len(result) > 1500 else result
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=approval.message_id,
                text=f"✅ *Skill erstellt*\n\n"
                     f"Von: {approval.requester_name}\n"
                     f"Anfrage: \"{approval.user_request}\"\n\n"
                     f"Ergebnis:\n```\n{truncated_result}\n```",
                settings=settings,
            )

        return f"Skill erstellt: {result[:200]}..."

    except Exception as e:
        logger.error(f"Error creating skill: {e}")

        # Notify user of failure
        await send_message(
            approval.chat_id,
            f"❌ Fehler bei der Skill-Erstellung:\n{str(e)}",
            settings,
        )

        return f"Fehler: {str(e)}"


async def create_skill(user_request: str, settings: Settings) -> str:
    """Create or extend a skill using Claude API.

    Args:
        user_request: The user's original request describing what they want
        settings: Application settings

    Returns:
        Claude's response describing what was created
    """
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY nicht konfiguriert")

    # Import here to avoid startup error if not installed
    try:
        from anthropic import Anthropic
    except ImportError:
        raise ImportError("anthropic Paket nicht installiert: pip install anthropic")

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Load existing skill structure for context
    skill_context = load_skill_context(settings)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""Erstelle oder erweitere einen Skill für folgende Anfrage:
"{user_request}"

## Bestehende Skill-Struktur:
{skill_context}

## Skill-Format (SKILL.md):
- Frontmatter mit name, description, version, triggers
- Abschnitte: Goal, Inputs, Tools, Outputs, Commands, Edge Cases

## Script-Format (*_api.py):
- argparse CLI mit Subcommands
- --json Flag für strukturierte Ausgabe
- load_env() für .env Unterstützung
- Fehler auf stderr

## Aufgabe:
1. Analysiere welchen Skill erstellen/erweitern
2. Beschreibe die nötigen Änderungen an SKILL.md
3. Beschreibe die nötigen Änderungen/Ergänzungen am Script
4. Gib konkreten Code wenn möglich

Bitte antworte auf Deutsch.""",
            }
        ],
    )

    return message.content[0].text


def load_skill_context(settings: Settings) -> str:
    """Load existing skill structure for Claude context.

    Args:
        settings: Application settings

    Returns:
        String describing existing skills
    """
    skills_base = settings.project_root / ".claude" / "skills"
    if not skills_base.exists():
        return "Keine bestehenden Skills gefunden."

    context_parts = ["Bestehende Skills:"]

    for skill_dir in sorted(skills_base.iterdir()):
        if not skill_dir.is_dir():
            continue

        skill_name = skill_dir.name
        skill_md = skill_dir / "SKILL.md"
        scripts_dir = skill_dir / "scripts"

        parts = [f"\n### {skill_name}"]

        # Read first 500 chars of SKILL.md if exists
        if skill_md.exists():
            try:
                content = skill_md.read_text()[:500]
                parts.append(f"SKILL.md:\n{content}...")
            except Exception:
                pass

        # List scripts
        if scripts_dir.exists():
            scripts = [f.name for f in scripts_dir.glob("*.py")]
            if scripts:
                parts.append(f"Scripts: {', '.join(scripts)}")

        context_parts.append("\n".join(parts))

    return "\n".join(context_parts)


def get_pending_approvals() -> list[ApprovalRequest]:
    """Get all pending approval requests.

    Returns:
        List of pending ApprovalRequest objects
    """
    return [a for a in pending_approvals.values() if a.status == ApprovalStatus.PENDING]


def cancel_approval(request_id: str) -> bool:
    """Cancel a pending approval request.

    Args:
        request_id: The approval request ID to cancel

    Returns:
        True if cancelled, False if not found
    """
    if request_id in pending_approvals:
        del pending_approvals[request_id]
        return True
    return False
