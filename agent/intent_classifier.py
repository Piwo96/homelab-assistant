"""Intent classification using LM Studio with dynamic tool-calling.

This module uses dynamic tool definitions from the skill registry.
Skills are automatically loaded from .claude/skills/ and converted
to tool definitions for function calling.
"""

import json
import logging
from typing import Any, Dict, List

import httpx

from .config import Settings
from .models import IntentResult
from .tool_registry import get_registry
from .wol import ensure_lm_studio_available, get_loaded_model

logger = logging.getLogger(__name__)

# Base system prompt - examples are added dynamically from skills
SYSTEM_PROMPT_BASE = """Du bist ein freundlicher Smart Home und Homelab Assistant.
Antworte auf Deutsch. Sei kurz und verständlich - keine technischen Begriffe.

## REGEL 1: Wann Tools benutzen
- Server, VMs, Container, Homelab → proxmox
- Kameras, Bewegung, Aufnahmen → unifi-protect
- DNS, Werbung, Pi-hole → pihole
- Lichter, Schalter, Smart Home → homeassistant
- Netzwerk, WLAN, Geräte → unifi-network

## REGEL 2: Wann KEIN Tool - einfach antworten!
Bei ALLEM was nicht mit Homelab/Smart Home zu tun hat, antworte einfach direkt:
- Grüße: "Hallo", "Hi", "Guten Morgen"
- Smalltalk: "Wie geht's?", "Was machst du?"
- Allgemeine Fragen: "Was ist X?", "Erkläre mir Y"
- Wissen: "Hauptstadt von...", "Wer hat...", "Wann war..."
- Bezug auf vorherige Nachrichten im Chat-Verlauf
- "Danke", "OK", "Verstehe"

Du bist ein normaler Chat-Assistent! Antworte freundlich und hilfreich auf ALLES.
Benutze Tools NUR wenn es EXPLIZIT um Homelab-Systeme geht.

## REGEL 3: IMMER eine action setzen!
Wenn du ein Tool benutzt, MUSST du IMMER eine action angeben.
NIEMALS ein Tool ohne action aufrufen!

## Beispiele mit action (PFLICHT!)

{skill_examples}

## Beispiele OHNE Tool
- "Hallo!" → "Hallo! Wie kann ich dir helfen?"
- "Danke!" → "Gerne!"
- "Was kannst du?" → "Ich kann dir bei deinem Homelab helfen: Server Status, Kameras, Smart Home, und mehr."

## Wichtig
- Erwähne NIEMALS: 'self-annealing', 'Skills', 'Features', 'Tool'
- Bei unklaren Anfragen: freundlich nachfragen
- args NUR wenn User explizit IDs/Namen nennt (z.B. "VM 100", "Licht Wohnzimmer")"""


# Cache for built system prompt
_cached_system_prompt: str | None = None


def build_system_prompt(registry) -> str:
    """Build system prompt with dynamic examples from loaded skills.

    Args:
        registry: The tool registry with loaded skills

    Returns:
        Complete system prompt with skill examples
    """
    global _cached_system_prompt

    # Return cached prompt if available
    if _cached_system_prompt is not None:
        return _cached_system_prompt

    example_sections = []

    for skill_name, skill in registry.skills.items():
        if not skill.examples:
            continue

        lines = [f"### {skill_name}"]
        for ex in skill.examples:
            if ex.args:
                # Format args as JSON-like string
                args_str = ", ".join(f"{k}: {v}" for k, v in ex.args.items())
                lines.append(f'- "{ex.phrase}" → action: {ex.action}, args: {{{args_str}}}')
            else:
                lines.append(f'- "{ex.phrase}" → action: {ex.action}')
        example_sections.append("\n".join(lines))

    skill_examples = "\n\n".join(example_sections) if example_sections else "# Keine Beispiele geladen"

    _cached_system_prompt = SYSTEM_PROMPT_BASE.format(skill_examples=skill_examples)
    logger.info(f"Built system prompt with {len(example_sections)} skill example sections")

    return _cached_system_prompt


def clear_prompt_cache():
    """Clear the cached system prompt (call after skill reload)."""
    global _cached_system_prompt
    _cached_system_prompt = None


