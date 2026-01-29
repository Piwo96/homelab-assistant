"""Skill loader - parses SKILL.md files and extracts command definitions."""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class SkillCommand:
    """A single command within a skill."""

    name: str  # e.g., "turn-on"
    description: str  # e.g., "Turn on entity"
    parameters: List[dict] = field(default_factory=list)  # argparse arguments
    script_path: Optional[Path] = None  # Path to script containing this command


@dataclass
class SkillDefinition:
    """Complete skill definition from SKILL.md + script."""

    name: str
    description: str
    version: str
    triggers: List[str]
    script_path: Optional[Path]
    commands: List[SkillCommand] = field(default_factory=list)
    intent_hints: List[str] = field(default_factory=list)
    is_documentation_only: bool = False


def parse_skill_md(skill_path: Path) -> Optional[SkillDefinition]:
    """Parse SKILL.md frontmatter and metadata.

    Args:
        skill_path: Directory containing SKILL.md

    Returns:
        SkillDefinition or None if parsing fails
    """
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        logger.debug(f"No SKILL.md found in {skill_path}")
        return None

    try:
        content = skill_md.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read {skill_md}: {e}")
        return None

    # Extract YAML frontmatter (between --- markers)
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        logger.warning(f"No YAML frontmatter in {skill_md}")
        return None

    try:
        frontmatter = yaml.safe_load(match.group(1))
    except yaml.YAMLError as e:
        logger.warning(f"Invalid YAML in {skill_md}: {e}")
        return None

    if not frontmatter or not isinstance(frontmatter, dict):
        logger.warning(f"Empty or invalid frontmatter in {skill_md}")
        return None

    # Find scripts in scripts/ directory
    scripts_dir = skill_path / "scripts"
    script = None  # Primary script for backward compatibility
    all_scripts = []  # All *_api.py scripts for command extraction
    if scripts_dir.exists():
        # Prefer script named after the skill (e.g., homeassistant_api.py for homeassistant)
        skill_name = frontmatter.get("name", skill_path.name)
        preferred_script = scripts_dir / f"{skill_name.replace('-', '_')}_api.py"

        if preferred_script.exists():
            script = preferred_script
        else:
            # Fallback: first *_api.py file found
            scripts = list(scripts_dir.glob("*_api.py"))
            if scripts:
                script = scripts[0]

        # Collect ALL *_api.py scripts for command extraction
        all_scripts = list(scripts_dir.glob("*_api.py"))

    skill = SkillDefinition(
        name=frontmatter.get("name", skill_path.name),
        description=frontmatter.get("description", ""),
        version=frontmatter.get("version", "1.0.0"),
        triggers=frontmatter.get("triggers", []),
        script_path=script,
        intent_hints=frontmatter.get("intent_hints", []),
        is_documentation_only=(script is None),
    )

    # Extract commands from ALL scripts if available
    if all_scripts:
        all_commands = []
        for script_file in all_scripts:
            commands = extract_commands_from_script(script_file)
            all_commands.extend(commands)
        skill.commands = all_commands
        if len(all_scripts) > 1:
            logger.info(f"Extracted {len(all_commands)} commands from {len(all_scripts)} scripts in {skill.name}")
    elif script:
        # Fallback for backward compatibility
        skill.commands = extract_commands_from_script(script)

    return skill


