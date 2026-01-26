"""Skill creation via Claude API with feature branch approval workflow.

When a user requests a new capability:
1. Admin approves the initial request
2. Claude API generates skill code
3. Changes are pushed to a feature branch
4. Admin receives GitHub compare link for review
5. On second approval, branch is merged and skills reloaded
6. On rejection, branch is deleted
"""

import asyncio
import json
import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

# Add skills path to import git_api
_git_scripts_path = str(Path(__file__).parent.parent / ".claude" / "skills" / "git" / "scripts")
if _git_scripts_path not in sys.path:
    sys.path.insert(0, _git_scripts_path)

from .config import Settings
from .models import ApprovalRequest, ApprovalStatus
from .telegram_handler import send_message, send_approval_request, edit_message_text
from .tool_registry import reload_registry

logger = logging.getLogger(__name__)

# File-based storage for pending skill approvals (persists across restarts)
PENDING_SKILLS_FILE = Path(__file__).parent.parent / ".claude" / "pending_skills.json"

# In-memory storage for initial approval requests (before skill creation)
pending_approvals: dict[str, ApprovalRequest] = {}
_approvals_lock = asyncio.Lock()


def _load_pending_skills() -> dict[str, dict]:
    """Load pending skill merge requests from file."""
    if not PENDING_SKILLS_FILE.exists():
        return {}
    try:
        return json.loads(PENDING_SKILLS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load pending skills: {e}")
        return {}


def _save_pending_skills(skills: dict[str, dict]) -> None:
    """Save pending skill merge requests to file."""
    try:
        PENDING_SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        PENDING_SKILLS_FILE.write_text(json.dumps(skills, indent=2, default=str))
    except OSError as e:
        logger.error(f"Failed to save pending skills: {e}")


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
    request_id = f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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

    For initial approval: creates skill and pushes to feature branch.
    For merge approval: merges branch and cleans up.

    Args:
        request_id: The approval request ID
        approved: True if approved, False if rejected
        settings: Application settings

    Returns:
        Status message
    """
    # Check if this is a merge approval (stored in file)
    pending_skills = _load_pending_skills()
    if request_id in pending_skills:
        return await handle_skill_merge_approval(request_id, approved, settings)

    # Otherwise, it's an initial skill creation approval (in memory)
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

    # Approved - create skill and push to feature branch
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
        result = await create_skill_on_branch(
            request_id=request_id,
            user_request=approval.user_request,
            requester_name=approval.requester_name,
            chat_id=approval.chat_id,
            settings=settings,
        )
        return result

    except Exception as e:
        logger.error(f"Error creating skill: {e}")

        # Notify user of failure
        await send_message(
            approval.chat_id,
            f"❌ Fehler bei der Skill-Erstellung:\n{str(e)}",
            settings,
        )

        # Update admin message
        if approval.message_id:
            await edit_message_text(
                chat_id=settings.admin_telegram_id,
                message_id=approval.message_id,
                text=f"❌ *Fehler*\n\n"
                     f"Von: {approval.requester_name}\n"
                     f"Anfrage: \"{approval.user_request}\"\n\n"
                     f"Fehler: {str(e)[:200]}",
                settings=settings,
            )

        return f"Fehler: {str(e)}"


async def create_skill_on_branch(
    request_id: str,
    user_request: str,
    requester_name: str,
    chat_id: int,
    settings: Settings,
) -> str:
    """Create skill on a feature branch and request merge approval.

    Args:
        request_id: The skill request ID
        user_request: The user's original request
        requester_name: Name of the requester
        chat_id: Chat ID to respond to
        settings: Application settings

    Returns:
        Status message
    """
    from git_api import GitAPI

    branch_name = f"feat/{request_id}"
    git = GitAPI()
    original_branch = git.get_current_branch()

    try:
        # Create feature branch
        branch_result = git.create_branch(branch_name)
        if not branch_result.get("success"):
            raise Exception(f"Branch creation failed: {branch_result.get('error')}")

        # Generate and write skill files
        skill_result = await create_skill(user_request, settings)

        if not skill_result.get("success"):
            raise Exception(skill_result.get("error", "Skill-Erstellung fehlgeschlagen"))

        # Commit changes
        commit_msg = f"feat(skill): {skill_result.get('summary', 'auto-created skill')}"
        commit_result = git.commit(message=commit_msg, add_all=True)
        if not commit_result.get("success"):
            raise Exception(f"Commit failed: {commit_result.get('error')}")

        # Push branch to remote
        push_result = git.push(set_upstream=True)
        if not push_result.get("success"):
            raise Exception(f"Push failed: {push_result.get('error')}")

        # Generate compare URL
        compare_url = git.get_github_compare_url(original_branch, branch_name)

        # Switch back to original branch
        git.checkout(original_branch)

        # Store skill data for merge approval
        skill_data = {
            "request_id": request_id,
            "user_request": user_request,
            "requester_name": requester_name,
            "chat_id": chat_id,
            "branch_name": branch_name,
            "original_branch": original_branch,
            "compare_url": compare_url,
            "skill_name": skill_result.get("skill_name"),
            "action": skill_result.get("action"),
            "summary": skill_result.get("summary"),
            "files": skill_result.get("files", []),
            "created_at": datetime.now().isoformat(),
        }

        pending_skills = _load_pending_skills()
        pending_skills[request_id] = skill_data
        _save_pending_skills(pending_skills)

        # Send merge approval request to admin
        files_list = ", ".join(skill_result.get("files", []))
        approval_text = (
            f"🔧 *Skill bereit zur Überprüfung*\n\n"
            f"**Von:** {requester_name}\n"
            f"**Anfrage:** \"{user_request}\"\n\n"
            f"**Skill:** {skill_result.get('skill_name')}\n"
            f"**Aktion:** {skill_result.get('action')}\n"
            f"**Dateien:** {files_list}\n\n"
            f"🔗 [Änderungen ansehen]({compare_url})\n\n"
            f"_Merge in master?_"
        )

        await send_approval_request(
            admin_id=settings.admin_telegram_id,
            text=approval_text,
            request_id=request_id,
            settings=settings,
        )

        # Notify user that skill is being reviewed
        await send_message(
            chat_id,
            f"⏳ Skill wurde erstellt und wartet auf Merge-Genehmigung.\n"
            f"Du bekommst Bescheid!",
            settings,
        )

        logger.info(f"Skill branch created: {branch_name} for {request_id}")
        return f"Skill-Branch erstellt: {branch_name}"

    except Exception as e:
        logger.error(f"Failed to create skill branch: {e}")

        # Cleanup: switch back to original branch and delete feature branch
        try:
            git.checkout(original_branch)
            git.delete_branch(branch_name, force=True)
        except Exception:
            pass

        raise


async def handle_skill_merge_approval(
    request_id: str,
    approved: bool,
    settings: Settings,
) -> str:
    """Handle admin's approval or rejection of a skill merge.

    Args:
        request_id: The skill request ID
        approved: True if approved, False if rejected
        settings: Application settings

    Returns:
        Status message
    """
    from git_api import GitAPI

    pending_skills = _load_pending_skills()

    if request_id not in pending_skills:
        return "❌ Skill-Anfrage nicht gefunden."

    skill_data = pending_skills.pop(request_id)
    _save_pending_skills(pending_skills)

    branch_name = skill_data.get("branch_name")
    original_branch = skill_data.get("original_branch", "master")
    chat_id = skill_data.get("chat_id")
    user_request = skill_data.get("user_request")

    git = GitAPI()

    if not approved:
        # Rejected - delete branch (local and remote)
        logger.info(f"Skill merge {request_id} rejected, deleting branch {branch_name}")

        git.delete_remote_branch(branch_name)
        git.delete_branch(branch_name, force=True)

        # Notify user
        await send_message(
            chat_id,
            f"❌ Skill-Änderungen wurden abgelehnt:\n\"{user_request}\"",
            settings,
        )

        return f"Branch {branch_name} gelöscht."

    # Approved - merge branch locally and push
    logger.info(f"Skill merge {request_id} approved, merging branch {branch_name}")

    try:
        # Ensure we're on the original branch
        current = git.get_current_branch()
        if current != original_branch:
            checkout_result = git.checkout(original_branch)
            if not checkout_result.get("success"):
                raise Exception(f"Checkout failed: {checkout_result.get('error')}")

        # Merge the feature branch
        merge_result = git.merge_branch(branch_name)
        if not merge_result.get("success"):
            raise Exception(f"Merge failed: {merge_result.get('error')}")

        # Push to remote
        push_result = git.push()
        if not push_result.get("success"):
            raise Exception(f"Push failed: {push_result.get('error')}")

        # Delete remote and local feature branch
        git.delete_remote_branch(branch_name)
        git.delete_branch(branch_name, force=True)

        # Reload tool registry with new skills
        reload_registry(settings)

        # Notify user
        await send_message(
            chat_id,
            f"✅ Skill erstellt! Du kannst es jetzt nochmal versuchen:\n\"{user_request}\"",
            settings,
        )

        logger.info(f"Skill merged: {request_id}")
        return f"Branch {branch_name} gemerged und gepusht. Skills neu geladen."

    except Exception as e:
        logger.error(f"Error merging skill branch: {e}")

        await send_message(
            chat_id,
            f"❌ Merge fehlgeschlagen:\n{str(e)}",
            settings,
        )

        return f"Merge fehlgeschlagen: {str(e)}"


async def create_skill(user_request: str, settings: Settings) -> dict[str, Any]:
    """Create or extend a skill using Claude API.

    Args:
        user_request: The user's original request describing what they want
        settings: Application settings

    Returns:
        Dict with skill_name, action, summary, files, success
    """
    if not settings.anthropic_api_key:
        return {"success": False, "error": "ANTHROPIC_API_KEY nicht konfiguriert"}

    # Import here to avoid startup error if not installed
    try:
        from anthropic import Anthropic
    except ImportError:
        return {"success": False, "error": "anthropic Paket nicht installiert: pip install anthropic"}

    client = Anthropic(api_key=settings.anthropic_api_key)

    # Load existing skill structure for context
    skill_context = load_skill_context(settings)

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=16384,  # Increased for complex skills with full scripts
        messages=[
            {
                "role": "user",
                "content": f"""Erstelle oder erweitere einen Skill für folgende Anfrage:
"{user_request}"

## Bestehende Skill-Struktur:
{skill_context}

## KRITISCHE REGELN - VERSTÖSSE WERDEN ABGELEHNT:

### REGEL 1: BESTEHENDEN CODE NIEMALS ÄNDERN!
Bei "extend" darfst du AUSSCHLIESSLICH:
- Neue Methoden zur Klasse HINZUFÜGEN (am Ende)
- Neue argparse Subcommands HINZUFÜGEN (am Ende)
- Neue Handler im main() HINZUFÜGEN (am Ende)
- Neue Imports HINZUFÜGEN (am Anfang)

Du darfst NIEMALS:
- Bestehende Methoden ändern, umbenennen oder "verbessern"
- Session-Management, Auth-Logik oder API-Requests ändern
- Bestehende Imports entfernen oder ändern
- Code "refactoren" oder "aufräumen"
- Reihenfolge von bestehendem Code ändern

### REGEL 2: ZEILE FÜR ZEILE PRÜFEN
Bevor du antwortest:
1. Kopiere den KOMPLETTEN bestehenden Code 1:1
2. Füge NUR am Ende neue Methoden/Commands hinzu
3. Prüfe: Ist JEDE bestehende Zeile IDENTISCH? Wenn nicht → FEHLER!

### REGEL 3: BEI "create"
Nur für komplett neue Skills die es noch nicht gibt.

## Skill-Format (SKILL.md):
- Frontmatter mit name, description, version, triggers
- Abschnitte: Goal, Inputs, Tools, Outputs, Commands, Edge Cases
- Bei extend: Nur neue Commands zur bestehenden Liste hinzufügen

## Script-Format (*_api.py):
- argparse CLI mit Subcommands
- --json Flag für strukturierte Ausgabe
- load_env() für .env Unterstützung
- Bei extend: NUR neue add_parser() und Handler hinzufügen

## WICHTIG: Ausgabeformat

Du MUSST deine Antwort als JSON zurückgeben. Das Format hängt von der Aktion ab:

### Bei "create" (neuer Skill):
```json
{{
  "skill_name": "name-des-skills",
  "action": "create",
  "summary": "Kurze Beschreibung des neuen Skills",
  "new_files": [
    {{
      "path": "name-des-skills/scripts/name_des_skills_api.py",
      "content": "Vollständiger Dateiinhalt"
    }},
    {{
      "path": "name-des-skills/SKILL.md",
      "content": "Vollständiger Dateiinhalt"
    }}
  ]
}}
```

### Bei "extend" (bestehenden Skill erweitern):
```json
{{
  "skill_name": "name-des-skills",
  "action": "extend",
  "summary": "Kurze Beschreibung was hinzugefügt wurde",
  "edits": [
    {{
      "path": "name-des-skills/scripts/name_des_skills_api.py",
      "old_string": "EXAKTER bestehender Code der erweitert wird",
      "new_string": "Bestehender Code PLUS neue Methoden/Features"
    }}
  ]
}}
```

## EDIT-REGELN FÜR "extend":

1. **old_string**: EXAKT kopieren - jedes Zeichen, jede Einrückung
2. **new_string**: old_string + deine Erweiterungen
3. **Typisches Muster**: Finde das Ende einer Klasse/Funktion und füge dort hinzu

### Beispiel: Neue Methode zur Klasse hinzufügen
```json
{{
  "old_string": "    def existing_method(self):\\n        return result\\n\\n\\nclass AnotherClass:",
  "new_string": "    def existing_method(self):\\n        return result\\n\\n    def new_method(self):\\n        # Neue Funktionalität\\n        pass\\n\\n\\nclass AnotherClass:"
}}
```

### Beispiel: Neuen argparse Command hinzufügen
```json
{{
  "old_string": "    args = parser.parse_args()\\n\\n    if args.command == 'status':",
  "new_string": "    # Neuer Subparser\\n    new_parser = subparsers.add_parser('newcmd', help='New command')\\n    new_parser.add_argument('--flag', help='Flag')\\n\\n    args = parser.parse_args()\\n\\n    if args.command == 'newcmd':\\n        handle_newcmd(args)\\n    elif args.command == 'status':"
}}
```

## KRITISCH: Dateipfade

Die Pfade sind RELATIV zu `.claude/skills/`.
- ✅ RICHTIG: `"path": "proxmox/scripts/proxmox_api.py"`
- ❌ FALSCH: `"path": ".claude/skills/proxmox/scripts/proxmox_api.py"`

VERBOTEN bei extend:
- Bestehende Methoden ändern (auch nicht "verbessern")
- Session/Auth-Code ändern
- Bestehenden Code umstrukturieren

Gib NUR das JSON zurück, keine weiteren Erklärungen.""",
            }
        ],
    )

    response_text = message.content[0].text

    # Check if response was truncated
    if message.stop_reason == "max_tokens":
        logger.error("Claude response was truncated (max_tokens reached)")
        return {
            "success": False,
            "error": "Response too long - skill generation truncated. Try a simpler request.",
        }

    # Parse JSON from response
    return await _parse_and_write_skill_files(response_text, settings)


async def _parse_and_write_skill_files(response_text: str, settings: Settings) -> dict[str, Any]:
    """Parse Claude's JSON response and write/edit skill files.

    Handles two formats:
    - "create": new_files with full content
    - "extend": edits with old_string/new_string

    Args:
        response_text: Claude's response containing JSON
        settings: Application settings

    Returns:
        Dict with skill_name, action, summary, files, success
    """
    from .edit_utils import apply_changes

    logger.debug(f"Raw Claude response length: {len(response_text)}")

    json_str = None

    # Method 1: Find the JSON object by looking for the opening/closing braces
    # This is more robust than regex for nested content
    start_idx = response_text.find('{')
    if start_idx != -1:
        # Find matching closing brace by counting braces
        brace_count = 0
        in_string = False
        escape_next = False
        end_idx = start_idx

        for i, char in enumerate(response_text[start_idx:], start_idx):
            if escape_next:
                escape_next = False
                continue
            if char == '\\' and in_string:
                escape_next = True
                continue
            if char == '"' and not escape_next:
                in_string = not in_string
            elif not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i
                        break

        if brace_count == 0 and end_idx > start_idx:
            json_str = response_text[start_idx:end_idx + 1]
            logger.debug(f"Extracted JSON (brace matching): {len(json_str)} chars")
        elif brace_count > 0:
            # JSON is incomplete (truncated)
            logger.error(f"JSON appears truncated: {brace_count} unclosed braces")
            return {"success": False, "error": f"JSON truncated ({brace_count} unclosed braces) - response too long"}

    # Method 2: Fallback to regex if brace matching failed
    if not json_str:
        # Try to extract from markdown code block - use greedy match to get all content
        json_match = re.search(r'```json\s*(\{[\s\S]*\})\s*```', response_text)
        if json_match:
            json_str = json_match.group(1)
            logger.debug(f"Extracted JSON (regex markdown): {len(json_str)} chars")

    # Method 3: Try the whole response as JSON
    if not json_str:
        json_str = response_text.strip()
        logger.debug(f"Using whole response as JSON: {len(json_str)} chars")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON from Claude response: {e}")
        logger.error(f"JSON string (first 500 chars): {json_str[:500] if json_str else 'None'}")
        logger.error(f"JSON string (last 500 chars): {json_str[-500:] if json_str and len(json_str) > 500 else json_str}")
        return {"success": False, "error": f"JSON parse error: {e}"}

    skill_name = data.get("skill_name")
    action = data.get("action", "create")

    if not skill_name:
        logger.error(f"Missing skill_name in response: {data}")
        return {"success": False, "error": "Missing skill_name in response"}

    skills_base = settings.project_root / ".claude" / "skills"
    files_written = []

    # Handle based on action type
    if action == "extend":
        # Use edits for extending existing skills
        edits = data.get("edits", [])
        if not edits:
            # Fallback: check for old "files" format (backwards compatibility)
            files = data.get("files", [])
            if files:
                logger.warning("Received 'files' instead of 'edits' for extend action - using legacy mode")
                # Fall through to legacy handling below
            else:
                logger.error("Missing edits for extend action")
                return {"success": False, "error": "Missing edits for extend action"}
        else:
            # Apply edits using the new system
            result = apply_changes({"edits": edits}, skills_base)

            if not result["success"]:
                errors = result.get("errors", [])
                error_msgs = [e.get("error", "Unknown") for e in errors]
                return {"success": False, "error": f"Edit failed: {'; '.join(error_msgs)}"}

            files_written = result.get("files_edited", [])

    # Handle "create" action or legacy "files" format
    if action == "create" or (action == "extend" and not files_written):
        new_files = data.get("new_files", []) or data.get("files", [])

        if not new_files and action == "create":
            logger.error("Missing new_files for create action")
            return {"success": False, "error": "Missing new_files for create action"}

        for file_info in new_files:
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

    if not files_written:
        return {"success": False, "error": "No files were written or edited"}

    # Auto-generate keywords and examples for the new skill
    skill_path = skills_base / skill_name
    try:
        from .keyword_extractor import ensure_keywords
        from .example_generator import ensure_examples
        from .skill_loader import extract_commands_from_script

        # Extract commands from newly created script
        script_path = skill_path / "scripts" / f"{skill_name.replace('-', '_')}_api.py"
        commands = []
        if script_path.exists():
            cmd_list = extract_commands_from_script(script_path)
            commands = [{"name": c.name, "description": c.description} for c in cmd_list]

        # Generate keywords (async, need to run in event loop)
        # For extend actions, force regeneration to include new commands
        import asyncio
        loop = asyncio.get_event_loop()
        should_regenerate = (action == "extend")

        keywords = loop.run_until_complete(
            ensure_keywords(
                skill_path,
                settings.lm_studio_url,
                settings.lm_studio_model,
                force_regenerate=should_regenerate,
            )
        )
        if keywords:
            files_written.append(f"{skill_name}/keywords.json")
            logger.info(f"Generated {len(keywords)} keywords for {skill_name}")

        # Generate examples
        examples = loop.run_until_complete(
            ensure_examples(
                skill_path,
                settings.lm_studio_url,
                settings.lm_studio_model,
                commands,
                force_regenerate=should_regenerate,
            )
        )
        if examples:
            files_written.append(f"{skill_name}/examples.json")
            logger.info(f"Generated {len(examples)} examples for {skill_name}")

    except Exception as e:
        logger.warning(f"Could not auto-generate metadata for {skill_name}: {e}")

    return {
        "success": True,
        "skill_name": skill_name,
        "action": data.get("action", "create"),
        "summary": data.get("summary", "Skill erstellt"),
        "files": files_written,
    }


def load_skill_context(settings: Settings) -> str:
    """Load existing skill structure for Claude context.

    Includes FULL content of existing scripts to prevent rewrites.

    Args:
        settings: Application settings

    Returns:
        String describing existing skills with full code
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

        # Read FULL SKILL.md if exists (important for understanding structure)
        if skill_md.exists():
            try:
                content = skill_md.read_text()
                # Truncate if very long, but include more than before
                if len(content) > 2000:
                    content = content[:2000] + "\n... (truncated)"
                parts.append(f"SKILL.md:\n```markdown\n{content}\n```")
            except Exception:
                pass

        # Read FULL script content (critical to prevent rewrites!)
        if scripts_dir.exists():
            for script in scripts_dir.glob("*.py"):
                try:
                    script_content = script.read_text()
                    # Include full script to prevent Claude from rewriting
                    if len(script_content) > 5000:
                        script_content = script_content[:5000] + "\n# ... (truncated, but preserve all existing code!)"
                    parts.append(f"\n{script.name}:\n```python\n{script_content}\n```")
                except Exception:
                    pass

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


def is_skill_request(request_id: str) -> bool:
    """Check if a request ID is a skill request.

    Args:
        request_id: The request ID to check

    Returns:
        True if it's a skill request
    """
    return request_id.startswith("skill_")
