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
from .error_approval import handle_error_fix_approval, is_error_request
from .tool_registry import get_registry, reload_registry_async
from .wol import wake_gaming_pc
from .chat_history import get_history, add_message, clear_history, save_conversation_to_db
from .response_formatter import format_response, should_format_response
from .conversational import (
    is_conversational_followup,
    handle_conversational_followup,
    get_pending_skill_request,
    is_skill_creation_confirmation,
)
from .skill_creator import request_skill_creation, handle_approval

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def periodic_git_pull(settings: Settings):
    """Background task that periodically pulls updates from git.

    Automatically restarts the server if Python files changed.
    """
    import os
    import sys

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

                    # Check if Python files changed (requires full restart)
                    if ".py" in output:
                        logger.info("Python files changed - restarting server...")
                        await asyncio.sleep(1)  # Brief delay for cleanup
                        os.execv(sys.executable, [sys.executable] + sys.argv)
                    else:
                        # Only non-Python files changed - reload skills with metadata generation
                        await reload_registry_async(settings)
                        logger.info("Skills reloaded after git pull (with metadata generation)")
            else:
                logger.warning(f"Git pull failed: {result.get('output')}")
        except Exception as e:
            logger.error(f"Error during periodic git pull: {e}")


async def periodic_nightly_review(_settings: Settings):
    """Background task that runs nightly conversation review.

    Runs once per day at ~3:00 AM (or 24h after startup).
    """
    from .nightly_review import run_review

    # Wait 24 hours between reviews (or run immediately if first time)
    interval = 24 * 60 * 60  # 24 hours in seconds

    # Check when last review was run
    try:
        stats = database.get_database_stats()
        if stats["total_reviews"] == 0:
            # First run - wait a bit to collect some data first
            logger.info("Nightly review: waiting 1 hour before first run")
            await asyncio.sleep(60 * 60)  # 1 hour
        else:
            # Wait until next scheduled time
            logger.info("Nightly review: scheduled to run every 24 hours")
            await asyncio.sleep(interval)
    except Exception:
        await asyncio.sleep(interval)

    while True:
        try:
            logger.info("Starting nightly conversation review...")
            result = await run_review(dry_run=False)
            logger.info(f"Nightly review completed: {result}")
        except Exception as e:
            logger.error(f"Error during nightly review: {e}")

        await asyncio.sleep(interval)


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

    # Cleanup old processed updates (keep last 7 days)
    cleaned = database.cleanup_old_updates(days=7)
    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} old processed update records")

    # Initialize tool registry
    logger.info("Loading skill registry...")
    registry = get_registry(settings)
    logger.info(
        f"Loaded {len(registry.skills)} skills: {', '.join(registry.get_skill_names())}"
    )

    # Start background tasks
    background_tasks = []

    # Background task for metadata generation (keywords/examples)
    async def generate_missing_metadata():
        """Generate missing keywords and examples for skills."""
        await asyncio.sleep(5)  # Wait for app to fully start
        try:
            skills_path = settings.project_root / ".claude" / "skills"
            await registry.ensure_skill_metadata_all(
                skills_path,
                settings.lm_studio_url,
                settings.lm_studio_model,
                settings=settings,
            )
        except Exception as e:
            logger.warning(f"Background metadata generation failed: {e}")

    # Check if any skills need metadata generation
    needs_generation = any(
        not skill.keywords or not skill.examples
        for skill in registry.skills.values()
    )
    if needs_generation:
        logger.info("Starting background metadata generation...")
        metadata_task = asyncio.create_task(generate_missing_metadata())
        background_tasks.append(metadata_task)

    if settings.git_pull_interval_minutes > 0:
        pull_task = asyncio.create_task(periodic_git_pull(settings))
        background_tasks.append(pull_task)

    # Start nightly review task
    # review_task = asyncio.create_task(periodic_nightly_review(settings))
    # background_tasks.append(review_task)
    # logger.info("Nightly review task started")

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
    """Reload all skills from disk (for development/hot-reload).

    Also generates missing keywords and examples for any new skills.
    """
    settings = get_settings()
    registry = await reload_registry_async(settings)

    # Count skills with examples/keywords
    skills_with_examples = sum(1 for s in registry.skills.values() if s.examples)
    skills_with_keywords = sum(1 for s in registry.skills.values() if s.keywords)

    return {
        "status": "reloaded",
        "skills": registry.get_skill_names(),
        "tool_count": len(registry.tools),
        "skills_with_examples": skills_with_examples,
        "skills_with_keywords": skills_with_keywords,
    }