def extract_commands_from_script(script_path: Path) -> List[SkillCommand]:
    """Extract argparse subcommands and their parameters from a Python script.

    Uses regex to find add_parser() calls with their help text, and
    add_argument() calls to extract parameter definitions per command.

    Args:
        script_path: Path to the Python script

    Returns:
        List of SkillCommand objects with parameters populated
    """
    if not script_path or not script_path.exists():
        return []

    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read script {script_path}: {e}")
        return []

    commands = []

    # Step 0: Detect lambda aliases for add_parser
    # e.g., _p = lambda *a, **kw: subparsers.add_parser(*a, ...)
    alias_pattern = r'(\w+)\s*=\s*lambda\s.*?\.add_parser\('
    parser_aliases = set()
    for m in re.finditer(alias_pattern, content):
        parser_aliases.add(m.group(1))
    if parser_aliases:
        logger.debug(f"Found add_parser aliases: {parser_aliases}")

    # Step 1: Find add_parser calls WITH variable assignment
    # e.g., events = subparsers.add_parser("events", help="List events")
    # Also matches alias calls: events = _p("events", help="List events")
    assigned_pattern = (
        r'(\w+)\s*=\s*\w+\.add_parser\(\s*'
        r'["\']([^"\']+)["\'].*?help\s*=\s*["\']([^"\']+)["\']'
    )
    assigned_vars = {}
    for m in re.finditer(assigned_pattern, content):
        var_name, cmd_name, help_text = m.group(1), m.group(2), m.group(3)
        assigned_vars[var_name] = (cmd_name, help_text)

    # Also find assigned alias calls: events = _p("events", help="...")
    for alias in parser_aliases:
        alias_assigned_pattern = (
            rf'(\w+)\s*=\s*{re.escape(alias)}\(\s*'
            rf'["\']([^"\']+)["\'].*?help\s*=\s*["\']([^"\']+)["\']'
        )
        for m in re.finditer(alias_assigned_pattern, content):
            var_name, cmd_name, help_text = m.group(1), m.group(2), m.group(3)
            if var_name != alias:  # Don't match the alias definition itself
                assigned_vars[var_name] = (cmd_name, help_text)

    # Step 2: For assigned parsers, extract their add_argument() calls
    for var_name, (cmd_name, help_text) in assigned_vars.items():
        # Handle nested parens in help text like: help="Last N hours (e.g., 24h)"
        # [^()]* stops at both ( and ), so nested groups are handled explicitly.
        # re.DOTALL handles multi-line add_argument calls.
        arg_pattern = rf'{re.escape(var_name)}\.add_argument\(([^()]*(?:\([^()]*\)[^()]*)*)\)'
        parameters = []
        for m in re.finditer(arg_pattern, content, re.DOTALL):
            param = _parse_add_argument(m.group(1))
            if param:
                parameters.append(param)

        commands.append(
            SkillCommand(
                name=cmd_name,
                description=help_text,
                parameters=parameters,
                script_path=script_path,
            )
        )

    # Step 3: Find standalone add_parser calls (no variable, no arguments)
    # e.g., subparsers.add_parser("cameras", help="List all cameras")
    all_pattern = r'add_parser\(\s*["\']([^"\']+)["\'].*?help\s*=\s*["\']([^"\']+)["\']'
    for m in re.finditer(all_pattern, content):
        cmd_name, help_text = m.group(1), m.group(2)
        if not any(c.name == cmd_name for c in commands):
            commands.append(
                SkillCommand(
                    name=cmd_name,
                    description=help_text,
                    parameters=[],
                    script_path=script_path,
                )
            )

    # Also find standalone alias calls: _p("cameras", help="...")
    for alias in parser_aliases:
        alias_standalone_pattern = (
            rf'{re.escape(alias)}\(\s*'
            rf'["\']([^"\']+)["\'].*?help\s*=\s*["\']([^"\']+)["\']'
        )
        for m in re.finditer(alias_standalone_pattern, content):
            cmd_name, help_text = m.group(1), m.group(2)
            if not any(c.name == cmd_name for c in commands):
                commands.append(
                    SkillCommand(
                        name=cmd_name,
                        description=help_text,
                        parameters=[],
                        script_path=script_path,
                    )
                )

    logger.debug(f"Extracted {len(commands)} commands from {script_path.name}")
    return commands


def _parse_add_argument(arg_text: str) -> Optional[dict]:
    """Parse an add_argument() call text into a parameter dict.

    Args:
        arg_text: The text inside add_argument(...) parentheses

    Returns:
        Dict with name, required, help keys, or None if unparseable
    """
    # Extract parameter name (first quoted string)
    name_match = re.search(r'["\'](-{0,2})([^"\']+)["\']', arg_text)
    if not name_match:
        return None

    prefix = name_match.group(1)
    name = name_match.group(2)

    # Skip short aliases like -o
    if prefix == "-" and len(name) == 1:
        return None

    # Extract help text
    help_match = re.search(r'help\s*=\s*["\']([^"\']+)["\']', arg_text)
    help_text = help_match.group(1) if help_match else ""

    return {
        "name": name.lstrip("-"),
        "required": prefix == "",  # No dash prefix = positional = required
        "help": help_text,
    }


def load_all_skills(skills_path: Path) -> List[SkillDefinition]:
    """Load all skills from a directory.

    Args:
        skills_path: Directory containing skill subdirectories

    Returns:
        List of SkillDefinition objects (only executable skills)
    """
    if not skills_path.exists():
        logger.warning(f"Skills path does not exist: {skills_path}")
        return []

    skills = []
    for skill_dir in sorted(skills_path.iterdir()):
        if not skill_dir.is_dir():
            continue

        # Skip hidden directories and common non-skill dirs
        if skill_dir.name.startswith(".") or skill_dir.name in ("__pycache__",):
            continue

        skill = parse_skill_md(skill_dir)
        if skill:
            if skill.is_documentation_only:
                logger.debug(f"Skipping documentation-only skill: {skill.name}")
            else:
                skills.append(skill)
                logger.info(
                    f"Loaded skill: {skill.name} ({len(skill.commands)} commands)"
                )

    return skills


def get_skill_path(skill_name: str, skills_path: Path) -> Optional[Path]:
    """Get the path to a skill directory.

    Args:
        skill_name: Name of the skill
        skills_path: Base skills directory

    Returns:
        Path to skill directory or None if not found
    """
    skill_dir = skills_path / skill_name
    if skill_dir.exists() and skill_dir.is_dir():
        return skill_dir
    return None
