"""Tests for threat deduplication."""

from unittest.mock import patch

import pytest

from backend.dedup import (
    _cosine_similarity,
    _select_preferred_threat,
    _threat_to_text,
    deduplicate_threats,
)
from backend.models.enums import StrideCategory
from backend.models.state import DreadScore, Threat, ThreatsList


def _make_threat(
    name: str = "Test Threat",
    category: StrideCategory = StrideCategory.SPOOFING,
    description: str = "A test threat description with enough words to be valid for the model",
    target: str = "API Gateway",
    impact: str = "High",
    likelihood: str = "Medium",
    dread: DreadScore | None = None,
    mitigations: list[str] | None = None,
) -> Threat:
    """Helper to create Threat instances for testing."""
    return Threat(
        name=name,
        stride_category=category,
        description=description,
        target=target,
        impact=impact,
        likelihood=likelihood,
        dread=dread,
        mitigations=mitigations or ["Mitigation 1", "Mitigation 2"],
    )


def _make_dread(
    damage: int = 5, repro: int = 5, exploit: int = 5, users: int = 5, discover: int = 5
) -> DreadScore:
    """Helper to create DreadScore instances."""
    return DreadScore(
        damage=damage,
        reproducibility=repro,
        exploitability=exploit,
        affected_users=users,
        discoverability=discover,
    )


# --- Cosine similarity tests ---


def test_cosine_similarity_identical_vectors():
    """Identical vectors have similarity 1.0."""
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    """Orthogonal vectors have similarity 0.0."""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_zero_vector():
    """Zero vector returns 0.0 (no division error)."""
    a = [0.0, 0.0]
    b = [1.0, 2.0]
    assert _cosine_similarity(a, b) == 0.0


# --- Preferred threat selection tests ---


def test_select_preferred_higher_dread_wins():
    """Threat with higher DREAD score is preferred."""
    a = _make_threat(name="A", dread=_make_dread(damage=3))
    b = _make_threat(name="B", dread=_make_dread(damage=8))
    assert _select_preferred_threat(a, b) is b


def test_select_preferred_longer_description_wins():
    """When DREAD scores are equal, longer description wins."""
    short_desc = "A short threat description that is valid but not very detailed really"
    long_desc = "A much longer and more detailed threat description that provides significantly more context about the attack vector and impact"
    a = _make_threat(name="A", description=short_desc)
    b = _make_threat(name="B", description=long_desc)
    assert _select_preferred_threat(a, b) is b


def test_select_preferred_stable_ordering():
    """When all else is equal, first threat (a) wins."""
    a = _make_threat(name="A")
    b = _make_threat(name="B")
    assert _select_preferred_threat(a, b) is a


# --- threat_to_text tests ---


def test_threat_to_text_format():
    """Text representation includes target and description."""
    threat = _make_threat(target="Database", description="SQL injection via user input parameters")
    text = _threat_to_text(threat)
    assert text == "Database: SQL injection via user input parameters"


# --- Embedding-based dedup tests ---


def _mock_embed(text: str) -> list[float]:
    """Mock embedding that returns a deterministic vector based on text content."""
    # Simple hash-based mock: similar texts get similar vectors
    import hashlib

    h = hashlib.md5(text.encode()).hexdigest()
    return [int(c, 16) / 15.0 for c in h]


def _mock_embed_with_similarity(similarity_map: dict[str, list[float]]):
    """Return a mock embed function that maps specific texts to specific vectors."""

    def embed(text: str) -> list[float]:
        for key, vec in similarity_map.items():
            if key in text:
                return vec
        # Default: unique vector
        return _mock_embed(text)

    return embed


@patch("backend.dedup.embed_text")
def test_dedup_identical_threats_removed(mock_embed):
    """Two identical threats should be deduplicated to one."""
    vec = [1.0] * 16
    mock_embed.return_value = vec

    threat = _make_threat(name="SQL Injection")
    threats = ThreatsList(threats=[threat, threat])

    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 1
    assert len(result.threats.threats) == 1


@patch("backend.dedup.embed_text")
def test_dedup_similar_threats_removed(mock_embed):
    """Threats with high cosine similarity should be deduplicated."""
    # Two very similar vectors (cosine sim > 0.85)
    vec_a = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
    vec_b = [1.0, 0.1, 1.0, 0.1, 1.0, 0.1, 1.0, 0.1]
    mock_embed.side_effect = [vec_a, vec_b]

    a = _make_threat(name="SQL Injection on DB", target="Database")
    b = _make_threat(name="SQL Injection on Database", target="Database")
    threats = ThreatsList(threats=[a, b])

    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 1
    assert len(result.threats.threats) == 1


