"""Tool registry - manages dynamic tool definitions from skills."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from .skill_loader import SkillDefinition, load_all_skills

logger = logging.getLogger(__name__)


def skill_to_tool(skill: SkillDefinition) -> Dict[str, Any]:
    """Convert a SkillDefinition to OpenAI-compatible tool schema.

    Args:
        skill: The skill definition to convert

    Returns:
        Tool definition dict in OpenAI format
    """
    # Extract action names from commands
    action_enum = [cmd.name for cmd in skill.commands] if skill.commands else []

    # Build action descriptions
    action_descriptions = []
    for cmd in skill.commands:
        action_descriptions.append(f"- {cmd.name}: {cmd.description}")

    action_help = "\n".join(action_descriptions) if action_descriptions else ""

    return {
        "type": "function",
        "function": {
            "name": skill.name.replace("-", "_"),  # unifi-protect -> unifi_protect
            "description": skill.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": f"Die auszuführende Aktion.\n{action_help}",
                        "enum": action_enum if action_enum else None,
                    },
                    "args": {
                        "type": "object",
                        "description": "Argumente für die Aktion (z.B. vmid, entity_id, name)",
                        "additionalProperties": True,
                    },
                },
                "required": ["action"],
            },
        },
    }


@dataclass
class ToolRegistry:
    """Central registry for all available tools/skills."""

    skills: Dict[str, SkillDefinition] = field(default_factory=dict)
    tools: List[Dict[str, Any]] = field(default_factory=list)
    _initialized: bool = False

    def load_skills(self, skills_path: Path) -> None:
        """Load all skills from directory and generate tool definitions.

        Args:
            skills_path: Directory containing skill subdirectories
        """
        loaded_skills = load_all_skills(skills_path)

        for skill in loaded_skills:
            self.skills[skill.name] = skill

        # Generate tool definitions
        self.tools = [skill_to_tool(s) for s in self.skills.values()]
        self._initialized = True

        logger.info(
            f"Registry initialized: {len(self.skills)} skills, "
            f"{len(self.tools)} tools"
        )

    def get_skill_by_name(self, name: str) -> Optional[SkillDefinition]:
        """Find skill by name (handles both - and _ variants).

        Args:
            name: Skill name (can use - or _)

        Returns:
            SkillDefinition or None
        """
        # Normalize: try both variants
        normalized_dash = name.replace("_", "-")
        normalized_underscore = name.replace("-", "_")

        return (
            self.skills.get(name)
            or self.skills.get(normalized_dash)
            or self.skills.get(normalized_underscore)
        )

    def get_tools_json(self) -> List[Dict[str, Any]]:
        """Get tool definitions for LLM API.

        Returns:
            List of tool definitions in OpenAI format
        """
        return self.tools

    def get_skill_names(self) -> List[str]:
        """Get list of all skill names.

        Returns:
            List of skill names
        """
        return list(self.skills.keys())



# Singleton instance
_registry: Optional[ToolRegistry] = None


def get_registry(settings=None) -> ToolRegistry:
    """Get or create the tool registry singleton.

    Args:
        settings: Optional settings object with project_root

    Returns:
        ToolRegistry instance
    """
    global _registry

    if _registry is None:
        _registry = ToolRegistry()
        if settings:
            skills_path = settings.project_root / ".claude" / "skills"
            _registry.load_skills(skills_path)

    return _registry


def reload_registry(settings) -> ToolRegistry:
    """Force reload of the registry.

    Args:
        settings: Settings object with project_root

    Returns:
        Fresh ToolRegistry instance
    """
    global _registry

    _registry = ToolRegistry()
    skills_path = settings.project_root / ".claude" / "skills"
    _registry.load_skills(skills_path)

    return _registry