@app.post("/generate-metadata")
async def generate_metadata():
    """Generate missing keywords and examples for all skills.

    This endpoint triggers async generation of keywords.json and examples.json
    for any skills that are missing them. Uses LM Studio for generation.
    """
    settings = get_settings()
    registry = await reload_registry_async(settings)

    # Count skills with examples/keywords
    skills_with_examples = sum(1 for s in registry.skills.values() if s.examples)
    skills_with_keywords = sum(1 for s in registry.skills.values() if s.keywords)

    return {
        "status": "generated",
        "skills": registry.get_skill_names(),
        "skills_with_examples": skills_with_examples,
        "skills_with_keywords": skills_with_keywords,
        "total_keywords": len(registry.homelab_keywords),
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

    # Deduplicate: Check if we already processed this update
    update_id = data.get("update_id")
    if update_id:
        if not database.mark_update_processed(update_id):
            # Already processed (e.g., during server restart)
            logger.info(f"Skipping duplicate update_id: {update_id}")
            return {"ok": True}

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
    # Send typing indicator - will be removed when final response is ready
    status_msg_id = await send_message(chat_id, "⏳ Bin dran...", settings)

    async def remove_status():
        """Remove status message before sending response."""
        nonlocal status_msg_id
        if status_msg_id:
            await delete_message(chat_id, status_msg_id, settings)
            status_msg_id = None

    # Check for skill creation confirmation FIRST
    # User might be responding "Ja" to a pending skill request
    pending_request, skill_to_extend = get_pending_skill_request(chat_id)
    if pending_request and is_skill_creation_confirmation(text):
        logger.info(f"User confirmed skill creation for: {pending_request[:50]}...")
        # Clear the pending marker by adding a new message
        add_message(chat_id, "system", "SKILL_REQUEST_CONFIRMED")

        # Trigger skill creation workflow
        response = await request_skill_creation(
            user_request=pending_request,
            requester_name=user.display_name,
            requester_id=user.id,
            chat_id=chat_id,
            settings=settings,
            skill_to_extend=skill_to_extend,
        )
        await remove_status()
        await send_message(chat_id, response, settings)
        add_message(chat_id, "user", text)
        add_message(chat_id, "assistant", response)
        return

    # Check for conversational follow-ups BEFORE classification
    # These are messages like "verstehe ich nicht" that reference previous context
    if is_conversational_followup(text, chat_id):
        response = await handle_conversational_followup(text, chat_id, settings)
        if response:
            await remove_status()
            await send_message(chat_id, response, settings)
            add_message(chat_id, "user", text)
            add_message(chat_id, "assistant", response)
            save_conversation_to_db(
                chat_id=chat_id,
                user_message=text,
                assistant_response=response,
                user_id=user.id,
                intent_skill="conversational",
                intent_confidence=1.0,
            )
            return

    # Get conversation history for context
    history = get_history(chat_id)

    # Classify intent with history context
    intent = await classify_intent(text, settings, history)
    logger.info(f"Classified intent: skill={intent.skill}, action={intent.action}")

    # Handle errors
    if intent.skill == "error":
        error_msg = intent.description or intent.action or "Unbekannter Fehler"
        await remove_status()
        await send_message(chat_id, f"❌ {error_msg}", settings)
        return

    # Handle unknown intents - general conversation or missing functionality
    if intent.skill == "unknown":
        registry = get_registry(settings)

        # If LLM gave a meaningful conversational response, use it
        # This handles cases like "Na wie läufts?" where keywords might match
        # but the LLM correctly recognized it as smalltalk
        has_llm_response = intent.description and len(intent.description) > 10

        # Only check for homelab request if LLM didn't give a good response
        # This prevents offering skill creation for conversational messages
        is_homelab_request = not has_llm_response and registry.is_homelab_related(text)

        # Homelab-related but no skill? Offer to extend or create!
        if is_homelab_request:
            # Check if there's a matching skill we could extend
            matching_skill = registry.find_matching_skill(text)

            # Offer to learn this capability
            fallback_response = (
                "🤔 Das kann ich leider noch nicht.\n\n"
                "Soll ich das lernen? Antworte mit **Ja** wenn du möchtest."
            )
            # Store the pending request in chat history for context
            add_message(chat_id, "user", text)
            add_message(chat_id, "assistant", fallback_response)
            # Store matching skill info for skill_creator
            if matching_skill:
                add_message(chat_id, "system", f"PENDING_SKILL_REQUEST:{text}|EXTEND:{matching_skill}")
            else:
                add_message(chat_id, "system", f"PENDING_SKILL_REQUEST:{text}")

            await remove_status()
            await send_message(chat_id, fallback_response, settings)
            save_conversation_to_db(
                chat_id=chat_id,
                user_message=text,
                assistant_response=fallback_response,
                user_id=user.id,
                intent_skill="unknown",
                intent_confidence=0.0,
                success=False,
                error_message="No skill for homelab request",
            )
            return

        # Not homelab-related - use LLM response if available (general chat)
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

            response_text = intent.description
            if is_bad_response:
                logger.warning(f"Filtered bad LLM response: {intent.description[:100]}...")
                response_text = "Das kann ich leider nicht beantworten. Kann ich dir bei etwas anderem helfen?"

            await remove_status()
            await send_message(chat_id, response_text, settings)
            add_message(chat_id, "user", text)
            add_message(chat_id, "assistant", response_text)
            save_conversation_to_db(
                chat_id=chat_id,
                user_message=text,
                assistant_response=response_text,
                user_id=user.id,
                intent_skill="conversational",
                intent_confidence=intent.confidence,
                success=not is_bad_response,
                error_message="Bad response filtered" if is_bad_response else None,
            )
            return

        # General fallback for non-homelab questions without LLM response
        fallback_response = "Hmm, da bin ich mir nicht sicher. Kannst du das anders formulieren?"
        add_message(chat_id, "user", text)
        add_message(chat_id, "assistant", fallback_response)

        await remove_status()
        await send_message(chat_id, fallback_response, settings)
        save_conversation_to_db(
            chat_id=chat_id,
            user_message=text,
            assistant_response=fallback_response,
            user_id=user.id,
            intent_skill="unknown",
            intent_confidence=0.0,
            success=False,
            error_message="No LLM response",
        )
        return

    # Execute known skill (with user_id for permission checks)
    result = await execute_skill(intent, settings, user_id=user.id)

    # Determine response message
    if result.success:
        # Format response based on original question
        if await should_format_response(text, result.output, intent.skill):
            response_msg = await format_response(
                text, result.output, settings, intent.skill, intent.action
            )
        else:
            response_msg = result.output
        await remove_status()
        await send_message(chat_id, response_msg, settings)
    else:
        # Show technical details to admin, friendly message to regular users
        if user.id == settings.admin_telegram_id:
            response_msg = f"❌ {result.error}"
        else:
            response_msg = f"Ups, da ist etwas schief gelaufen. 🙈 {settings.admin_name} wird informiert!"
        await remove_status()
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
