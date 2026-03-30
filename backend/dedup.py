"""Threat deduplication using embedding similarity with text-based fallback.

Removes near-duplicate threats when merging across frameworks (STRIDE + MAESTRO)
or across pipeline iterations. Uses cosine similarity on embeddings from fastembed
as the primary strategy, with difflib.SequenceMatcher as a fallback.
"""

import logging
import math
from dataclasses import dataclass
from difflib import SequenceMatcher

from backend.db.vectors import embed_text
from backend.models.state import Threat, ThreatsList


logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    """Result of deduplication."""

    threats: ThreatsList
    removed_count: int


def deduplicate_threats(
    new_threats: ThreatsList,
    existing_threats: ThreatsList | None = None,
    threshold: float = 0.85,
) -> DedupResult:
    """Remove near-duplicate threats using embedding similarity.

    Two-pass strategy:
    1. Deduplicate within new_threats (intra-list)
    2. Deduplicate new_threats against existing_threats (cross-list)

    Falls back to text-based comparison if embedding generation fails.

    Args:
        new_threats: Threats to deduplicate
        existing_threats: Optional existing threats to compare against
        threshold: Similarity threshold (0.0-1.0). Pairs above this are duplicates.

    Returns:
        DedupResult with deduplicated threats and count of removals
    """
    if len(new_threats.threats) <= 1 and existing_threats is None:
        return DedupResult(threats=new_threats, removed_count=0)

    try:
        kept = _deduplicate_by_embeddings(
            new_threats.threats,
            existing_threats.threats if existing_threats else None,
            threshold,
        )
    except Exception:
        logger.warning("Embedding-based dedup failed, falling back to text comparison")
        kept = _deduplicate_by_text(
            new_threats.threats,
            existing_threats.threats if existing_threats else None,
            threshold,
        )

    removed = len(new_threats.threats) - len(kept)
    return DedupResult(threats=ThreatsList(threats=kept), removed_count=removed)


def _deduplicate_by_embeddings(
    threats: list[Threat],
    existing: list[Threat] | None,
    threshold: float,
) -> list[Threat]:
    """Deduplicate using embedding cosine similarity."""
    # Generate embeddings for all new threats
    threat_embeddings: list[tuple[Threat, list[float]]] = []
    for threat in threats:
        text = _threat_to_text(threat)
        embedding = embed_text(text)
        threat_embeddings.append((threat, embedding))

    # Generate embeddings for existing threats (if any)
    existing_embeddings: list[tuple[Threat, list[float]]] = []
    if existing:
        for threat in existing:
            text = _threat_to_text(threat)
            embedding = embed_text(text)
            existing_embeddings.append((threat, embedding))

    # Pass 1: Deduplicate within new threats
    kept_indices: list[int] = []
    for i, (threat_i, emb_i) in enumerate(threat_embeddings):
        is_duplicate = False
        for j in kept_indices:
            threat_j, emb_j = threat_embeddings[j]
            similarity = _cosine_similarity(emb_i, emb_j)
            if similarity >= threshold:
                # Keep the preferred one, potentially replacing j
                preferred = _select_preferred_threat(threat_j, threat_i)
                if preferred is threat_i:
                    threat_embeddings[j] = (threat_i, emb_i)
                is_duplicate = True
                break
        if not is_duplicate:
            kept_indices.append(i)

    intra_kept = [threat_embeddings[i] for i in kept_indices]

    # Pass 2: Remove new threats that duplicate existing threats
    if not existing_embeddings:
        return [t for t, _ in intra_kept]

    final_kept: list[Threat] = []
    for threat, emb in intra_kept:
        is_duplicate = False
        for _, existing_emb in existing_embeddings:
            similarity = _cosine_similarity(emb, existing_emb)
            if similarity >= threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            final_kept.append(threat)

    return final_kept


def _deduplicate_by_text(
    threats: list[Threat],
    existing: list[Threat] | None,
    threshold: float,
) -> list[Threat]:
    """Fallback dedup using SequenceMatcher on target + description."""
    # Use slightly lower threshold for text comparison (less precise than embeddings)
    text_threshold = max(0.0, threshold - 0.05)

    # Pass 1: Deduplicate within new threats
    kept: list[Threat] = []
    for threat in threats:
        text_i = _threat_to_text(threat)
        is_duplicate = False
        for j, kept_threat in enumerate(kept):
            text_j = _threat_to_text(kept_threat)
            ratio = SequenceMatcher(None, text_i, text_j).ratio()
            if ratio >= text_threshold:
                preferred = _select_preferred_threat(kept_threat, threat)
                if preferred is threat:
                    kept[j] = threat
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(threat)

    # Pass 2: Remove new threats that duplicate existing threats
    if not existing:
        return kept

    existing_texts = [_threat_to_text(t) for t in existing]
    final_kept: list[Threat] = []
    for threat in kept:
        text_i = _threat_to_text(threat)
        is_duplicate = False
        for existing_text in existing_texts:
            ratio = SequenceMatcher(None, text_i, existing_text).ratio()
            if ratio >= text_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            final_kept.append(threat)

    return final_kept


def _threat_to_text(threat: Threat) -> str:
    """Convert threat to comparable text string."""
    return f"{threat.target}: {threat.description}"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _select_preferred_threat(a: Threat, b: Threat) -> Threat:
    """Select the preferred threat from a duplicate pair.

    Preference order:
    1. Higher DREAD score
    2. Longer description (more detail)
    3. First threat (stable ordering)
    """
    # Compare DREAD scores
    a_score = a.dread.score if a.dread else 0.0
    b_score = b.dread.score if b.dread else 0.0
    if a_score != b_score:
        return a if a_score >= b_score else b

    # Compare description length
    if len(a.description) != len(b.description):
        return a if len(a.description) >= len(b.description) else b

    # Stable: keep first
    return a
