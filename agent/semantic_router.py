"""Embedding-based semantic router for intent classification.

Uses EmbeddingGemma (or similar) via LM Studio /v1/embeddings to compute
semantic similarity between user messages and pre-computed skill/action
embeddings. Provides fast routing (~50ms) without needing the LLM for
tool-calling.

Cache strategy:
- On startup: load cached embeddings from disk if valid
- If cache invalid: defer re-embedding to first LM Studio availability
- Cache key: SHA-256 of all skill names + versions + hint texts + command descriptions
- Any SKILL.md change invalidates the cache automatically
"""

import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from .config import Settings
from .skill_loader import SkillDefinition
from .wol import is_lm_studio_available

logger = logging.getLogger(__name__)


@dataclass
class EmbeddingEntry:
    """A single embeddable text with its embedding vector and metadata."""

    text: str
    embedding: List[float]
    skill: str
    entry_type: str  # "intent_hint" or "action"
    action: Optional[str] = None


@dataclass
class SemanticMatch:
    """Result of semantic routing."""

    skill: str
    action: Optional[str] = None
    skill_similarity: float = 0.0
    action_similarity: float = 0.0
    top_skills: List[Tuple[str, float]] = field(default_factory=list)


@dataclass
class SemanticRouter:
    """Embedding-based semantic router for intent classification."""

    entries: List[EmbeddingEntry] = field(default_factory=list)
    cache_key: str = ""
    _ready: bool = False
    _refreshing: bool = False


# Module-level singleton
_router: Optional[SemanticRouter] = None


def get_router() -> SemanticRouter:
    """Get the router singleton."""
    global _router
    if _router is None:
        _router = SemanticRouter()
    return _router


async def init_router(
    skills: Dict[str, SkillDefinition],
    settings: Settings,
) -> None:
    """Initialize the semantic router.

    Loads cached embeddings if available and valid.
    If cache is stale, marks router for background refresh.
    Called during app startup from lifespan().

    Args:
        skills: Loaded skill definitions from registry
        settings: Application settings
    """
    router = get_router()
    cache_path = _get_cache_path(settings)
    current_key = _compute_cache_key(skills)
    router.cache_key = current_key

    # Try loading from cache
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("cache_key") == current_key:
                router.entries = [
                    EmbeddingEntry(**e) for e in cached["entries"]
                ]
                router._ready = True
                logger.info(
                    f"Semantic router loaded from cache: "
                    f"{len(router.entries)} entries"
                )
                return
            else:
                logger.info("Embedding cache stale, will refresh")
        except Exception as e:
            logger.warning(f"Failed to load embedding cache: {e}")

    # Cache miss or stale - try to build now if LM Studio is up
    if await is_lm_studio_available(settings):
        await refresh_embeddings(skills, settings)
    else:
        logger.info(
            "LM Studio not available at startup, "
            "embeddings will be computed on first availability"
        )


async def route(
    message: str,
    settings: Settings,
    skills: Dict[str, SkillDefinition],
) -> Optional[SemanticMatch]:
    """Route a user message using embedding similarity.

    Args:
        message: User's natural language message
        settings: Application settings
        skills: Loaded skill definitions (for deferred refresh)

    Returns:
        SemanticMatch with routing decision, or None if router unavailable
    """
    router = get_router()

    # Deferred initialization: refresh if not ready and LM Studio is up
    if not router._ready and not router._refreshing:
        if await is_lm_studio_available(settings, timeout=2.0):
            await refresh_embeddings(skills, settings)

    if not router._ready:
        return None  # Caller falls back to full LLM

    # Embed the user message
    user_embedding = await _embed_text(message, settings)
    if user_embedding is None:
        return None  # Embedding endpoint failed

    # Compute similarities
    skill_scores: Dict[str, float] = {}
    action_scores: Dict[str, Tuple[str, float]] = {}

    for entry in router.entries:
        sim = _cosine_similarity(user_embedding, entry.embedding)

        # Track best match per skill (across hints AND actions)
        if entry.skill not in skill_scores or sim > skill_scores[entry.skill]:
            skill_scores[entry.skill] = sim

        # Track best action match per skill (only action entries)
        if entry.entry_type == "action" and entry.action:
            key = entry.skill
            if key not in action_scores or sim > action_scores[key][1]:
                action_scores[key] = (entry.action, sim)

    if not skill_scores:
        return None

    # Sort skills by score
    sorted_skills = sorted(
        skill_scores.items(), key=lambda x: x[1], reverse=True
    )

    best_skill, best_skill_sim = sorted_skills[0]

    # Get best action for that skill
    best_action = None
    best_action_sim = 0.0
    if best_skill in action_scores:
        best_action, best_action_sim = action_scores[best_skill]

    return SemanticMatch(
        skill=best_skill,
        action=best_action,
        skill_similarity=best_skill_sim,
        action_similarity=best_action_sim,
        top_skills=sorted_skills[:3],
    )


