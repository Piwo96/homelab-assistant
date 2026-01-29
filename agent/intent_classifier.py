"""Intent classification using LM Studio with dynamic tool-calling.

This module uses dynamic tool definitions from the skill registry.
Skills are automatically loaded from .claude/skills/ and converted
to tool definitions for function calling.
"""

import json
import logging
import re
from typing import Any, Dict, List

import httpx

from .config import Settings
from .models import IntentResult
from .tool_registry import get_registry
from .wol import ensure_lm_studio_available, get_loaded_model

logger = logging.getLogger(__name__)

# System prompt - the model decides via tool definitions whether to call tools.
# No hardcoded examples needed; the tool schemas provide action enums and descriptions.
SYSTEM_PROMPT = """Du bist ein freundlicher Smart Home und Homelab Assistant - wie ein technikbegeisterter Kumpel.
Antworte auf Deutsch, locker und natürlich. Kurze Sätze. Keine Emojis.

## KRITISCH: Du hast KEIN eigenes Wissen über das Homelab!
Du weißt NICHTS über Geräte, Kameras, Server, Netzwerk, DNS oder Smart Home Zustände.
Wenn der User nach solchen Infos fragt, MUSST du ein Tool benutzen.
ERFINDE NIEMALS Daten! Keine Geräteanzahl, keine Status, keine Namen ausdenken!

## Wann KEIN Tool benutzen
- Grüße: "Hallo", "Hi", "Moin", "Hey"
- Smalltalk: "Wie geht's?", "Na wie läufts?", "Alles klar?", "Was geht?"
- Bestätigungen: "OK", "Danke", "Super", "Ja", "Nein"
- Fragen über dich: "Was kannst du?", "Wer bist du?"
- Allgemeinwissen: "Was ist X?", "Hauptstadt von...", "Wer hat..."
- Verabschiedungen: "Tschüss", "Bye"

"Na wie läufts?" ist Smalltalk, KEIN Homelab-Befehl!

### So antwortest du bei Smalltalk (OHNE Tool):
- "Hallo!" → "Hey! Was kann ich für dich tun?"
- "Wie geht's dir?" → "Mir geht's gut, danke! Was steht an?"
- "Was geht?" → "Alles ruhig hier. Was brauchst du?"
- "Na wie läufts?" → "Läuft! Was kann ich für dich tun?"
- "Danke!" → "Klar, gerne!"
- "Was kannst du?" → "Ich steuere dein Smart Home und Homelab. Kameras, Server, Lichter, Netzwerk - frag einfach!"
- "Tschüss" → "Bis dann!"

## Wann Tool benutzen
Bei JEDER Frage über das Homelab, Smart Home oder Netzwerk. Beispiele:
- "Haben wir Geräte im LAN?" → unifi_network (clients)
- "Welche Kameras haben wir?" → unifi_protect (cameras)
- "Läuft die VM?" → proxmox (vms)
- "Licht an im Wohnzimmer" → homeassistant (turn-on)
- "Wie viele Werbungen geblockt?" → pihole (stats)
- "Gibt es kabelgebundene Geräte?" → unifi_network (clients)
- "Was war letztens vor der Tür?" → unifi_protect (events)
- "Wie ist der Server-Status?" → proxmox (node-status)

Im Zweifel: IMMER Tool benutzen statt selbst antworten!

## Regeln
- IMMER eine action angeben wenn du ein Tool benutzt
- args NUR wenn User explizit IDs/Namen nennt (z.B. "VM 100", "Licht Wohnzimmer")
- Erwähne NIEMALS: 'self-annealing', 'Skills', 'Features', 'Tool', 'API'"""


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
    user_message = message

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]

    # Determine model to use: configured model or auto-detect from LM Studio
    model = settings.lm_studio_model
    logger.info(f"Configured lm_studio_model: '{model}' (empty={not model})")
    if not model:
        model = await get_loaded_model(settings)
        logger.info(f"Auto-detected model from LM Studio: '{model}'")

    # Always let the model decide whether to use tools.
    # The system prompt already instructs when NOT to call tools (greetings, smalltalk, etc.)
    # This replaces the previous keyword-gate which was too brittle for natural language.
    tool_choice = "auto"
    logger.info(f"Using tool_choice: {tool_choice} (model decides)")

    # Token limits for retry: start low, increase on context errors
    token_limits = [2048, 4096, 8192]

    for attempt, max_tokens in enumerate(token_limits):
        payload = {
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }

        if model:
            payload["model"] = model

        logger.info(f"LM Studio request - model: {model}, tools: {len(tools)}, tool_choice: {tool_choice}, max_tokens: {max_tokens}")

        async with httpx.AsyncClient(timeout=settings.lm_studio_timeout) as client:
            response = await client.post(
                f"{settings.lm_studio_url}/v1/chat/completions",
                json=payload,
            )

            if response.status_code == 200:
                return response.json()

            # Check for context/token errors that might benefit from retry
            body = response.text[:500] if response.text else ""
            is_context_error = (
                response.status_code == 400
                and any(kw in body.lower() for kw in ["context", "token", "length", "exceed"])
            )

            if is_context_error and attempt < len(token_limits) - 1:
                logger.warning(f"Context error with max_tokens={max_tokens}, retrying with {token_limits[attempt + 1]}")
                continue

            # Not a retryable error, raise
            response.raise_for_status()

    # Should not reach here, but just in case
    raise httpx.HTTPStatusError("Max retries exceeded", request=None, response=response)


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
        content = _strip_thinking_tags(message.get("content", ""))
        logger.info(f"Model did not use tool. Response preview: {content[:200]}...")
        return IntentResult(
            skill="unknown",
            action="",
            description=content,
            confidence=0.0,
            raw_response=content,
        )


def _strip_thinking_tags(text: str) -> str:
    """Strip <think>...</think> tags from model output.

    Some reasoning models (e.g. Qwen3, DeepSeek) wrap internal chain-of-thought
    in <think> tags. This is a no-op for non-thinking models.
    """
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def get_available_skills(settings: Settings) -> list:
    """Get list of available skill names from registry.

    Args:
        settings: Application settings

    Returns:
        List of skill names
    """
    registry = get_registry(settings)
    return registry.get_skill_names()
