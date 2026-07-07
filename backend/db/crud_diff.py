"""Cross-model threat diff using embedding similarity.

Compares two completed threat models and classifies every threat as
added / removed / changed / unchanged, enabling "re-run diffing" —
the ability to see exactly what changed between two pipeline runs on
the same or similar system description.
"""

import logging
import math
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from backend.db import crud
from backend.db.vectors import embed_text


logger = logging.getLogger(__name__)

# Similarity threshold for treating two threats as "the same threat".
# Below this → the head threat is "added" and the base threat is "removed".
_DEFAULT_MATCH_THRESHOLD = 0.75

# If matched threats have cosine similarity above this value AND no
# significant field-level change, they are "unchanged"; otherwise "changed".
_UNCHANGED_THRESHOLD = 0.97

# DREAD score delta magnitude that qualifies a match as "changed".
_DREAD_DELTA_THRESHOLD = 0.5


@dataclass
class ThreatDiffEntry:
    """A single entry in the diff result."""

    status: str  # "added" | "removed" | "changed" | "unchanged"
    head: dict[str, Any] | None = None
    base: dict[str, Any] | None = None
    similarity: float | None = None
    dread_delta: float | None = None


@dataclass
class ModelDiffResult:
    """Full diff between two threat models."""

    base_model_id: str
    head_model_id: str
    base_count: int
    head_count: int
    added: int = 0
    removed: int = 0
    changed: int = 0
    unchanged: int = 0
    threats: list[ThreatDiffEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_model_id": self.base_model_id,
            "head_model_id": self.head_model_id,
            "summary": {
                "base_count": self.base_count,
                "head_count": self.head_count,
                "added": self.added,
                "removed": self.removed,
                "changed": self.changed,
                "unchanged": self.unchanged,
            },
            "threats": [
                {
                    "status": e.status,
                    "head": e.head,
                    "base": e.base,
                    "similarity": e.similarity,
                    "dread_delta": e.dread_delta,
                }
                for e in self.threats
            ],
        }


async def compare_models(
    base_model_id: str,
    head_model_id: str,
    match_threshold: float = _DEFAULT_MATCH_THRESHOLD,
) -> ModelDiffResult:
    """Compare threats between two models.

    For each threat in head, finds the best-matching threat in base using
    cosine similarity on embeddings. Threats with similarity >= match_threshold
    are paired; within a pair, "changed" is detected via DREAD delta or
    significant description divergence.

    Args:
        base_model_id: The older / reference model.
        head_model_id: The newer / re-run model.
        match_threshold: Minimum cosine similarity to consider two threats
            the same threat (default 0.75).

    Returns:
        ModelDiffResult with classified threat entries.
    """
    base_threats = await crud.list_threats(base_model_id)
    head_threats = await crud.list_threats(head_model_id)

    result = ModelDiffResult(
        base_model_id=base_model_id,
        head_model_id=head_model_id,
        base_count=len(base_threats),
        head_count=len(head_threats),
    )

    if not base_threats and not head_threats:
        return result

    try:
        entries = _diff_by_embeddings(base_threats, head_threats, match_threshold)
    except (ValueError, RuntimeError) as exc:
        logger.warning(f"Embedding diff failed ({exc}), falling back to text diff")
        entries = _diff_by_text(base_threats, head_threats, match_threshold)

    result.threats = entries
    for e in entries:
        result.added += e.status == "added"
        result.removed += e.status == "removed"
        result.changed += e.status == "changed"
        result.unchanged += e.status == "unchanged"

    return result


def _threat_text(t: dict[str, Any]) -> str:
    return f"{t.get('target', '')}: {t.get('description', '')}"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _dread_score(t: dict[str, Any]) -> float | None:
    score = t.get("dread_score")
    return float(score) if score is not None else None


def _is_changed(base: dict[str, Any], head: dict[str, Any], similarity: float) -> bool:
    """Decide whether a matched pair should be classified as 'changed'."""
    if similarity < _UNCHANGED_THRESHOLD:
        return True

    base_dread = _dread_score(base)
    head_dread = _dread_score(head)
    if base_dread is not None and head_dread is not None:
        if abs(head_dread - base_dread) >= _DREAD_DELTA_THRESHOLD:
            return True

    return False


def _diff_by_embeddings(
    base: list[dict[str, Any]],
    head: list[dict[str, Any]],
    threshold: float,
) -> list[ThreatDiffEntry]:
    base_embs = [(t, embed_text(_threat_text(t))) for t in base]
    head_embs = [(t, embed_text(_threat_text(t))) for t in head]

    # Greedy best-match: for each head threat, find the unmatched base threat
    # with the highest cosine similarity above the threshold.
    used_base: set[int] = set()
    entries: list[ThreatDiffEntry] = []

    for h_threat, h_emb in head_embs:
        best_idx: int | None = None
        best_sim = 0.0
        for i, (_, b_emb) in enumerate(base_embs):
            if i in used_base:
                continue
            sim = _cosine(h_emb, b_emb)
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_idx = i

        if best_idx is not None:
            used_base.add(best_idx)
            b_threat = base_embs[best_idx][0]
            dread_delta = None
            h_dread = _dread_score(h_threat)
            b_dread = _dread_score(b_threat)
            if h_dread is not None and b_dread is not None:
                dread_delta = round(h_dread - b_dread, 2)

            status = "changed" if _is_changed(b_threat, h_threat, best_sim) else "unchanged"
            entries.append(
                ThreatDiffEntry(
                    status=status,
                    head=h_threat,
                    base=b_threat,
                    similarity=round(best_sim, 4),
                    dread_delta=dread_delta,
                )
            )
        else:
            entries.append(ThreatDiffEntry(status="added", head=h_threat))

    # Remaining unmatched base threats are "removed"
    for i, (b_threat, _) in enumerate(base_embs):
        if i not in used_base:
            entries.append(ThreatDiffEntry(status="removed", base=b_threat))

    return entries


def _diff_by_text(
    base: list[dict[str, Any]],
    head: list[dict[str, Any]],
    threshold: float,
) -> list[ThreatDiffEntry]:
    """Text-based fallback using SequenceMatcher."""
    text_threshold = max(0.0, threshold - 0.05)

    used_base: set[int] = set()
    entries: list[ThreatDiffEntry] = []

    for h_threat in head:
        h_text = _threat_text(h_threat)
        best_idx: int | None = None
        best_ratio = 0.0
        for i, b_threat in enumerate(base):
            if i in used_base:
                continue
            ratio = SequenceMatcher(None, h_text, _threat_text(b_threat)).ratio()
            if ratio >= text_threshold and ratio > best_ratio:
                best_ratio = ratio
                best_idx = i

        if best_idx is not None:
            used_base.add(best_idx)
            b_threat = base[best_idx]
            dread_delta = None
            h_dread = _dread_score(h_threat)
            b_dread = _dread_score(b_threat)
            if h_dread is not None and b_dread is not None:
                dread_delta = round(h_dread - b_dread, 2)
            status = "changed" if _is_changed(b_threat, h_threat, best_ratio) else "unchanged"
            entries.append(
                ThreatDiffEntry(
                    status=status,
                    head=h_threat,
                    base=b_threat,
                    similarity=round(best_ratio, 4),
                    dread_delta=dread_delta,
                )
            )
        else:
            entries.append(ThreatDiffEntry(status="added", head=h_threat))

    for i, b_threat in enumerate(base):
        if i not in used_base:
            entries.append(ThreatDiffEntry(status="removed", base=b_threat))

    return entries
