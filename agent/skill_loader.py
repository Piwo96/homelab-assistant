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


@dataclass
class SkillExample:
    """An example phrase that maps to a skill action."""

    phrase: str  # e.g., "Mach Licht an"
    action: str  # e.g., "turn-on"
    args: Optional[dict] = None  # e.g., {"entity_id": "light.wohnzimmer"}


@dataclass
class SkillDefinition:
    """Complete skill definition from SKILL.md + script."""

    name: str
    description: str
    version: str
    triggers: List[str]
    script_path: Optional[Path]
    commands: List[SkillCommand] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)  # Auto-extracted keywords
    examples: List[SkillExample] = field(default_factory=list)  # Example phrases
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

    # Load keywords from keywords.json if exists
    keywords = _load_keywords_from_file(skill_path)
    # Also include tags from frontmatter as keywords
    tags = frontmatter.get("tags", [])
    if tags:
        keywords.extend([t.lower() for t in tags])

    # Load examples from examples.json if exists
    examples = _load_examples_from_file(skill_path)

    skill = SkillDefinition(
        name=frontmatter.get("name", skill_path.name),
        description=frontmatter.get("description", ""),
        version=frontmatter.get("version", "1.0.0"),
        triggers=frontmatter.get("triggers", []),
        script_path=script,
        keywords=list(set(keywords)),  # Deduplicate
        examples=examples,
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


def _load_keywords_from_file(skill_path: Path) -> List[str]:
    """Load keywords from keywords.json if it exists.

    Args:
        skill_path: Path to skill directory

    Returns:
        List of keywords or empty list
    """
    import json

    keywords_file = skill_path / "keywords.json"
    if keywords_file.exists():
        try:
            with open(keywords_file) as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [k.lower() for k in data]
                elif isinstance(data, dict) and "keywords" in data:
                    return [k.lower() for k in data["keywords"]]
        except Exception as e:
            logger.warning(f"Failed to load keywords from {keywords_file}: {e}")

    return []


def _load_examples_from_file(skill_path: Path) -> List["SkillExample"]:
    """Load examples from examples.json if it exists.

    Args:
        skill_path: Path to skill directory

    Returns:
        List of SkillExample objects or empty list
    """
    import json

    examples_file = skill_path / "examples.json"
    if examples_file.exists():
        try:
            with open(examples_file) as f:
                data = json.load(f)
                examples_data = data.get("examples", []) if isinstance(data, dict) else data
                return [
                    SkillExample(
                        phrase=ex.get("phrase", ""),
                        action=ex.get("action", ""),
                        args=ex.get("args"),
                    )
                    for ex in examples_data
                    if ex.get("phrase") and ex.get("action")
                ]
        except Exception as e:
            logger.warning(f"Failed to load examples from {examples_file}: {e}")

    return []


def extract_commands_from_script(script_path: Path) -> List[SkillCommand]:
    """Extract argparse subcommands from a Python script.

    Uses regex to find add_parser() calls and their help text.

    Args:
        script_path: Path to the Python script

    Returns:
        List of SkillCommand objects
    """
    if not script_path or not script_path.exists():
        return []

    try:
        content = script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read script {script_path}: {e}")
        return []

    commands = []

    # Pattern for: subparsers.add_parser("command", help="description")
    # Also matches: add_parser("command", help="description")
    pattern = r'add_parser\(\s*["\']([^"\']+)["\'].*?help\s*=\s*["\']([^"\']+)["\']'
    matches = re.findall(pattern, content, re.DOTALL)

    for cmd_name, help_text in matches:
        commands.append(
            SkillCommand(
                name=cmd_name,
                description=help_text,
                parameters=[],  # Could be extended to parse add_argument calls
            )
        )

    logger.debug(f"Extracted {len(commands)} commands from {script_path.name}")
    return commands


async def ensure_skill_metadata(
    skill: "SkillDefinition",
    skill_path: Path,
    lm_studio_url: str,
    lm_studio_model: str,
) -> "SkillDefinition":
    """Ensure skill has keywords and examples, generating if missing.

    This function checks if a skill has keywords and examples loaded.
    If either is missing, it will generate them using LM Studio.

    Args:
        skill: The skill definition to check/update
        skill_path: Path to skill directory
        lm_studio_url: LM Studio API URL
        lm_studio_model: Model name to use

    Returns:
        Updated SkillDefinition with keywords/examples
    """
    from .keyword_extractor import ensure_keywords
    from .example_generator import ensure_examples

    # Ensure keywords exist
    if not skill.keywords:
        logger.info(f"Generating keywords for {skill.name}...")
        keywords = await ensure_keywords(skill_path, lm_studio_url, lm_studio_model)
        skill.keywords = list(set(keywords))

    # Ensure examples exist
    if not skill.examples:
        logger.info(f"Generating examples for {skill.name}...")
        commands = [{"name": c.name, "description": c.description} for c in skill.commands]
        examples_data = await ensure_examples(
            skill_path, lm_studio_url, lm_studio_model, commands
        )
        skill.examples = [
            SkillExample(
                phrase=ex["phrase"],
                action=ex["action"],
                args=ex.get("args"),
            )
            for ex in examples_data
        ]

    return skill


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
