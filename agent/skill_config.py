"""Central configuration for skill paths and validation.

This is the SINGLE SOURCE OF TRUTH for all skill-related paths.
All other modules should import from here.
"""

from pathlib import Path
from typing import Optional


# Base path relative to project root
SKILLS_BASE_PATH = ".claude/skills"

# Known skills and their script filenames
# Key: skill name, Value: script filename (without path)
SKILL_SCRIPTS = {
    "proxmox": "proxmox_api.py",
    "homeassistant": "homeassistant_api.py",
    "pihole": "pihole_api.py",
    "unifi-network": "network_api.py",
    "unifi-protect": "protect_api.py",
}


def get_skills_base_path(project_root: Path) -> Path:
    """Get the absolute path to the skills directory.

    Args:
        project_root: Project root directory

    Returns:
        Absolute path to skills directory
    """
    return project_root / SKILLS_BASE_PATH


def get_skill_path(skill_name: str, project_root: Optional[Path] = None) -> str:
    """Get the relative path to a skill's script.

    Args:
        skill_name: Name of the skill
        project_root: Optional project root for absolute path

    Returns:
        Relative path to the skill script (e.g., ".claude/skills/proxmox/scripts/proxmox_api.py")
    """
    script_name = SKILL_SCRIPTS.get(skill_name)
    if not script_name:
        # Default naming convention
        script_name = f"{skill_name.replace('-', '_')}_api.py"

    rel_path = f"{SKILLS_BASE_PATH}/{skill_name}/scripts/{script_name}"

    if project_root:
        return str(project_root / rel_path)
    return rel_path


def get_skill_dir(skill_name: str) -> str:
    """Get the relative directory path for a skill.

    Args:
        skill_name: Name of the skill

    Returns:
        Relative path to skill directory (e.g., ".claude/skills/proxmox/")
    """
    return f"{SKILLS_BASE_PATH}/{skill_name}/"


def is_valid_skill_path(path: str) -> bool:
    """Check if a path is a valid skill path.

    Args:
        path: Path to check

    Returns:
        True if path is within the skills directory
    """
    valid_prefixes = [SKILLS_BASE_PATH, f"./{SKILLS_BASE_PATH}"]
    return any(path.startswith(prefix) for prefix in valid_prefixes)


def is_valid_agent_path(path: str) -> bool:
    """Check if a path is a valid agent code path.

    Args:
        path: Path to check

    Returns:
        True if path is within the agent directory
    """
    return path.startswith("agent/") or path.startswith("./agent/")


def validate_file_path(path: str) -> tuple[bool, str]:
    """Validate a file path for skill/agent operations.

    Args:
        path: Path to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if is_valid_skill_path(path):
        return True, ""
    if is_valid_agent_path(path):
        return True, ""

    return False, f"Invalid path: {path} - Must be in {SKILLS_BASE_PATH}/ or agent/"


def verify_skill_paths(project_root: Path) -> dict:
    """Verify all skill scripts exist.

    Args:
        project_root: Project root directory

    Returns:
        Dict with verification results
    """
    results = {"valid": [], "missing": [], "all_valid": True}

    for skill_name in SKILL_SCRIPTS.keys():
        full_path = project_root / get_skill_path(skill_name)
        if full_path.exists():
            results["valid"].append(skill_name)
        else:
            results["missing"].append({
                "skill": skill_name,
                "expected_path": get_skill_path(skill_name),
            })
            results["all_valid"] = False

    return results


def get_all_skill_names() -> list[str]:
    """Get list of all known skill names.

    Returns:
        List of skill names
    """
    return list(SKILL_SCRIPTS.keys())