async def refresh_embeddings(
    skills: Dict[str, SkillDefinition],
    settings: Settings,
) -> None:
    """Recompute all embeddings and save to cache.

    Args:
        skills: All loaded skill definitions
        settings: Application settings
    """
    router = get_router()
    router._refreshing = True

    try:
        texts: List[str] = []
        metadata: List[Tuple[str, str, Optional[str]]] = []

        for name, skill in skills.items():
            # Add intent hints
            for hint in skill.intent_hints:
                texts.append(hint)
                metadata.append((name, "intent_hint", None))

            # Add action descriptions
            for cmd in skill.commands:
                action_text = f"{cmd.name}: {cmd.description}"
                texts.append(action_text)
                metadata.append((name, "action", cmd.name))

        logger.info(f"Computing embeddings for {len(texts)} texts...")
        start = time.monotonic()

        embeddings = await _embed_batch(texts, settings)
        if embeddings is None or len(embeddings) != len(texts):
            logger.error(
                f"Failed to compute embeddings "
                f"(got {len(embeddings) if embeddings else 0}, expected {len(texts)})"
            )
            return

        elapsed = time.monotonic() - start
        logger.info(f"Computed {len(embeddings)} embeddings in {elapsed:.1f}s")

        # Build entries
        entries = []
        for i, (text, emb) in enumerate(zip(texts, embeddings)):
            skill_name, entry_type, action = metadata[i]
            entries.append(EmbeddingEntry(
                text=text,
                embedding=emb,
                skill=skill_name,
                entry_type=entry_type,
                action=action,
            ))

        router.entries = entries
        router.cache_key = _compute_cache_key(skills)
        router._ready = True

        # Save to cache
        _save_cache(entries, router.cache_key, settings)

    finally:
        router._refreshing = False


async def _embed_text(text: str, settings: Settings) -> Optional[List[float]]:
    """Embed a single text via LM Studio /v1/embeddings.

    Args:
        text: Text to embed
        settings: Application settings

    Returns:
        Embedding vector or None on failure
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.lm_studio_url}/v1/embeddings",
                json={
                    "model": settings.embedding_model,
                    "input": text,
                },
            )
            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            else:
                logger.warning(
                    f"Embedding API error: {response.status_code} - "
                    f"{response.text[:200]}"
                )
                return None
    except (httpx.RequestError, httpx.TimeoutException) as e:
        logger.warning(f"Embedding request failed: {e}")
        return None


async def _embed_batch(
    texts: List[str], settings: Settings
) -> Optional[List[List[float]]]:
    """Embed multiple texts via LM Studio /v1/embeddings.

    Processes in chunks to avoid overwhelming the endpoint.

    Args:
        texts: List of texts to embed
        settings: Application settings

    Returns:
        List of embedding vectors, or None on failure
    """
    if not texts:
        return []

    BATCH_SIZE = 32
    all_embeddings: List[List[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.lm_studio_url}/v1/embeddings",
                    json={
                        "model": settings.embedding_model,
                        "input": batch,
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    # Sort by index to maintain order
                    sorted_data = sorted(
                        data["data"], key=lambda x: x["index"]
                    )
                    all_embeddings.extend(
                        [d["embedding"] for d in sorted_data]
                    )
                else:
                    logger.error(
                        f"Batch embedding failed: {response.status_code} - "
                        f"{response.text[:200]}"
                    )
                    return None
        except (httpx.RequestError, httpx.TimeoutException) as e:
            logger.error(f"Batch embedding request failed: {e}")
            return None

    return all_embeddings


def _save_cache(
    entries: List[EmbeddingEntry],
    cache_key: str,
    settings: Settings,
) -> None:
    """Save embeddings to disk cache."""
    cache_path = _get_cache_path(settings)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    cache_data = {
        "cache_key": cache_key,
        "created_at": time.time(),
        "entry_count": len(entries),
        "entries": [
            {
                "text": e.text,
                "embedding": e.embedding,
                "skill": e.skill,
                "entry_type": e.entry_type,
                "action": e.action,
            }
            for e in entries
        ],
    }

    cache_path.write_text(
        json.dumps(cache_data, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Saved embedding cache: {len(entries)} entries to {cache_path}")


def _get_cache_path(settings: Settings) -> Path:
    """Get the path for the embedding cache file."""
    return settings.project_root / "data" / "embedding_cache.json"


def _compute_cache_key(skills: Dict[str, SkillDefinition]) -> str:
    """Compute a hash key that changes when skills change.

    Incorporates skill names, versions, intent_hints texts,
    and command descriptions so any edit triggers re-embedding.
    """
    parts = []
    for name in sorted(skills.keys()):
        skill = skills[name]
        parts.append(f"{name}:{skill.version}")
        parts.extend(skill.intent_hints)
        for cmd in skill.commands:
            parts.append(f"{cmd.name}:{cmd.description}")

    combined = "|".join(parts)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors.

    Pure Python implementation - no numpy needed.
    For 256-768 dim vectors, this runs in <1ms.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)
