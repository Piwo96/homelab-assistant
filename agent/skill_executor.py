"""Skill execution - maps intents to skill script calls using dynamic registry."""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import List

from .config import Settings
from .models import IntentResult, SkillExecutionResult, is_admin_required
from .skill_loader import SkillDefinition
from .tool_registry import get_registry
from .error_approval import request_error_fix_approval

logger = logging.getLogger(__name__)


def get_skills_base_path(settings: Settings) -> Path:
    """Get the base path for skills."""
    return settings.project_root / ".claude" / "skills"


def build_command(intent: IntentResult, skill: SkillDefinition) -> List[str]:
    """Build command line arguments for a skill script.

    Args:
        intent: Parsed intent from classifier
        skill: Skill definition from registry

    Returns:
        Command list for subprocess
    """
    if not skill.script_path:
        return []

    cmd = ["python", str(skill.script_path)]

    # Don't add --json - let scripts use their user-friendly formatted output

    # Action is the subcommand
    if intent.action:
        cmd.append(intent.action)

    # Known positional argument names (order matters!)
    # These are passed as positional args, not flags
    positional_args = ["node", "vmid", "storage", "domain", "entity_id"]

    # First pass: add positional args in order
    for pos_arg in positional_args:
        if pos_arg in intent.args:
            cmd.append(str(intent.args[pos_arg]))

    # Second pass: add remaining args as flags
    for key, value in intent.args.items():
        if key in ("action",) or key in positional_args:
            continue  # Already handled
        cmd.append(f"--{key}")
        cmd.append(str(value))

    return cmd


async def execute_skill(
    intent: IntentResult,
    settings: Settings,
    user_id: int | None = None,
) -> SkillExecutionResult:
    """Execute a skill based on classified intent.

    Args:
        intent: Parsed intent from LM Studio
        settings: Application settings
        user_id: Telegram user ID (for permission checks)

    Returns:
        SkillExecutionResult with success status and output
    """
    skill_name = intent.skill

    # Check admin permission for infrastructure write operations
    if is_admin_required(skill_name, intent.action):
        if user_id != settings.admin_telegram_id:
            return SkillExecutionResult(
                success=False,
                output="",
                error=f"Nur Admins dürfen '{intent.action}' auf {skill_name} ausführen.",
                skill=skill_name,
                action=intent.action,
            )

    # Get skill from registry
    registry = get_registry(settings)
    skill = registry.get_skill_by_name(skill_name)

    if not skill:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Unbekannter Skill: {skill_name}. Verfügbar: {', '.join(registry.get_skill_names())}",
            skill=skill_name,
            action=intent.action,
        )

    if skill.is_documentation_only:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Skill '{skill_name}' ist nur Dokumentation (kein Script)",
            skill=skill_name,
            action=intent.action,
        )

    if not skill.script_path or not skill.script_path.exists():
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Script nicht gefunden für {skill_name}",
            skill=skill_name,
            action=intent.action,
        )

    # Validate action exists
    valid_actions = [cmd.name for cmd in skill.commands]
    action_normalized = intent.action.replace("_", "-")

    if valid_actions and action_normalized not in valid_actions:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Unbekannte Aktion '{intent.action}' für {skill_name}. Verfügbar: {', '.join(valid_actions)}",
            skill=skill_name,
            action=intent.action,
        )

    # Build command
    cmd = build_command(intent, skill)
    if not cmd:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Konnte Command nicht bauen für {skill_name}:{intent.action}",
            skill=skill_name,
            action=intent.action,
        )

    logger.info(f"Executing: {' '.join(cmd)}")

    # Execute in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(settings.project_root),
            ),
        )

        if result.returncode == 0:
            return SkillExecutionResult(
                success=True,
                output=format_skill_output(result.stdout, skill_name, intent.action),
                skill=skill_name,
                action=intent.action,
            )
        else:
            # Request admin approval for error fix
            error_msg = result.stderr or f"Exit code {result.returncode}"
            asyncio.create_task(
                request_error_fix_approval(
                    error_type="ScriptError",
                    error_message=error_msg[:500],
                    skill=skill_name,
                    action=intent.action,
                    context=f"Command: {' '.join(cmd)}",
                    settings=settings,
                )
            )
            return SkillExecutionResult(
                success=False,
                output="",
                error=result.stderr or f"Script fehlgeschlagen (Exit Code: {result.returncode})",
                skill=skill_name,
                action=intent.action,
            )

    except subprocess.TimeoutExpired:
        # Request admin approval for timeout error fix
        asyncio.create_task(
            request_error_fix_approval(
                error_type="TimeoutExpired",
                error_message="Script timeout after 30s",
                skill=skill_name,
                action=intent.action,
                context=f"Command: {' '.join(cmd)}",
                settings=settings,
            )
        )
        return SkillExecutionResult(
            success=False,
            output="",
            error="Timeout: Script brauchte zu lange (>30s)",
            skill=skill_name,
            action=intent.action,
        )
    except Exception as e:
        # Request admin approval for execution error fix
        asyncio.create_task(
            request_error_fix_approval(
                error_type=type(e).__name__,
                error_message=str(e),
                skill=skill_name,
                action=intent.action,
                context=f"Command: {' '.join(cmd)}",
                settings=settings,
            )
        )
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Ausführungsfehler: {str(e)}",
            skill=skill_name,
            action=intent.action,
        )


def format_skill_output(output: str, skill: str = "", action: str = "") -> str:  # noqa: ARG001
    """Format skill output for Telegram display.

    Scripts now have their own user-friendly formatting, so we just
    pass through the output and truncate for Telegram limits.

    Args:
        output: Output from skill script (already formatted)
        skill: Skill name (unused, kept for compatibility)
        action: Action that was executed (unused, kept for compatibility)

    Returns:
        Formatted string for Telegram
    """
    # Scripts output formatted text directly - just truncate for Telegram
    if len(output) > 4000:
        return output[:3950] + "\n\n... (gekürzt)"
    return output.strip()


def get_available_skills(settings: Settings) -> list:
    """Get list of available skill names from registry."""
    registry = get_registry(settings)
    return registry.get_skill_names()


def get_skill_actions(skill_name: str, settings: Settings) -> list:
    """Get available actions for a skill from registry."""
    registry = get_registry(settings)
    skill = registry.get_skill_by_name(skill_name)
    if skill:
        return [cmd.name for cmd in skill.commands]
    return []
