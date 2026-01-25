"""SQLite database for conversation storage and analysis.

Stores all conversations for later analysis and self-improvement.
Designed for easy migration to PostgreSQL later.
"""

import sqlite3
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# Database path (relative to project root)
_db_path: Optional[Path] = None
_initialized: bool = False


def init_database(project_root: Path) -> None:
    """Initialize database connection and create tables.

    Args:
        project_root: Project root directory
    """
    global _db_path, _initialized

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)

    _db_path = data_dir / "conversations.db"
    _initialized = True

    # Create tables
    with get_connection() as conn:
        conn.executescript("""
            -- All conversations
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_message TEXT NOT NULL,
                assistant_response TEXT,
                intent_skill TEXT,
                intent_action TEXT,
                intent_target TEXT,
                intent_confidence REAL,
                success BOOLEAN DEFAULT TRUE,
                error_message TEXT,
                flagged BOOLEAN DEFAULT FALSE,
                reviewed BOOLEAN DEFAULT FALSE
            );

            -- Index for efficient queries
            CREATE INDEX IF NOT EXISTS idx_conversations_chat_id
                ON conversations(chat_id);
            CREATE INDEX IF NOT EXISTS idx_conversations_timestamp
                ON conversations(timestamp);
            CREATE INDEX IF NOT EXISTS idx_conversations_flagged
                ON conversations(flagged);
            CREATE INDEX IF NOT EXISTS idx_conversations_skill
                ON conversations(intent_skill);

            -- Nightly review results
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                conversations_analyzed INTEGER,
                issues_found INTEGER,
                findings TEXT,
                improvements TEXT,
                commit_hash TEXT
            );

            -- Learned examples (extracted from good conversations)
            CREATE TABLE IF NOT EXISTS learned_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                user_message TEXT NOT NULL,
                expected_skill TEXT NOT NULL,
                expected_action TEXT NOT NULL,
                expected_target TEXT,
                source_conversation_id INTEGER,
                active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY (source_conversation_id) REFERENCES conversations(id)
            );
        """)
        conn.commit()

    logger.info(f"Database initialized at {_db_path}")


@contextmanager
def get_connection():
    """Get database connection context manager.

    Yields:
        sqlite3.Connection with row factory
    """
    if not _initialized or not _db_path:
        raise RuntimeError("Database not initialized. Call init_database first.")

    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def save_conversation(
    chat_id: int,
    user_message: str,
    assistant_response: str,
    user_id: Optional[int] = None,
    intent_skill: Optional[str] = None,
    intent_action: Optional[str] = None,
    intent_target: Optional[str] = None,
    intent_confidence: Optional[float] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> int:
    """Save a conversation to the database.

    Args:
        chat_id: Telegram chat ID
        user_message: User's message
        assistant_response: Bot's response
        user_id: Telegram user ID
        intent_skill: Detected skill name
        intent_action: Detected action
        intent_target: Detected target
        intent_confidence: Classification confidence
        success: Whether the response was successful
        error_message: Error message if failed

    Returns:
        ID of inserted conversation
    """
    # Auto-flag conversations that might need review
    flagged = _should_flag(intent_skill, assistant_response, success)

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO conversations (
                chat_id, user_id, user_message, assistant_response,
                intent_skill, intent_action, intent_target, intent_confidence,
                success, error_message, flagged
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            chat_id, user_id, user_message, assistant_response,
            intent_skill, intent_action, intent_target, intent_confidence,
            success, error_message, flagged
        ))
        conn.commit()
        return cursor.lastrowid


def _should_flag(
    intent_skill: Optional[str],
    response: str,
    success: bool
) -> bool:
    """Determine if a conversation should be flagged for review.

    Args:
        intent_skill: Detected skill
        response: Assistant response
        success: Whether it succeeded

    Returns:
        True if should be flagged
    """
    # Flag unknown intents
    if intent_skill == "unknown":
        return True

    # Flag errors
    if not success:
        return True

    # Flag responses with bad patterns
    bad_patterns = [
        "self-annealing", "skill updates", "neue features",
        "nicht verstanden", "weiß nicht",
    ]
    response_lower = response.lower()
    if any(p in response_lower for p in bad_patterns):
        return True

    return False


def get_recent_conversations(
    chat_id: int,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Get recent conversations for a chat.

    Args:
        chat_id: Telegram chat ID
        limit: Maximum number of conversations

    Returns:
        List of conversation dicts
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT user_message, assistant_response
            FROM conversations
            WHERE chat_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (chat_id, limit)).fetchall()

    # Return in chronological order (oldest first)
    return [dict(row) for row in reversed(rows)]