@patch("backend.dedup.embed_text")
def test_dedup_different_threats_kept(mock_embed):
    """Threats with low similarity should both be kept."""
    # Orthogonal vectors (cosine sim = 0.0)
    vec_a = [1.0, 0.0, 0.0, 0.0]
    vec_b = [0.0, 1.0, 0.0, 0.0]
    mock_embed.side_effect = [vec_a, vec_b]

    a = _make_threat(name="SQL Injection", target="Database")
    b = _make_threat(name="DDoS Attack", target="Load Balancer")
    threats = ThreatsList(threats=[a, b])

    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 0
    assert len(result.threats.threats) == 2


@patch("backend.dedup.embed_text")
def test_dedup_cross_list_removes_duplicates(mock_embed):
    """New threats that duplicate existing threats are removed."""
    vec = [1.0] * 8
    mock_embed.return_value = vec

    existing = ThreatsList(threats=[_make_threat(name="Existing")])
    new = ThreatsList(threats=[_make_threat(name="Duplicate of Existing")])

    result = deduplicate_threats(new, existing_threats=existing, threshold=0.85)
    assert result.removed_count == 1
    assert len(result.threats.threats) == 0


@patch("backend.dedup.embed_text")
def test_dedup_cross_list_keeps_unique(mock_embed):
    """New threats that differ from existing are kept."""
    vec_existing = [1.0, 0.0, 0.0, 0.0]
    vec_new = [0.0, 1.0, 0.0, 0.0]
    mock_embed.side_effect = [vec_new, vec_existing]

    existing = ThreatsList(threats=[_make_threat(name="Existing", target="DB")])
    new = ThreatsList(threats=[_make_threat(name="New Threat", target="API")])

    result = deduplicate_threats(new, existing_threats=existing, threshold=0.85)
    assert result.removed_count == 0
    assert len(result.threats.threats) == 1


# --- Edge cases ---


def test_dedup_empty_list():
    """Empty threat list returns empty with no errors."""
    threats = ThreatsList(threats=[])
    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 0
    assert len(result.threats.threats) == 0


def test_dedup_single_threat():
    """Single threat is returned as-is without embedding call."""
    threat = _make_threat(name="Only Threat")
    threats = ThreatsList(threats=[threat])
    # No mock needed — should short-circuit before calling embed_text
    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 0
    assert len(result.threats.threats) == 1
    assert result.threats.threats[0].name == "Only Threat"


# --- Fallback tests ---


@patch("backend.dedup.embed_text", side_effect=RuntimeError("Model load failed"))
def test_dedup_falls_back_to_text_on_embedding_failure(mock_embed):
    """When embeddings fail, falls back to text-based dedup."""
    a = _make_threat(
        name="SQL Injection",
        target="Database",
        description="An attacker exploits SQL injection vulnerability in the database query parameters to extract sensitive data",
    )
    b = _make_threat(
        name="SQL Injection Attack",
        target="Database",
        description="An attacker exploits SQL injection vulnerability in the database query parameters to extract sensitive data",
    )
    threats = ThreatsList(threats=[a, b])

    result = deduplicate_threats(threats, threshold=0.85)
    # Same target + nearly identical description → should be deduplicated by text fallback
    assert result.removed_count == 1
    assert len(result.threats.threats) == 1


@patch("backend.dedup.embed_text", side_effect=RuntimeError("Model load failed"))
def test_dedup_text_fallback_keeps_different_threats(mock_embed):
    """Text fallback correctly keeps distinct threats."""
    a = _make_threat(
        name="SQL Injection",
        target="Database",
        description="An attacker exploits SQL injection vulnerability in the database query parameters to extract sensitive data",
    )
    b = _make_threat(
        name="DDoS Attack",
        target="Load Balancer",
        description="An attacker overwhelms the load balancer with massive traffic volume causing service unavailability for legitimate users",
    )
    threats = ThreatsList(threats=[a, b])

    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 0
    assert len(result.threats.threats) == 2


# --- Preference in dedup ---


@patch("backend.dedup.embed_text")
def test_dedup_prefers_higher_dread_score(mock_embed):
    """When deduplicating, the threat with higher DREAD score is kept."""
    vec = [1.0] * 8
    mock_embed.return_value = vec

    low_dread = _make_threat(name="Low Risk", dread=_make_dread(damage=2))
    high_dread = _make_threat(name="High Risk", dread=_make_dread(damage=9))
    threats = ThreatsList(threats=[low_dread, high_dread])

    result = deduplicate_threats(threats, threshold=0.85)
    assert result.removed_count == 1
    assert result.threats.threats[0].name == "High Risk"
