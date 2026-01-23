"""Skill execution - maps intents to skill script calls using dynamic registry."""

import asyncio
import json
import logging
import subprocess
from pathlib import Path
from typing import List

from .config import Settings
from .models import IntentResult, SkillExecutionResult
from .skill_loader import SkillDefinition
from .tool_registry import get_registry

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

    # Action is the subcommand
    if intent.action:
        cmd.append(intent.action)

    # Target as positional argument (if present)
    if intent.target:
        cmd.append(intent.target)

    # Additional args as flags
    for key, value in intent.args.items():
        if key in ("action", "target"):  # Skip already handled
            continue
        cmd.append(f"--{key}")
        cmd.append(str(value))

    # Always add --json for structured output
    cmd.append("--json")

    return cmd


async def execute_skill(intent: IntentResult, settings: Settings) -> SkillExecutionResult:
    """Execute a skill based on classified intent.

    Args:
        intent: Parsed intent from LM Studio
        settings: Application settings

    Returns:
        SkillExecutionResult with success status and output
    """
    skill_name = intent.skill

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
            return SkillExecutionResult(
                success=False,
                output="",
                error=result.stderr or f"Script fehlgeschlagen (Exit Code: {result.returncode})",
                skill=skill_name,
                action=intent.action,
            )

    except subprocess.TimeoutExpired:
        return SkillExecutionResult(
            success=False,
            output="",
            error="Timeout: Script brauchte zu lange (>30s)",
            skill=skill_name,
            action=intent.action,
        )
    except Exception as e:
        return SkillExecutionResult(
            success=False,
            output="",
            error=f"Ausführungsfehler: {str(e)}",
            skill=skill_name,
            action=intent.action,
        )


def format_skill_output(output: str, skill: str, action: str) -> str:
    """Format skill output for Telegram display.

    Args:
        output: Raw JSON output from skill script
        skill: Skill name
        action: Action that was executed

    Returns:
        Formatted string for Telegram
    """
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        # If not JSON, return as-is
        return output[:2000]  # Telegram message limit

    # Format based on skill and action
    try:
        if skill == "homeassistant":
            return format_homeassistant_output(data, action)
        elif skill == "proxmox":
            return format_proxmox_output(data, action)
        elif skill == "unifi-network":
            return format_unifi_network_output(data, action)
        elif skill == "unifi-protect":
            return format_unifi_protect_output(data, action)
        elif skill == "pihole":
            return format_pihole_output(data, action)
    except (KeyError, TypeError, AttributeError) as e:
        logger.warning(f"Error formatting {skill} output: {e}")

    # Default: pretty print JSON (truncated)
    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


def format_homeassistant_output(data: dict, action: str) -> str:
    """Format Home Assistant output."""
    if action in ["turn_on", "turn-on", "turn_off", "turn-off", "toggle"]:
        entity = data.get("entity_id", "Unbekannt")
        state = data.get("state", "unbekannt")
        return f"✅ {entity}: {state}"

    if action == "status":
        return f"🏠 Home Assistant: {data.get('state', 'unknown')}"

    if action in ["entities", "list_scenes", "list-scenes"]:
        if isinstance(data, list):
            items = [f"• {item.get('entity_id', item)}" for item in data[:20]]
            result = "\n".join(items)
            if len(data) > 20:
                result += f"\n... und {len(data) - 20} weitere"
            return result

    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


def format_proxmox_output(data: dict, action: str) -> str:
    """Format Proxmox output."""
    if action in ["start", "stop"]:
        return f"✅ Aktion ausgeführt"

    if action == "overview" and isinstance(data, list):
        lines = []
        for node in data:
            name = node.get("node", "?")
            status = node.get("status", "?")
            cpu = node.get("cpu", 0) * 100
            mem_used = node.get("mem", 0) / (1024**3)
            mem_total = node.get("maxmem", 1) / (1024**3)
            lines.append(
                f"🖥️ {name}: {status} | CPU: {cpu:.1f}% | RAM: {mem_used:.1f}/{mem_total:.1f}GB"
            )
        return "\n".join(lines)

    if action in ["vms", "containers"] and isinstance(data, list):
        lines = []
        for vm in data[:15]:
            vmid = vm.get("vmid", "?")
            name = vm.get("name", "?")
            status = vm.get("status", "?")
            emoji = "🟢" if status == "running" else "⚪"
            lines.append(f"{emoji} {vmid}: {name} ({status})")
        if len(data) > 15:
            lines.append(f"... und {len(data) - 15} weitere")
        return "\n".join(lines) or "Keine VMs/Container gefunden"

    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


def format_unifi_network_output(data: dict, action: str) -> str:
    """Format UniFi Network output."""
    if action == "clients" and isinstance(data, list):
        lines = []
        for client in data[:20]:
            name = client.get("name") or client.get("hostname") or client.get("mac", "?")
            ip = client.get("ip", "?")
            lines.append(f"📱 {name}: {ip}")
        if len(data) > 20:
            lines.append(f"... und {len(data) - 20} weitere")
        return "\n".join(lines) or "Keine Clients gefunden"

    if action == "health":
        return f"✅ Netzwerk-Status: OK"

    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


def format_unifi_protect_output(data: dict, action: str) -> str:
    """Format UniFi Protect output."""
    if action == "cameras" and isinstance(data, list):
        lines = []
        for cam in data:
            name = cam.get("name", "?")
            state = cam.get("state", "?")
            emoji = "🟢" if state == "CONNECTED" else "🔴"
            lines.append(f"{emoji} {name}")
        return "\n".join(lines) or "Keine Kameras gefunden"

    if action in ["events", "detections"] and isinstance(data, list):
        if not data:
            return "Keine Ereignisse gefunden"
        lines = []
        for event in data[:10]:
            event_type = event.get("type", "?")
            camera = event.get("camera", {}).get("name", "?")
            lines.append(f"📹 {camera}: {event_type}")
        if len(data) > 10:
            lines.append(f"... und {len(data) - 10} weitere")
        return "\n".join(lines)

    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


def format_pihole_output(data: dict, action: str) -> str:
    """Format Pi-hole output."""
    if action == "summary":
        total = data.get("dns_queries_today", 0)
        blocked = data.get("ads_blocked_today", 0)
        percent = data.get("ads_percentage_today", 0)
        return f"🛡️ Pi-hole\nAnfragen heute: {total}\nBlockiert: {blocked} ({percent:.1f}%)"

    if action == "status":
        status = data.get("status", "unknown")
        emoji = "🟢" if status == "enabled" else "🔴"
        return f"{emoji} Pi-hole: {status}"

    if action in ["enable", "disable"]:
        return f"✅ Pi-hole {action}d"

    return json.dumps(data, indent=2, ensure_ascii=False)[:2000]


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
