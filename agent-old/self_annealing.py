"""Self-Annealing integration for the agent.

Provides programmatic access to the self-annealing skill for:
- Automatic commits after skill creation
- Error logging during skill execution
- Pattern learning from resolved errors
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .config import Settings

logger = logging.getLogger(__name__)

# Path to self-annealing scripts
SCRIPTS_PATH = Path(__file__).parent.parent / ".claude" / "skills" / "self-annealing" / "scripts"


def _run_script(script: str, *args, settings: Settings = None) -> tuple[bool, str]:
    """Run a self-annealing script.

    Args:
        script: Script name (git_api.py or annealing_api.py)
        *args: Arguments to pass to the script
        settings: Application settings

    Returns:
        Tuple of (success, output)
    """
    script_path = SCRIPTS_PATH / script

    if not script_path.exists():
        logger.error(f"Self-annealing script not found: {script_path}")
        return False, f"Script nicht gefunden: {script}"

    cmd = ["python", str(script_path)] + list(args)
    cwd = settings.project_root if settings else Path(__file__).parent.parent

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(cwd),
        )

        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip() or f"Exit code: {result.returncode}"

    except subprocess.TimeoutExpired:
        return False, "Timeout nach 60s"
    except Exception as e:
        return False, str(e)


async def _run_script_async(script: str, *args, settings: Settings = None) -> tuple[bool, str]:
    """Run a self-annealing script asynchronously.

    Args:
        script: Script name
        *args: Arguments to pass
        settings: Application settings

    Returns:
        Tuple of (success, output)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: _run_script(script, *args, settings=settings)
    )


# --- Git Operations ---

async def git_status(settings: Settings = None) -> dict:
    """Get git repository status.

    Returns:
        Dict with status info or error
    """
    success, output = await _run_script_async("git_api.py", "status", settings=settings)
    return {"success": success, "output": output}


async def git_pull(settings: Settings = None) -> dict:
    """Pull latest changes from remote.

    Returns:
        Dict with success status and output
    """
    success, output = await _run_script_async("git_api.py", "pull", settings=settings)

    if success:
        logger.info(f"Git pull: {output}")
    else:
        logger.warning(f"Git pull failed: {output}")

    return {"success": success, "output": output}


async def commit_and_push(message: str, settings: Settings = None) -> dict:
    """Commit all changes and push to remote.

    Args:
        message: Commit message (should follow Conventional Commits)
        settings: Application settings

    Returns:
        Dict with success status and output
    """
    success, output = await _run_script_async(
        "annealing_api.py", "anneal", message,
        settings=settings
    )

    if success:
        logger.info(f"Self-annealing: {output}")
    else:
        logger.error(f"Self-annealing failed: {output}")

    return {"success": success, "output": output}


# --- Error Tracking ---

async def log_error(error: str, context: str, settings: Settings = None) -> dict:
    """Log an error for tracking.

    Args:
        error: Error type/name
        context: Context/description
        settings: Application settings

    Returns:
        Dict with error ID and status
    """
    success, output = await _run_script_async(
        "annealing_api.py", "log-error", error, context,
        settings=settings
    )

    if success:
        # Parse error ID from output
        # Format: "Logged: err_20240115_001"
        error_id = None
        for line in output.split("\n"):
            if line.startswith("Logged:"):
                error_id = line.split(":")[1].strip()
                break
        return {"success": True, "error_id": error_id, "output": output}

    return {"success": False, "output": output}


async def log_resolution(error_id: str, resolution: str, settings: Settings = None) -> dict:
    """Log how an error was resolved.

    Args:
        error_id: Error ID from log_error
        resolution: How it was fixed
        settings: Application settings

    Returns:
        Dict with status
    """
    success, output = await _run_script_async(
        "annealing_api.py", "log-resolution", error_id, resolution,
        settings=settings
    )
    return {"success": success, "output": output}


# --- Skill Management ---

async def update_skill(skill_name: str, content: str, section: str = "edge_cases", settings: Settings = None) -> dict:
    """Update a skill with new content.

    Args:
        skill_name: Name of the skill to update
        content: Content to add
        section: Section to update (default: edge_cases)
        settings: Application settings

    Returns:
        Dict with status
    """
    success, output = await _run_script_async(
        "annealing_api.py", "update-skill", skill_name, content,
        "--section", section,
        settings=settings
    )
    return {"success": success, "output": output}


async def create_skill(name: str, description: str, settings: Settings = None) -> dict:
    """Create a new skill.

    Args:
        name: Skill name
        description: Skill description
        settings: Application settings

    Returns:
        Dict with status and path
    """
    success, output = await _run_script_async(
        "annealing_api.py", "create-skill", name, description,
        settings=settings
    )
    return {"success": success, "output": output}


# --- Full Annealing Cycle ---

async def full_cycle(
    error: str,
    context: str,
    resolution: str,
    skill_name: Optional[str] = None,
    commit_message: Optional[str] = None,
    settings: Settings = None,
) -> dict:
    """Run complete self-annealing cycle.

    1. Log error
    2. Log resolution
    3. Update skill (if specified)
    4. Commit and push

    Args:
        error: Error type/name
        context: Error context
        resolution: How it was fixed
        skill_name: Optional skill to update
        commit_message: Optional custom commit message
        settings: Application settings

    Returns:
        Dict with status and details
    """
    args = ["full-cycle", error, context, resolution]

    if skill_name:
        args.extend(["--skill", skill_name])

    if commit_message:
        args.extend(["--message", commit_message])

    success, output = await _run_script_async(
        "annealing_api.py", *args,
        settings=settings
    )

    return {"success": success, "output": output}


# --- Convenience Functions ---

async def anneal_after_skill_creation(skill_name: str, settings: Settings = None) -> dict:
    """Called after a skill is created/updated to commit and push.

    Args:
        skill_name: Name of the created/updated skill
        settings: Application settings

    Returns:
        Dict with status
    """
    message = f"feat({skill_name}): auto-created skill via agent"
    return await commit_and_push(message, settings=settings)


async def anneal_after_skill_update(skill_name: str, change_description: str, settings: Settings = None) -> dict:
    """Called after a skill is updated to commit and push.

    Args:
        skill_name: Name of the updated skill
        change_description: Brief description of changes
        settings: Application settings

    Returns:
        Dict with status
    """
    # Sanitize description for commit message
    desc = change_description.lower().replace(" ", "-")[:50]
    message = f"docs({skill_name}): {desc}"
    return await commit_and_push(message, settings=settings)


async def anneal_after_error_fix(
    error: str,
    resolution: str,
    skill_name: Optional[str] = None,
    settings: Settings = None,
) -> dict:
    """Called after fixing an error to log and commit.

    Args:
        error: Error that was fixed
        resolution: How it was fixed
        skill_name: Optional skill that was affected
        settings: Application settings

    Returns:
        Dict with status
    """
    # Generate commit message
    scope = skill_name or "agent"
    desc = error.lower().replace(" ", "-")[:40]
    message = f"fix({scope}): {desc}"

    return await full_cycle(
        error=error,
        context=f"Auto-logged by agent",
        resolution=resolution,
        skill_name=skill_name,
        commit_message=message,
        settings=settings,
    )