def get_flagged_conversations(
    limit: int = 100,
    reviewed: bool = False
) -> List[Dict[str, Any]]:
    """Get flagged conversations for review.

    Args:
        limit: Maximum number of conversations
        reviewed: Include already reviewed

    Returns:
        List of conversation dicts
    """
    with get_connection() as conn:
        if reviewed:
            rows = conn.execute("""
                SELECT * FROM conversations
                WHERE flagged = TRUE
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM conversations
                WHERE flagged = TRUE AND reviewed = FALSE
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()

    return [dict(row) for row in rows]


def get_unknown_intent_patterns(limit: int = 50) -> List[Dict[str, Any]]:
    """Get conversations where intent was unknown.

    Args:
        limit: Maximum number of results

    Returns:
        List of user messages that weren't understood
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT user_message, COUNT(*) as count
            FROM conversations
            WHERE intent_skill = 'unknown' OR intent_skill IS NULL
            GROUP BY user_message
            ORDER BY count DESC
            LIMIT ?
        """, (limit,)).fetchall()

    return [dict(row) for row in rows]


def get_skill_usage_stats() -> Dict[str, int]:
    """Get usage statistics per skill.

    Returns:
        Dict of skill name -> usage count
    """
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT intent_skill, COUNT(*) as count
            FROM conversations
            WHERE intent_skill IS NOT NULL
            GROUP BY intent_skill
            ORDER BY count DESC
        """).fetchall()

    return {row["intent_skill"]: row["count"] for row in rows}


def mark_reviewed(conversation_ids: List[int]) -> None:
    """Mark conversations as reviewed.

    Args:
        conversation_ids: List of conversation IDs
    """
    with get_connection() as conn:
        conn.executemany(
            "UPDATE conversations SET reviewed = TRUE WHERE id = ?",
            [(id,) for id in conversation_ids]
        )
        conn.commit()


def save_review(
    conversations_analyzed: int,
    issues_found: int,
    findings: Dict[str, Any],
    improvements: Dict[str, Any],
    commit_hash: Optional[str] = None
) -> int:
    """Save a review result.

    Args:
        conversations_analyzed: Number of conversations analyzed
        issues_found: Number of issues found
        findings: JSON-serializable findings
        improvements: JSON-serializable improvements made
        commit_hash: Git commit hash if changes were committed

    Returns:
        ID of inserted review
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO reviews (
                conversations_analyzed, issues_found, findings,
                improvements, commit_hash
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            conversations_analyzed,
            issues_found,
            json.dumps(findings, ensure_ascii=False),
            json.dumps(improvements, ensure_ascii=False),
            commit_hash
        ))
        conn.commit()
        return cursor.lastrowid


def add_learned_example(
    user_message: str,
    expected_skill: str,
    expected_action: str,
    expected_target: Optional[str] = None,
    source_conversation_id: Optional[int] = None
) -> int:
    """Add a learned example for future training.

    Args:
        user_message: Example user message
        expected_skill: Expected skill to use
        expected_action: Expected action
        expected_target: Expected target
        source_conversation_id: ID of source conversation

    Returns:
        ID of inserted example
    """
    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO learned_examples (
                user_message, expected_skill, expected_action,
                expected_target, source_conversation_id
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            user_message, expected_skill, expected_action,
            expected_target, source_conversation_id
        ))
        conn.commit()
        return cursor.lastrowid


def get_learned_examples(active_only: bool = True) -> List[Dict[str, Any]]:
    """Get learned examples for prompt enhancement.

    Args:
        active_only: Only return active examples

    Returns:
        List of learned examples
    """
    with get_connection() as conn:
        if active_only:
            rows = conn.execute("""
                SELECT user_message, expected_skill, expected_action, expected_target
                FROM learned_examples
                WHERE active = TRUE
                ORDER BY created_at DESC
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM learned_examples
                ORDER BY created_at DESC
            """).fetchall()

    return [dict(row) for row in rows]


def clear_chat_history(chat_id: int) -> int:
    """Clear conversation history for a chat (soft delete via flag).

    Note: We don't actually delete for analysis purposes,
    but we can exclude from history retrieval.

    Args:
        chat_id: Telegram chat ID

    Returns:
        Number of conversations affected
    """
    # For now, we keep the data but could add a 'cleared' flag if needed
    # This maintains data for analysis while respecting user intent
    with get_connection() as conn:
        cursor = conn.execute("""
            SELECT COUNT(*) FROM conversations WHERE chat_id = ?
        """, (chat_id,))
        count = cursor.fetchone()[0]

    return count


def get_database_stats() -> Dict[str, Any]:
    """Get database statistics.

    Returns:
        Dict with various statistics
    """
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations"
        ).fetchone()[0]

        flagged = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE flagged = TRUE"
        ).fetchone()[0]

        unreviewed = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE flagged = TRUE AND reviewed = FALSE"
        ).fetchone()[0]

        reviews = conn.execute(
            "SELECT COUNT(*) FROM reviews"
        ).fetchone()[0]

        examples = conn.execute(
            "SELECT COUNT(*) FROM learned_examples WHERE active = TRUE"
        ).fetchone()[0]

    return {
        "total_conversations": total,
        "flagged_conversations": flagged,
        "unreviewed_conversations": unreviewed,
        "total_reviews": reviews,
        "active_examples": examples,
    }
