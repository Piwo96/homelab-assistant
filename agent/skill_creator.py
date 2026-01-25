"""Skill creation via Claude API with admin approval workflow."""

import asyncio
import json
import re
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .models import ApprovalRequest, ApprovalStatus
from .telegram_handler import send_message, send_approval_request, edit_message_text
from . import self_annealing

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

        # Self-annealing: commit and push changes
        anneal_result = await self_annealing.commit_and_push(
            f"feat(skill): auto-created via agent request",
            settings=settings,
        )
        if anneal_result.get("success"):
            logger.info(f"Self-annealing: {anneal_result.get('output')}")
        else:
            logger.warning(f"Self-annealing failed: {anneal_result.get('output')}")

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
        Summary of what was created/modified
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
        max_tokens=8192,
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

## WICHTIG: Ausgabeformat

Du MUSST deine Antwort als JSON zurückgeben mit folgendem Format:

```json
{{
  "skill_name": "name-des-skills",
  "action": "create" oder "extend",
  "summary": "Kurze Beschreibung was erstellt/geändert wurde",
  "files": [
    {{
      "path": "relativer/pfad/zur/datei.md",
      "content": "Vollständiger Dateiinhalt hier..."
    }}
  ]
}}
```

- skill_name: Name des Skills (lowercase, mit Bindestrichen)
- action: "create" für neuen Skill, "extend" für Erweiterung
- summary: 1-2 Sätze was gemacht wurde
- files: Array mit allen Dateien die erstellt/überschrieben werden sollen
  - path: Relativer Pfad ab .claude/skills/ (z.B. "pihole/SKILL.md" oder "pihole/scripts/pihole_api.py")
  - content: Vollständiger Inhalt der Datei

Gib NUR das JSON zurück, keine weiteren Erklärungen.""",
            }
        ],
    )

    response_text = message.content[0].text

    # Parse JSON from response
    files_written = await _parse_and_write_skill_files(response_text, settings)

    if not files_written:
        logger.warning("No files were written from Claude response")
        return f"Keine Dateien erstellt. Claude Antwort: {response_text[:500]}..."

    return f"Skill '{files_written['skill_name']}' ({files_written['action']}): {files_written['summary']} - {len(files_written['files'])} Datei(en) geschrieben"


async def _parse_and_write_skill_files(response_text: str, settings: Settings) -> dict[str, Any] | None:
    """Parse Claude's JSON response and write skill files to disk.

    Args:
        response_text: Claude's response containing JSON
        settings: Application settings

    Returns:
        Parsed data with written files info, or None if parsing failed
    """
    # Try to extract JSON from response (might be wrapped in markdown code block)
    json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        # Try to parse the whole response as JSON
        json_str = response_text.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Claude response: {e}")
        logger.debug(f"Response was: {response_text[:1000]}")
        return None

    skill_name = data.get("skill_name")
    files = data.get("files", [])

    if not skill_name or not files:
        logger.error(f"Missing skill_name or files in response: {data}")
        return None

    skills_base = settings.project_root / ".claude" / "skills"
    files_written = []

    for file_info in files:
        rel_path = file_info.get("path", "")
        content = file_info.get("content", "")

        if not rel_path or not content:
            logger.warning(f"Skipping file with missing path or content: {file_info}")
            continue

        # Security: ensure path stays within skills directory
        full_path = (skills_base / rel_path).resolve()
        if not str(full_path).startswith(str(skills_base.resolve())):
            logger.error(f"Path traversal attempt blocked: {rel_path}")
            continue

        # Create parent directories
        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        full_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote skill file: {full_path}")
        files_written.append(str(rel_path))

    return {
        "skill_name": skill_name,
        "action": data.get("action", "create"),
        "summary": data.get("summary", "Skill erstellt"),
        "files": files_written,
    }


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