async def classify_intent(
    message: str,
    settings: Settings,
    history: List[Dict[str, str]] | None = None,
) -> IntentResult:
    """Classify user message into structured intent using tool-calling.

    This function uses dynamic tool definitions loaded from the skill
    registry. New skills are automatically recognized without code changes.

    Args:
        message: User's natural language message
        settings: Application settings
        history: Optional conversation history for context

    Returns:
        IntentResult with classified skill, action, and parameters
    """
    # Ensure registry is initialized
    registry = get_registry(settings)

    if not registry._initialized:
        logger.error("Tool registry not initialized")
        return IntentResult(
            skill="error",
            action="not_initialized",
            description="Tool Registry nicht initialisiert. Bitte Agent neu starten.",
        )

    if not registry.skills:
        logger.warning("No skills loaded in registry")
        return IntentResult(
            skill="unknown",
            action="",
            description="Keine Skills geladen. Bitte Skills in .claude/skills/ prüfen.",
        )

    # Ensure LM Studio is available (wake Gaming PC if needed)
    if not await ensure_lm_studio_available(settings):
        logger.error("LM Studio not available after wake attempt")
        return IntentResult(
            skill="error",
            action="lm_studio_unavailable",
            description="LM Studio ist nicht erreichbar. Ist der Gaming-PC an?",
        )

    try:
        response = await _call_with_tools(
            message, settings, registry.get_tools_json(), history or [], registry
        )
        result = _parse_tool_call_response(response)

        logger.info(
            f"Tool classification: skill={result.skill}, action={result.action}, "
            f"target={result.target}, confidence={result.confidence}"
        )

        return result

    except httpx.TimeoutException:
        logger.error("LM Studio request timed out")
        return IntentResult(
            skill="error",
            action="timeout",
            description="LM Studio Timeout - Anfrage dauerte zu lange",
        )
    except httpx.HTTPStatusError as e:
        error_body = e.response.text[:500] if e.response.text else "no body"
        logger.error(f"LM Studio HTTP error: {e.response.status_code} - {error_body}")
        return IntentResult(
            skill="error",
            action="http_error",
            description=f"LM Studio Fehler: HTTP {e.response.status_code}",
        )
    except httpx.RequestError as e:
        logger.error(f"LM Studio request failed: {e}")
        return IntentResult(
            skill="error",
            action="connection_error",
            description=f"Verbindungsfehler zu LM Studio: {str(e)}",
        )
    except Exception as e:
        logger.error(f"Unexpected error in tool classification: {e}")
        return IntentResult(
            skill="error",
            action="internal_error",
            description=f"Interner Fehler: {str(e)}",
        )


async def _call_with_tools(
    message: str,
    settings: Settings,
    tools: List[Dict[str, Any]],
    history: List[Dict[str, str]],
    registry,
) -> Dict[str, Any]:
    """Call LM Studio with tool definitions.

    Args:
        message: User message
        settings: Application settings
        tools: Tool definitions in OpenAI format
        history: Conversation history for context
        registry: Tool registry for building system prompt

    Returns:
        Raw API response from LM Studio
    """
    # Note: /no_think flag only works for certain Qwen3 variants, not the thinking
    # model which has separate reasoning_content. Just use message directly.
    user_message = message

    # Build system prompt with dynamic examples from registry
    system_prompt = build_system_prompt(registry)

    messages = [
        {"role": "system", "content": system_prompt},
        *history,
        {"role": "user", "content": user_message},
    ]

    # Determine model to use: configured model or auto-detect from LM Studio
    model = settings.lm_studio_model
    if not model:
        model = await get_loaded_model(settings)

    payload = {
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",  # Let model decide
        "temperature": 0.1,  # Low temperature for consistent results
        "max_tokens": 1500,  # Thinking models need more tokens for reasoning + output
    }

    if model:
        payload["model"] = model

    logger.debug(f"LM Studio request - model: {model}, tools count: {len(tools)}")

    async with httpx.AsyncClient(timeout=settings.lm_studio_timeout) as client:
        response = await client.post(
            f"{settings.lm_studio_url}/v1/chat/completions",
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def _parse_tool_call_response(response: Dict[str, Any]) -> IntentResult:
    """Parse LM Studio response with potential tool calls.

    Args:
        response: Raw API response

    Returns:
        IntentResult with parsed skill/action or unknown
    """
    choices = response.get("choices", [])
    if not choices:
        return IntentResult(
            skill="error",
            action="no_response",
            description="Keine Antwort vom LLM",
        )

    message = choices[0].get("message", {})

    # Check if model made a tool call
    tool_calls = message.get("tool_calls", [])

    if tool_calls:
        # Model chose to use a tool
        tool_call = tool_calls[0]  # Take first tool call
        function = tool_call.get("function", {})

        tool_name = function.get("name", "")
        arguments_str = function.get("arguments", "{}")

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            arguments = {}

        action = arguments.get("action", "")

        # Validate: action is required for tool calls
        if not action:
            skill_name = tool_name.replace("_", "-")
            logger.warning(f"Tool call without action: {skill_name}, arguments: {arguments}")
            return IntentResult(
                skill="error",
                action="missing_action",
                description=f"Das habe ich nicht ganz verstanden. Was genau möchtest du mit {skill_name} machen?",
                confidence=0.3,
                raw_response=json.dumps(tool_call),
            )

        return IntentResult(
            skill=tool_name.replace("_", "-"),  # unifi_protect -> unifi-protect
            action=action,
            target=arguments.get("target"),
            args=arguments.get("args", {}),
            confidence=0.95,  # Tool call implies high confidence
            raw_response=json.dumps(tool_call),
        )
    else:
        # Model responded without tool (conversational response)
        content = message.get("content", "")
        # Strip thinking tags from thinking models (e.g., Qwen3)
        content = _strip_thinking_tags(content)
        return IntentResult(
            skill="unknown",
            action="",
            description=content,
            confidence=0.0,
            raw_response=content,
        )


def _strip_thinking_tags(text: str) -> str:
    """Remove <think>...</think> tags from thinking model output.

    Args:
        text: Raw model output that may contain thinking tags

    Returns:
        Text with thinking sections removed
    """
    import re

    # Remove <think>...</think> blocks (including multiline)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Also handle unclosed think tags (model cut off mid-thinking)
    text = re.sub(r"<think>.*$", "", text, flags=re.DOTALL)
    return text.strip()


def get_available_skills(settings: Settings) -> list:
    """Get list of available skill names from registry.

    Args:
        settings: Application settings

    Returns:
        List of skill names
    """
    registry = get_registry(settings)
    return registry.get_skill_names()
