"""Skill execution - maps intents to skill script calls using dynamic imports."""

import asyncio
import inspect
import json
import logging
from typing import Optional

from .config import Settings
from .models import IntentResult, SkillExecutionResult, is_admin_required
from .skill_loader import SkillCommand
from .skill_importer import get_execute_fn, load_skill_module
from .tool_registry import get_registry
from .error_approval import request_error_fix_approval

logger = logging.getLogger(__name__)


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

    # Validate action exists and find the command
    action_normalized = intent.action.replace("_", "-")
    matching_command: Optional[SkillCommand] = None

    for cmd_def in skill.commands:
        if cmd_def.name == action_normalized:
            matching_command = cmd_def
            break

    valid_actions = [cmd_def.name for cmd_def in skill.commands]
    if valid_actions and not matching_command:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Unbekannte Aktion '{intent.action}' für {skill_name}. Verfügbar: {', '.join(valid_actions)}",
            skill=skill_name,
            action=intent.action,
        )

    # Determine which script to use
    script_to_use = matching_command.script_path if matching_command else skill.script_path
    logger.debug(f"Using script {script_to_use} for action {action_normalized}")

    # Try direct Python import
    execute_fn = get_execute_fn(script_to_use)

    if execute_fn:
        return await _execute_direct(execute_fn, intent, skill_name, action_normalized, settings, script_to_use)

    return SkillExecutionResult(
        success=False,
        output="",
        error=f"Kein execute() in {script_to_use}",
        skill=skill_name,
        action=intent.action,
    )


async def _execute_direct(
    execute_fn,
    intent: IntentResult,
    skill_name: str,
    action: str,
    settings: Settings,
    script_path=None,
) -> SkillExecutionResult:
    """Execute skill via direct Python import.

    Handles both sync and async execute() functions.
    Sync functions run in a thread pool to avoid blocking the event loop.
    If the skill module provides format_output(action, data), it is used
    to produce human-readable text instead of raw JSON.
    """
    try:
        if inspect.iscoroutinefunction(execute_fn):
            # Async function (e.g. dashboard_api) - await directly with timeout
            result = await asyncio.wait_for(
                execute_fn(action, intent.args),
                timeout=30.0,
            )
        else:
            # Sync function - run in thread pool with timeout
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: execute_fn(action, intent.args)
                ),
                timeout=30.0,
            )

        # Try skill-level format_output() for human-readable text
        output = _try_format_output(script_path, action, result)

        if output is None:
            # Fallback: serialize to JSON for response_formatter
            if isinstance(result, (dict, list)):
                output = json.dumps(result, indent=2, default=str)
            elif isinstance(result, bytes):
                output = f"Binary data ({len(result)} bytes)"
            elif result is not None:
                output = str(result)
            else:
                output = ""

        # Pre-truncate to ~2 chars/token of context to leave room for prompt
        max_output = settings.lm_studio_context_size * 2
        return SkillExecutionResult(
            success=True,
            output=format_skill_output(output, max_chars=max_output),
            skill=skill_name,
            action=intent.action,
        )

    except asyncio.TimeoutError:
        asyncio.create_task(
            request_error_fix_approval(
                error_type="TimeoutExpired",
                error_message="Script timeout after 30s",
                skill=skill_name,
                action=intent.action,
                context=f"Direct call: {action}({intent.args})",
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
    except (ValueError, KeyError) as e:
        asyncio.create_task(
            request_error_fix_approval(
                error_type=type(e).__name__,
                error_message=str(e),
                skill=skill_name,
                action=intent.action,
                context=f"Direct call: {action}({intent.args})",
                settings=settings,
            )
        )
        return SkillExecutionResult(
            success=False,
            output="",
            error=str(e),
            skill=skill_name,
            action=intent.action,
        )
    except Exception as e:
        asyncio.create_task(
            request_error_fix_approval(
                error_type=type(e).__name__,
                error_message=str(e),
                skill=skill_name,
                action=intent.action,
                context=f"Direct call: {action}({intent.args})",
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


def _try_format_output(script_path, action: str, data) -> str | None:
    """Try to use the skill's format_agent_output() for human-readable text.

    Skills can export format_agent_output(action, data) -> str|None to
    provide compact, human-readable output instead of raw JSON. This
    prevents large JSON payloads from overwhelming the LLM formatter.

    Returns formatted string, or None if no formatter available.
    """
    if script_path is None:
        return None
    try:
        module = load_skill_module(script_path)
        if module and hasattr(module, "format_agent_output"):
            formatted = module.format_agent_output(action, data)
            if formatted is not None:
                logger.info(f"Used skill format_agent_output() for {action}")
                return formatted
    except Exception as e:
        logger.debug(f"format_agent_output() failed for {action}: {e}")
    return None


def format_skill_output(output: str, max_chars: int = 100000) -> str:
    """Truncate very large outputs for LLM context limits.

    Args:
        output: Raw output string
        max_chars: Maximum allowed characters (derived from context size)
    """
    if len(output) > max_chars:
        return output[:max_chars - 50] + "\n\n... (gekürzt)"
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
