"""FastAPI application for Telegram webhook."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, HTTPException

from .config import get_settings, Settings
from . import self_annealing
from . import database
from .telegram_handler import (
    verify_webhook_signature,
    send_message,
    delete_message,
    answer_callback_query,
    parse_telegram_user,
    HELP_TEXT,
)
from .intent_classifier import classify_intent
from .skill_executor import execute_skill
from .skill_creator import request_skill_creation, handle_approval
from .error_approval import handle_error_fix_approval, is_error_request
from .tool_registry import get_registry, reload_registry
from .wol import wake_gaming_pc
from .chat_history import get_history, add_message, clear_history, save_conversation_to_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def periodic_git_pull(settings: Settings):
    """Background task that periodically pulls updates from git."""
    interval = settings.git_pull_interval_minutes * 60
    logger.info(f"Starting periodic git pull (every {settings.git_pull_interval_minutes} min)")

    while True:
        await asyncio.sleep(interval)
        try:
            result = await self_annealing.git_pull(settings)
            if result.get("success"):
                output = result.get("output", "")
                if "Already up to date" not in output:
                    logger.info(f"Git pull: {output}")
                    # Reload skills if new code was pulled
                    reload_registry(settings)
                    logger.info("Skills reloaded after git pull")
            else:
                logger.warning(f"Git pull failed: {result.get('output')}")
        except Exception as e:
            logger.error(f"Error during periodic git pull: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    settings = get_settings()
    logger.info("Starting Telegram Homelab Agent...")
    logger.info(f"Allowed users: {settings.telegram_allowed_users}")
    logger.info(f"Admin ID: {settings.admin_telegram_id}")

    # Initialize database
    logger.info("Initializing database...")
    database.init_database(settings.project_root)
    stats = database.get_database_stats()
    logger.info(f"Database: {stats['total_conversations']} conversations, {stats['flagged_conversations']} flagged")

    # Initialize tool registry
    logger.info("Loading skill registry...")
    registry = get_registry(settings)
    logger.info(
        f"Loaded {len(registry.skills)} skills: {', '.join(registry.get_skill_names())}"
    )

    # Start background tasks
    background_tasks = []
    if settings.git_pull_interval_minutes > 0:
        pull_task = asyncio.create_task(periodic_git_pull(settings))
        background_tasks.append(pull_task)

    yield

    # Cancel background tasks
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    logger.info("Shutting down...")


app = FastAPI(
    title="Homelab Telegram Agent",
    description="Smart Home and Homelab control via Telegram",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "1.0.0"}


@app.post("/reload-skills")
async def reload_skills():
    """Reload all skills from disk (for development/hot-reload)."""
    settings = get_settings()
    registry = reload_registry(settings)
    return {
        "status": "reloaded",
        "skills": registry.get_skill_names(),
        "tool_count": len(registry.tools),
    }


@app.post("/webhook")
async def webhook(request: Request):
    """Handle incoming Telegram webhook updates."""
    settings = get_settings()

    # Verify webhook signature
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not verify_webhook_signature(secret_header, settings.telegram_webhook_secret):
        logger.warning("Invalid webhook signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Route to appropriate handler
    if "callback_query" in data:
        await handle_callback_update(data["callback_query"], settings)
    elif "message" in data:
        await handle_message_update(data["message"], settings)

    return {"ok": True}


async def handle_message_update(message: Dict[str, Any], settings: Settings):
    """Handle incoming message from Telegram."""
    user_data = message.get("from", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()
    user_id = user_data.get("id")

    if not chat_id or not text:
        return

    user = parse_telegram_user(user_data)
    # Only log first 30 chars to avoid logging sensitive data
    safe_preview = text[:30] + "..." if len(text) > 30 else text
    logger.info(f"Message from {user.display_name} ({user_id}): {safe_preview}")

    # Check allowlist
    if user_id not in settings.telegram_allowed_users:
        logger.warning(f"Unauthorized user: {user_id}")
        await send_message(chat_id, "⛔ Du bist nicht autorisiert.", settings)
        return

    # Handle commands
    if text.startswith("/"):
        await handle_command(text, chat_id, user, settings)
        return

    # Process natural language
    await process_natural_language(text, chat_id, user, settings)


async def handle_command(
    text: str, chat_id: int, user, settings: Settings
):
    """Handle slash commands."""
    command = text.split()[0].lower()

    if command == "/start" or command == "/help":
        await send_message(chat_id, HELP_TEXT, settings)

    elif command == "/skills":
        registry = get_registry(settings)
        skills_list = []
        for name, skill in registry.skills.items():
            cmd_count = len(skill.commands)
            skills_list.append(f"• **{name}** ({cmd_count} commands)")
        skills_text = "\n".join(skills_list) if skills_list else "Keine Skills geladen"
        await send_message(
            chat_id,
            f"🛠️ **Geladene Skills:**\n\n{skills_text}",
            settings,
        )

    elif command == "/wake":
        await send_message(chat_id, "🖥️ Gaming-PC wird geweckt...", settings)
        success = await wake_gaming_pc(settings)
        if success:
            await send_message(
                chat_id,
                "✅ Wake-on-LAN Paket gesendet. Der PC sollte in ~1 Minute bereit sein.",
                settings,
            )
        else:
            await send_message(
                chat_id,
                "❌ Fehler: Keine MAC-Adresse konfiguriert.",
                settings,
            )

    elif command == "/clear":
        cleared = clear_history(chat_id)
        if cleared:
            await send_message(chat_id, "🗑️ Chat-Verlauf gelöscht.", settings)
        else:
            await send_message(chat_id, "ℹ️ Kein Verlauf vorhanden.", settings)

    else:
        await send_message(
            chat_id,
            f"❓ Unbekannter Befehl: {command}\n\nTippe /help für Hilfe.",
            settings,
        )


async def process_natural_language(
    text: str, chat_id: int, user, settings: Settings
):
    """Process natural language input through intent classification."""
    # Send typing indicator
    status_msg_id = await send_message(chat_id, "⏳ Bin dran...", settings)

    # Get conversation history for context
    history = get_history(chat_id)

    # Classify intent with history context
    intent = await classify_intent(text, settings, history)

    # Remove typing indicator
    if status_msg_id:
        await delete_message(chat_id, status_msg_id, settings)
    logger.info(f"Classified intent: skill={intent.skill}, action={intent.action}")

    # Handle errors
    if intent.skill == "error":
        error_msg = intent.description or intent.action or "Unbekannter Fehler"
        await send_message(chat_id, f"❌ {error_msg}", settings)
        return

    # Handle unknown intents - either conversational or skill creation request
    if intent.skill == "unknown":
        # If model gave a text response, check if it's a good response
        if intent.description and len(intent.description) > 10:
            # Filter out bad responses that mention internal concepts
            bad_keywords = [
                "self-annealing", "self_annealing", "selbstverbesserung",
                "skill updates", "skill-updates", "neue features",
                "fehlerbehebung", "github sync", "error tracking",
                "können wir automatisch", "durch die selbstverbesserung",
            ]
            response_lower = intent.description.lower()
            is_bad_response = any(kw in response_lower for kw in bad_keywords)

            if not is_bad_response:
                await send_message(chat_id, intent.description, settings)
                add_message(chat_id, "user", text)
                add_message(chat_id, "assistant", intent.description)
                save_conversation_to_db(
                    chat_id=chat_id,
                    user_message=text,
                    assistant_response=intent.description,
                    user_id=user.id,
                    intent_skill="unknown",
                    intent_confidence=intent.confidence,
                )
                return

            # Bad response detected - give a helpful fallback
            logger.warning(f"Filtered bad LLM response: {intent.description[:100]}...")
            fallback_response = (
                "🤔 Das habe ich nicht ganz verstanden.\n\n"
                "Ich kann dir helfen bei:\n"
                "• **Server/VMs**: \"Welche Server laufen?\"\n"
                "• **Kameras**: \"Zeige Kameras\"\n"
                "• **Smart Home**: \"Mach Licht an\"\n"
                "• **Pi-hole**: \"DNS Status\"\n\n"
                "Was möchtest du wissen?"
            )
            await send_message(chat_id, fallback_response, settings)
            add_message(chat_id, "user", text)
            add_message(chat_id, "assistant", fallback_response)
            # Save bad response for analysis (original response, not fallback)
            save_conversation_to_db(
                chat_id=chat_id,
                user_message=text,
                assistant_response=intent.description,  # Original bad response
                user_id=user.id,
                intent_skill="unknown",
                intent_confidence=intent.confidence,
                success=False,
                error_message="Bad response filtered",
            )
            return

        # Otherwise, request skill creation for missing capability
        response = await request_skill_creation(
            user_request=text,
            requester_name=user.display_name,
            requester_id=user.id,
            chat_id=chat_id,
            settings=settings,
        )
        await send_message(chat_id, response, settings)
        return

    # Execute known skill (with user_id for permission checks)
    result = await execute_skill(intent, settings, user_id=user.id)

    # Determine response message
    if result.success:
        response_msg = result.output
        await send_message(chat_id, response_msg, settings)
    else:
        response_msg = f"❌ {result.error}"
        await send_message(chat_id, response_msg, settings)

    # Store conversation in history
    add_message(chat_id, "user", text)
    add_message(chat_id, "assistant", response_msg)

    # Save to database for analysis
    save_conversation_to_db(
        chat_id=chat_id,
        user_message=text,
        assistant_response=response_msg,
        user_id=user.id,
        intent_skill=intent.skill,
        intent_action=intent.action,
        intent_target=intent.target,
        intent_confidence=intent.confidence,
        success=result.success,
        error_message=result.error if not result.success else None,
    )


async def handle_callback_update(callback_query: Dict[str, Any], settings: Settings):
    """Handle inline keyboard button press."""
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    user_id = callback_query.get("from", {}).get("id")

    logger.info(f"Callback from {user_id}: {data}")

    # Only admin can approve/reject
    if user_id != settings.admin_telegram_id:
        await answer_callback_query(callback_id, "⛔ Nur Admin", settings)
        return

    # Parse callback data
    if ":" not in data:
        await answer_callback_query(callback_id, "❌ Ungültige Daten", settings)
        return

    action, request_id = data.split(":", 1)
    approved = action == "approve"

    # Route to appropriate handler based on request type
    if is_error_request(request_id):
        result = await handle_error_fix_approval(request_id, approved, settings)
    else:
        result = await handle_approval(request_id, approved, settings)

    # Send feedback
    feedback = "✅ Genehmigt" if approved else "❌ Abgelehnt"
    await answer_callback_query(callback_id, feedback, settings)

    logger.info(f"Approval result for {request_id}: {result}")
