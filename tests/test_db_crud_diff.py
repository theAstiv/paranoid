"""Tests for cross-model threat diffing (crud_diff.py).

The diff logic has two code paths:
  1. Embedding-based (primary) — uses fastembed cosine similarity.
  2. Text-based fallback — uses SequenceMatcher.

Both paths are exercised through the public compare_models() API.  The
embedding path is tested with mock embeddings so fastembed is not required
in CI.
"""

from unittest.mock import patch

import pytest

from backend.db import crud
from backend.db.crud_diff import (
    ModelDiffResult,
    _diff_by_text,
    compare_models,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_model(title: str = "Test") -> str:
    return await crud.create_threat_model(
        title=title,
        description="test description",
        provider="anthropic",
        model="claude-sonnet-4",
    )


async def _add_threat(
    model_id: str,
    name: str = "Threat",
    description: str = "An attacker exploits the login form via SQL injection",
    target: str = "DB",
    dread_score: float | None = 6.0,
) -> str:
    return await crud.create_threat(
        model_id=model_id,
        name=name,
        description=description,
        target=target,
        impact="High",
        likelihood="Medium",
        mitigations=["Use parameterized queries", "Input validation"],
        stride_category="Tampering",
        dread_score=dread_score,
    )


def _fake_embed(text: str) -> list[float]:
    """Deterministic fake embedding: one-hot on text hash bucket (dim=16)."""
    idx = hash(text) % 16
    vec = [0.0] * 16
    vec[idx] = 1.0
    return vec


# ---------------------------------------------------------------------------
# Empty-model edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_both_empty(test_db):
    base_id = await _make_model("Base")
    head_id = await _make_model("Head")

    result = await compare_models(base_id, head_id)

    assert isinstance(result, ModelDiffResult)
    assert result.base_count == 0
    assert result.head_count == 0
    assert result.added == result.removed == result.changed == result.unchanged == 0
    assert result.threats == []


@pytest.mark.asyncio
async def test_diff_base_empty_all_added(test_db):
    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(head_id, name="New Threat")

    with patch("backend.db.crud_diff.embed_text", side_effect=_fake_embed):
        result = await compare_models(base_id, head_id)

    assert result.head_count == 1
    assert result.added == 1
    assert result.removed == 0
    assert all(e.status == "added" for e in result.threats)


@pytest.mark.asyncio
async def test_diff_head_empty_all_removed(test_db):
    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(base_id, name="Old Threat")

    with patch("backend.db.crud_diff.embed_text", side_effect=_fake_embed):
        result = await compare_models(base_id, head_id)

    assert result.base_count == 1
    assert result.removed == 1
    assert result.added == 0
    assert all(e.status == "removed" for e in result.threats)


# ---------------------------------------------------------------------------
# Matched pairs: unchanged vs changed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_identical_threats_unchanged(test_db):
    """Two models with the same threat text → unchanged."""
    description = "An attacker exploits the REST API to exfiltrate user PII"

    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(base_id, name="PII leak", description=description, dread_score=5.0)
    await _add_threat(head_id, name="PII leak", description=description, dread_score=5.0)

    def same_embed(text: str) -> list[float]:
        # Return the same vector for identical text so similarity == 1.0
        vec = [0.0] * 16
        vec[0] = 1.0
        return vec

    with patch("backend.db.crud_diff.embed_text", side_effect=same_embed):
        result = await compare_models(base_id, head_id)

    assert result.unchanged == 1
    assert result.changed == result.added == result.removed == 0
    entry = result.threats[0]
    assert entry.status == "unchanged"
    assert entry.similarity == 1.0
    assert entry.dread_delta == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_diff_large_dread_delta_changed(test_db):
    """Matched pair with DREAD score change ≥ 0.5 → changed."""
    description = "An attacker mounts a brute-force attack against the auth endpoint"

    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(base_id, description=description, dread_score=4.0)
    await _add_threat(head_id, description=description, dread_score=8.0)

    def same_embed(text: str) -> list[float]:
        vec = [0.0] * 16
        vec[0] = 1.0
        return vec

    with patch("backend.db.crud_diff.embed_text", side_effect=same_embed):
        result = await compare_models(base_id, head_id)

    assert result.changed == 1
    entry = result.threats[0]
    assert entry.status == "changed"
    assert entry.dread_delta == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Fallback text path
# ---------------------------------------------------------------------------


def test_diff_by_text_added_removed():
    """_diff_by_text correctly classifies completely different threats."""
    base = [
        {
            "target": "DB",
            "description": "SQL injection in login form via unparameterised query",
            "dread_score": 7.0,
        }
    ]
    head = [
        {
            "target": "API",
            "description": "Unvalidated redirect allows open-redirect phishing attack",
            "dread_score": 5.0,
        }
    ]
    entries = _diff_by_text(base, head, threshold=0.75)

    statuses = {e.status for e in entries}
    assert "added" in statuses
    assert "removed" in statuses


def test_diff_by_text_unchanged():
    """_diff_by_text recognises identical threat text as unchanged/matched."""
    text = "Attacker exploits IDOR vulnerability to access other users data"
    threat = {"target": "API", "description": text, "dread_score": 6.0}
    entries = _diff_by_text([threat], [threat], threshold=0.75)

    assert len(entries) == 1
    # Identical text → ratio == 1.0, above _UNCHANGED_THRESHOLD=0.97, delta == 0.0 → unchanged
    assert entries[0].status == "unchanged"
    assert entries[0].similarity == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# to_dict serialisation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_to_dict_structure(test_db):
    """to_dict() produces the expected JSON-serialisable shape."""
    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(head_id)

    with patch("backend.db.crud_diff.embed_text", side_effect=_fake_embed):
        result = await compare_models(base_id, head_id)

    d = result.to_dict()
    assert "summary" in d
    assert d["summary"]["added"] == 1
    assert isinstance(d["threats"], list)
    assert d["threats"][0]["status"] == "added"
    assert d["threats"][0]["head"] is not None
    assert d["threats"][0]["base"] is None


# ---------------------------------------------------------------------------
# Embedding fallback on error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_falls_back_to_text_on_embed_error(test_db):
    """compare_models uses text fallback when embed_text raises."""
    base_id = await _make_model("Base")
    head_id = await _make_model("Head")
    await _add_threat(head_id, name="New threat")

    with patch("backend.db.crud_diff.embed_text", side_effect=RuntimeError("model unavailable")):
        result = await compare_models(base_id, head_id)

    # Should still return a valid result via text fallback
    assert result.head_count == 1
    assert result.added + result.unchanged + result.changed + result.removed == 1
