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

# System prompt for tool-calling mode
SYSTEM_PROMPT = """Du bist ein freundlicher Smart Home und Homelab Assistant.
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

### proxmox
- "Welche Server laufen?" → action: overview
- "Homelab Status" → action: overview
- "Zeige VMs" → action: vms
- "Container Status" → action: containers
- "Wie geht es den Servern?" → action: nodes
- "Starte VM 100" → action: start, args: {vmid: 100}
- "Stoppe Container 101" → action: stop, args: {vmid: 101}

### unifi-protect
- "Zeige Kameras" → action: cameras
- "Kamera Status" → action: cameras
- "Gab es Bewegung?" → action: events
- "Was war los heute?" → action: events

### pihole
- "Pi-hole Status" → action: status
- "Ist Pi-hole aktiv?" → action: status
- "Wie viel geblockt?" → action: summary
- "DNS Statistiken" → action: summary
- "Blockiere example.com" → action: block, args: {domain: "example.com"}

### homeassistant
- "Mach Licht an" → action: turn-on, args: {entity_id: light.wohnzimmer}
- "Lichter aus" → action: turn-off
- "Welche Geräte gibt es?" → action: entities

### unifi-network
- "Welche Geräte sind online?" → action: clients
- "Netzwerk Status" → action: health
- "WLAN Geräte" → action: clients
- "Firewall Regeln" → action: firewall-rules
- "Port Forwarding" → action: port-forwards

## Beispiele OHNE Tool
- "Hallo!" → "Hallo! Wie kann ich dir helfen?"
- "Danke!" → "Gerne!"
- "Was kannst du?" → "Ich kann dir bei deinem Homelab helfen: Server Status, Kameras, Smart Home, und mehr."

## Wichtig
- Erwähne NIEMALS: 'self-annealing', 'Skills', 'Features', 'Tool'
- Bei unklaren Anfragen: freundlich nachfragen
- args NUR wenn User explizit IDs/Namen nennt (z.B. "VM 100", "Licht Wohnzimmer")"""


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
            message, settings, registry.get_tools_json(), history or []
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
        logger.error(f"LM Studio HTTP error: {e.response.status_code}")
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
) -> Dict[str, Any]:
    """Call LM Studio with tool definitions.

    Args:
        message: User message
        settings: Application settings
        tools: Tool definitions in OpenAI format
        history: Conversation history for context

    Returns:
        Raw API response from LM Studio
    """
    # Note: /no_think flag only works for certain Qwen3 variants, not the thinking
    # model which has separate reasoning_content. Just use message directly.
    user_message = message

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
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

        return IntentResult(
            skill=tool_name.replace("_", "-"),  # unifi_protect -> unifi-protect
            action=arguments.get("action", ""),
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
