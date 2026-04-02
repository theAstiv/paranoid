"""Tests for the deterministic rule engine (backend/rules/engine.py).

Uses real seed JSON files for pattern matching tests.
Mocks embed_text for merge/dedup tests to avoid fastembed/ONNX dependency.
"""

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from backend.models.enums import Framework, StrideCategory
from backend.models.state import Threat, ThreatsList
from backend.rules.engine import (
    _MAESTRO_TO_STRIDE,
    _pattern_to_threat,
    extract_keywords,
    fetch_rag_context,
    match_patterns,
    merge_rule_and_llm_threats,
    run_rule_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_threat(
    name: str = "Test Threat",
    category: StrideCategory = StrideCategory.SPOOFING,
    description: str = "An attacker with network access can exploit this vulnerability to gain unauthorized access to the system",
    target: str = "API Gateway",
    mitigations: list[str] | None = None,
) -> Threat:
    return Threat(
        name=name,
        stride_category=category,
        description=description,
        target=target,
        impact="High",
        likelihood="Medium",
        mitigations=mitigations or ["Apply input validation", "Enable logging"],
    )


def _mock_embed(text: str) -> list[float]:
    """Deterministic mock embedding — different texts get distinct vectors."""
    h = hashlib.md5(text.encode()).hexdigest()
    return [int(c, 16) / 15.0 for c in h]


# ---------------------------------------------------------------------------
# extract_keywords
# ---------------------------------------------------------------------------


def test_extract_keywords_finds_auth_terms():
    desc = "The system uses JWT tokens for OAuth authentication and session management."
    kw = extract_keywords(desc)
    assert "jwt" in kw
    assert "oauth" in kw
    assert "authentication" in kw
    assert "session" in kw


def test_extract_keywords_finds_database_terms():
    desc = "Data is stored in PostgreSQL and cached in Redis."
    kw = extract_keywords(desc)
    assert "postgresql" in kw or "postgres" in kw
    assert "redis" in kw


def test_extract_keywords_finds_cloud_terms():
    desc = "Files are uploaded to S3 and processed by AWS Lambda behind a CDN."
    kw = extract_keywords(desc)
    assert "s3" in kw
    assert "aws" in kw
    assert "lambda" in kw
    assert "cdn" in kw


def test_extract_keywords_finds_ml_terms():
    desc = "An LLM inference API performs RAG over a vector embedding store."
    kw = extract_keywords(desc)
    assert "llm" in kw
    assert "inference" in kw
    assert "rag" in kw
    assert "embedding" in kw
    assert "vector" in kw


def test_extract_keywords_empty_description():
    kw = extract_keywords("")
    assert kw == set()


def test_extract_keywords_no_tech_terms():
    kw = extract_keywords("The quick brown fox jumps over the lazy dog.")
    assert len(kw) == 0


def test_extract_keywords_case_insensitive():
    kw = extract_keywords("POSTGRESQL database with JWT tokens")
    assert "postgresql" in kw
    assert "jwt" in kw


# ---------------------------------------------------------------------------
# match_patterns — uses real seed files
# ---------------------------------------------------------------------------


def test_match_patterns_auth_description_returns_threats():
    """Auth-heavy description should match spoofing/tampering seed patterns."""
    desc = (
        "A REST API using JWT tokens for authentication. Users authenticate via "
        "OAuth and sessions are managed with cookies."
    )
    result = match_patterns(desc, Framework.STRIDE)
    assert len(result.threats) > 0
    # All returned threats must be valid Threat instances
    for t in result.threats:
        assert isinstance(t, Threat)
        assert t.name
        assert t.stride_category in StrideCategory


def test_match_patterns_stride_filter_excludes_maestro_only():
    """STRIDE framework filter: no pattern should lack stride_category."""
    desc = "ML model training pipeline with vector embeddings and LLM inference."
    result = match_patterns(desc, Framework.STRIDE)
    # Every matched threat must have a valid StrideCategory (not a placeholder issue)
    for t in result.threats:
        assert t.stride_category in StrideCategory


def test_match_patterns_maestro_filter_returns_threats():
    """MAESTRO filter should return ML/AI-specific patterns."""
    desc = (
        "AI system with model training, inference API, and vector embedding pipeline. "
        "LLM prompt injection risks and training data poisoning concerns."
    )
    result = match_patterns(desc, Framework.MAESTRO)
    assert len(result.threats) > 0
    for t in result.threats:
        assert isinstance(t, Threat)


def test_match_patterns_no_keywords_returns_empty():
    """Description with no tech terms produces no matches."""
    result = match_patterns("A story about a hero and a dragon.", Framework.STRIDE)
    assert result.threats == []


def test_match_patterns_max_results_cap():
    """max_results parameter is respected."""
    desc = (
        "Web API with JWT, OAuth, sessions, cookies, SQL database, Redis cache, "
        "TLS encryption, admin panel, file upload, S3 storage."
    )
    result = match_patterns(desc, Framework.STRIDE, max_results=3)
    assert len(result.threats) <= 3


def test_match_patterns_hybrid_includes_both_frameworks():
    """HYBRID framework gets patterns from both STRIDE and MAESTRO seed files."""
    desc = (
        "ML-powered web API with JWT auth, SQL database, LLM inference, "
        "training data pipeline, and vector embeddings."
    )
    stride_result = match_patterns(desc, Framework.STRIDE, max_results=50)
    maestro_result = match_patterns(desc, Framework.MAESTRO, max_results=50)
    hybrid_result = match_patterns(desc, Framework.HYBRID, max_results=50)
    # HYBRID pool is union of both, so it can match at least as many as either alone
    assert len(hybrid_result.threats) >= max(
        len(stride_result.threats), len(maestro_result.threats)
    )


# ---------------------------------------------------------------------------
# _pattern_to_threat
# ---------------------------------------------------------------------------


def test_pattern_to_threat_stride_pattern():
    pattern = {
        "name": "SQL Injection",
        "stride_category": "Tampering",
        "description": "An attacker with access to user input fields can inject malicious SQL statements bypassing authentication controls.",
        "target": "Database",
        "impact": "High",
        "likelihood": "High",
        "mitigations": ["Use parameterized queries", "Apply input validation"],
    }
    threat = _pattern_to_threat(pattern, Framework.STRIDE)
    assert threat is not None
    assert threat.stride_category == StrideCategory.TAMPERING
    assert threat.name == "SQL Injection"


def test_pattern_to_threat_maestro_pattern_maps_to_stride():
    pattern = {
        "name": "Model Inversion",
        "maestro_category": "Model Security",
        "description": "An attacker with query access can reconstruct training data through repeated model inference calls.",
        "target": "ML Model",
        "impact": "High",
        "likelihood": "Medium",
        "mitigations": ["Add output noise", "Rate limit queries"],
    }
    threat = _pattern_to_threat(pattern, Framework.MAESTRO)
    assert threat is not None
    # Model Security maps to Tampering
    assert threat.stride_category == _MAESTRO_TO_STRIDE["Model Security"]


def test_pattern_to_threat_unknown_stride_category_defaults_to_tampering():
    pattern = {
        "name": "Unknown Threat",
        "stride_category": "NotACategory",
        "description": "An attacker can exploit this unknown vulnerability to compromise system security.",
        "target": "System",
        "impact": "Medium",
        "likelihood": "Low",
        "mitigations": ["Apply patches", "Monitor logs"],
    }
    threat = _pattern_to_threat(pattern, Framework.STRIDE)
    assert threat is not None
    assert threat.stride_category == StrideCategory.TAMPERING


def test_pattern_to_threat_missing_name_returns_none():
    pattern = {
        "stride_category": "Spoofing",
        "description": "Missing name field.",
        "mitigations": ["Fix it"],
    }
    threat = _pattern_to_threat(pattern, Framework.STRIDE)
    assert threat is None


# ---------------------------------------------------------------------------
# run_rule_engine
# ---------------------------------------------------------------------------


def test_run_rule_engine_no_llm_no_db():
    """Rule engine runs entirely offline — no LLM or DB required."""
    desc = (
        "A REST API that authenticates users with JWT tokens stored in PostgreSQL. "
        "Admin endpoints accessible via HTTPS."
    )
    result = run_rule_engine(desc, Framework.STRIDE)
    assert isinstance(result, ThreatsList)
    assert len(result.threats) > 0


def test_run_rule_engine_empty_description():
    result = run_rule_engine("", Framework.STRIDE)
    assert result.threats == []


def test_run_rule_engine_max_patterns_respected():
    desc = (
        "Web API with JWT, OAuth, sessions, cookies, SQL, Redis, TLS, admin, "
        "file upload, S3, AWS Lambda, Docker, encryption, RBAC."
    )
    result = run_rule_engine(desc, Framework.STRIDE, max_patterns=5)
    assert len(result.threats) <= 5


# ---------------------------------------------------------------------------
# merge_rule_and_llm_threats
# ---------------------------------------------------------------------------


def test_merge_empty_rule_returns_llm_unchanged():
    llm = ThreatsList(threats=[_make_threat("LLM Threat")])
    rule = ThreatsList(threats=[])
    merged = merge_rule_and_llm_threats(rule, llm)
    assert merged.threats == llm.threats


def test_merge_empty_llm_returns_rule_unchanged():
    rule = ThreatsList(threats=[_make_threat("Rule Threat")])
    llm = ThreatsList(threats=[])
    merged = merge_rule_and_llm_threats(rule, llm)
    assert merged.threats == rule.threats


def test_merge_unique_rule_threats_appended():
    """Completely distinct rule threats are appended after LLM threats."""
    llm_threat = _make_threat(
        name="SQL Injection via user input",
        description="An attacker submitting crafted SQL payloads through the login form can bypass authentication and exfiltrate database records.",
    )
    rule_threat = _make_threat(
        name="DNS Cache Poisoning attack",
        description="A remote attacker with network access can poison DNS resolver caches to redirect legitimate users to malicious servers.",
        category=StrideCategory.SPOOFING,
    )

    llm = ThreatsList(threats=[llm_threat])
    rule = ThreatsList(threats=[rule_threat])

    with patch("backend.db.vectors.embed_text", side_effect=_mock_embed):
        merged = merge_rule_and_llm_threats(rule, llm, threshold=0.85)

    # LLM threats come first; unique rule threat is appended
    assert merged.threats[0].name == llm_threat.name
    assert len(merged.threats) == 2


def test_merge_near_duplicate_rule_threat_dropped():
    """Rule engine threat highly similar to LLM threat is deduplicated out."""
    # Identical threats — cosine similarity will be 1.0, above any threshold
    shared_description = (
        "An attacker with network access can steal authentication credentials "
        "by intercepting unencrypted communication channels to gain unauthorized access."
    )
    llm_threat = _make_threat(name="Credential Theft", description=shared_description)
    rule_threat = _make_threat(name="Credential Theft", description=shared_description)

    llm = ThreatsList(threats=[llm_threat])
    rule = ThreatsList(threats=[rule_threat])

    with patch("backend.db.vectors.embed_text", side_effect=_mock_embed):
        merged = merge_rule_and_llm_threats(rule, llm, threshold=0.85)

    # Identical threat should be deduplicated
    assert len(merged.threats) == 1


# ---------------------------------------------------------------------------
# fetch_rag_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_rag_context_returns_formatted_strings():
    """Successful vector search returns formatted threat strings."""
    mock_results = [
        {
            "threat_id": "abc",
            "name": "Session Hijacking",
            "stride_category": "Spoofing",
            "description": "Attacker intercepts session tokens.",
            "source": "seed",
            "similarity": 0.9,
        }
    ]
    with patch(
        "backend.db.vectors.search_similar_threats",
        new=AsyncMock(return_value=mock_results),
    ):
        result = await fetch_rag_context("web app with sessions", limit=5)

    assert len(result) == 1
    assert "Session Hijacking" in result[0]
    assert "Spoofing" in result[0]


@pytest.mark.asyncio
async def test_fetch_rag_context_empty_results():
    """No matches in vector store returns empty list."""
    with patch(
        "backend.db.vectors.search_similar_threats",
        new=AsyncMock(return_value=[]),
    ):
        result = await fetch_rag_context("system description")

    assert result == []


@pytest.mark.asyncio
async def test_fetch_rag_context_db_error_returns_empty():
    """Any error from the vector store is caught and returns empty list."""
    with patch(
        "backend.db.vectors.search_similar_threats",
        new=AsyncMock(side_effect=RuntimeError("DB not initialized")),
    ):
        result = await fetch_rag_context("system description")

    assert result == []
