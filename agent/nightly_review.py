#!/usr/bin/env python3
"""Nightly review script for conversation analysis and self-improvement.

Analyzes flagged conversations, identifies patterns, and suggests
improvements to the system prompt or skills.

Usage:
    python -m agent.nightly_review
    python -m agent.nightly_review --dry-run
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agent.config import get_settings
from agent.database import (
    init_database,
    get_flagged_conversations,
    get_unknown_intent_patterns,
    get_skill_usage_stats,
    mark_reviewed,
    save_review,
    add_learned_example,
    get_database_stats,
)
from agent import self_annealing
from agent.skill_config import get_skill_path, verify_skill_paths

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def analyze_conversations(conversations: list) -> dict:
    """Analyze flagged conversations to find patterns.

    Args:
        conversations: List of flagged conversation dicts

    Returns:
        Analysis results
    """
    analysis = {
        "total": len(conversations),
        "unknown_intents": [],
        "errors": [],
        "bad_responses": [],
        "patterns": {},
    }

    for conv in conversations:
        skill = conv.get("intent_skill")
        success = conv.get("success")
        user_msg = conv.get("user_message", "")
        assistant_resp = conv.get("assistant_response", "")

        # Categorize
        if skill == "unknown" or skill is None:
            analysis["unknown_intents"].append({
                "user_message": user_msg,
                "response": assistant_resp[:200],
            })
        elif not success:
            analysis["errors"].append({
                "skill": skill,
                "action": conv.get("intent_action"),
                "error": conv.get("error_message"),
                "user_message": user_msg,
            })

        # Check for bad response patterns
        bad_patterns = ["self-annealing", "skill", "feature", "nicht verstanden"]
        resp_lower = assistant_resp.lower()
        if any(p in resp_lower for p in bad_patterns):
            analysis["bad_responses"].append({
                "user_message": user_msg,
                "response": assistant_resp[:200],
            })

    return analysis


def generate_improvements(analysis: dict, unknown_patterns: list) -> dict:
    """Generate improvement suggestions based on analysis.

    Args:
        analysis: Analysis results from analyze_conversations
        unknown_patterns: Common unknown intent patterns

    Returns:
        Improvement suggestions
    """
    improvements = {
        "new_examples": [],
        "prompt_additions": [],
        "skill_suggestions": [],
    }

    # Suggest new examples for common unknown patterns
    for pattern in unknown_patterns[:10]:  # Top 10
        msg = pattern["user_message"]
        count = pattern["count"]

        if count >= 2:  # Only if it happened multiple times
            # Try to infer the likely skill
            likely_skill = _infer_skill(msg)
            if likely_skill:
                improvements["new_examples"].append({
                    "user_message": msg,
                    "suggested_skill": likely_skill["skill"],
                    "suggested_action": likely_skill["action"],
                    "script_path": likely_skill.get("script_path"),
                    "occurrences": count,
                })

    # Suggest prompt additions for bad responses
    if analysis["bad_responses"]:
        improvements["prompt_additions"].append(
            "Add more explicit examples for unclear queries"
        )

    return improvements


def _infer_skill(message: str) -> dict | None:
    """Try to infer which skill a message should map to.

    Args:
        message: User message

    Returns:
        Dict with skill, action, and script_path, or None
    """
    msg_lower = message.lower()

    # Server/VM related
    if any(kw in msg_lower for kw in ["server", "vm", "container", "läuft", "status", "homelab"]):
        return {
            "skill": "proxmox",
            "action": "overview",
            "script_path": get_skill_path("proxmox"),
        }

    # Camera related
    if any(kw in msg_lower for kw in ["kamera", "camera", "bewegung", "aufnahme"]):
        return {
            "skill": "unifi-protect",
            "action": "cameras",
            "script_path": get_skill_path("unifi-protect"),
        }

    # Smart home related
    if any(kw in msg_lower for kw in ["licht", "light", "lampe", "schalter"]):
        return {
            "skill": "homeassistant",
            "action": "entities",
            "script_path": get_skill_path("homeassistant"),
        }

    # DNS related
    if any(kw in msg_lower for kw in ["dns", "pihole", "block", "werbung"]):
        return {
            "skill": "pihole",
            "action": "status",
            "script_path": get_skill_path("pihole"),
        }

    # Network related
    if any(kw in msg_lower for kw in ["netzwerk", "network", "wlan", "wifi", "client"]):
        return {
            "skill": "unifi-network",
            "action": "clients",
            "script_path": get_skill_path("unifi-network"),
        }

    return None


def apply_improvements(
    improvements: dict,
    settings,
    dry_run: bool = False
) -> dict:
    """Apply improvements to the system.

    Args:
        improvements: Improvement suggestions
        settings: Application settings
        dry_run: If True, don't actually make changes

    Returns:
        Results of applied improvements
    """
    results = {
        "examples_added": 0,
        "prompt_updated": False,
        "commit_hash": None,
    }

    if dry_run:
        logger.info("DRY RUN - no changes will be made")
        return results

    # Add learned examples to database
    for example in improvements.get("new_examples", []):
        try:
            add_learned_example(
                user_message=example["user_message"],
                expected_skill=example["suggested_skill"],
                expected_action=example["suggested_action"],
            )
            results["examples_added"] += 1
            logger.info(f"Added example: '{example['user_message'][:50]}...' -> {example['suggested_skill']}")
        except Exception as e:
            logger.warning(f"Failed to add example: {e}")

    # TODO: Auto-update system prompt with new examples
    # This would require reading intent_classifier.py, modifying SYSTEM_PROMPT,
    # and writing it back. For now, we just log suggestions.

    if improvements.get("prompt_additions"):
        logger.info(f"Suggested prompt additions: {improvements['prompt_additions']}")

    return results


async def run_review(dry_run: bool = False) -> dict:
    """Run the nightly review process.

    Args:
        dry_run: If True, analyze but don't make changes

    Returns:
        Review results
    """
    settings = get_settings()

    # Initialize database
    init_database(settings.project_root)

    # Verify skill paths
    skill_check = verify_skill_paths(settings.project_root)
    if skill_check["missing"]:
        logger.warning(f"Missing skill scripts: {skill_check['missing']}")
    else:
        logger.info(f"All {len(skill_check['valid'])} skill scripts verified")

    # Get statistics
    stats = get_database_stats()
    logger.info(f"Database stats: {stats}")

    # Get flagged conversations
    flagged = get_flagged_conversations(limit=100, reviewed=False)
    logger.info(f"Found {len(flagged)} unreviewed flagged conversations")

    if not flagged:
        logger.info("No conversations to review")
        return {"status": "no_data", "conversations_analyzed": 0}

    # Analyze conversations
    analysis = analyze_conversations(flagged)
    logger.info(f"Analysis: {analysis['total']} total, "
                f"{len(analysis['unknown_intents'])} unknown, "
                f"{len(analysis['errors'])} errors, "
                f"{len(analysis['bad_responses'])} bad responses")

    # Get common unknown patterns
    unknown_patterns = get_unknown_intent_patterns(limit=20)
    logger.info(f"Top unknown patterns: {unknown_patterns[:5]}")

    # Generate improvements
    improvements = generate_improvements(analysis, unknown_patterns)
    logger.info(f"Suggested improvements: {len(improvements['new_examples'])} new examples")

    # Apply improvements
    results = apply_improvements(improvements, settings, dry_run=dry_run)

    # Mark conversations as reviewed
    if not dry_run:
        conversation_ids = [c["id"] for c in flagged]
        mark_reviewed(conversation_ids)
        logger.info(f"Marked {len(conversation_ids)} conversations as reviewed")

        # Save review to database
        review_id = save_review(
            conversations_analyzed=len(flagged),
            issues_found=len(analysis["unknown_intents"]) + len(analysis["errors"]),
            findings=analysis,
            improvements=improvements,
            commit_hash=results.get("commit_hash"),
        )
        logger.info(f"Saved review #{review_id}")

    return {
        "status": "completed",
        "conversations_analyzed": len(flagged),
        "issues_found": len(analysis["unknown_intents"]) + len(analysis["errors"]),
        "improvements_suggested": len(improvements["new_examples"]),
        "examples_added": results["examples_added"],
        "skills_verified": len(skill_check["valid"]),
        "skills_missing": skill_check["missing"],
        "dry_run": dry_run,
    }


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Nightly review of conversations for self-improvement"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze but don't make changes",
    )
    parser.add_argument(
        "--stats-only",
        action="store_true",
        help="Only show database statistics",
    )

    args = parser.parse_args()

    settings = get_settings()
    init_database(settings.project_root)

    if args.stats_only:
        stats = get_database_stats()
        print(json.dumps(stats, indent=2))

        print("\nSkill usage:")
        usage = get_skill_usage_stats()
        for skill, count in usage.items():
            print(f"  {skill}: {count}")

        print("\nTop unknown patterns:")
        patterns = get_unknown_intent_patterns(limit=10)
        for p in patterns:
            print(f"  ({p['count']}x) {p['user_message'][:60]}...")
        return

    # Run async review
    import asyncio
    result = asyncio.run(run_review(dry_run=args.dry_run))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
