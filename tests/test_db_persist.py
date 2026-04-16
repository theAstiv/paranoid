"""Tests for backend/db/persist.py — pipeline result persistence.

Uses the shared test_db fixture (fresh SQLite per test, no sqlite-vec extension).
All tests verify data round-trips correctly through persist_pipeline_result()
into the underlying CRUD layer.
"""

import pytest

from backend.db import crud
from backend.db.persist import persist_pipeline_result
from backend.models.enums import AssetType, Framework, StrideCategory
from backend.models.state import (
    Asset,
    AssetsList,
    DataFlow,
    DreadScore,
    FlowsList,
    Threat,
    ThreatsList,
    ThreatSource,
    TrustBoundary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_assets() -> AssetsList:
    return AssetsList(
        assets=[
            Asset(type=AssetType.ASSET, name="PostgreSQL DB", description="Primary database"),
            Asset(type=AssetType.ENTITY, name="Admin User", description="Internal admin"),
        ]
    )


def _make_flows() -> FlowsList:
    return FlowsList(
        data_flows=[
            DataFlow(
                flow_description="API reads user records",
                source_entity="REST API",
                target_entity="PostgreSQL DB",
            )
        ],
        trust_boundaries=[
            TrustBoundary(
                purpose="Separates public internet from internal services",
                source_entity="Public Internet",
                target_entity="API Gateway",
            )
        ],
        threat_sources=[
            ThreatSource(
                category="External Attacker",
                description="Unauthenticated threat actor with internet access",
                example="Script kiddie exploiting known CVEs",
            )
        ],
    )


def _make_threats(with_dread: bool = False) -> ThreatsList:
    dread = (
        DreadScore(
            damage=7.5,
            reproducibility=5.0,
            exploitability=5.0,
            affected_users=7.5,
            discoverability=5.0,
        )
        if with_dread
        else None
    )
    return ThreatsList(
        threats=[
            Threat(
                name="SQL Injection",
                stride_category=StrideCategory.TAMPERING,
                description="An attacker with access to user input fields can inject malicious SQL bypassing authentication and exfiltrating database records.",
                target="PostgreSQL DB",
                impact="High",
                likelihood="Medium",
                dread=dread,
                mitigations=["Use parameterized queries", "Apply input validation"],
            ),
            Threat(
                name="Session Hijacking",
                stride_category=StrideCategory.SPOOFING,
                description="A network attacker can intercept session tokens over unencrypted channels and impersonate authenticated users to access protected resources.",
                target="REST API",
                impact="High",
                likelihood="Low",
                mitigations=["Enforce TLS", "Use short-lived tokens"],
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Core persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_returns_valid_model_id(test_db):
    """persist_pipeline_result() returns a non-empty string model_id."""
    model_id = await persist_pipeline_result(
        title="test_system",
        description="A simple test system",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_threats(),
    )
    assert model_id is not None
    assert len(model_id) > 0


@pytest.mark.asyncio
async def test_persist_creates_threat_model_record(test_db):
    """A threat_model row is created with correct fields."""
    model_id = await persist_pipeline_result(
        title="my_system",
        description="System under analysis",
        provider="openai",
        model_name="gpt-4o",
        framework=Framework.STRIDE,
        iterations_completed=3,
        assets=None,
        flows=None,
        threats=_make_threats(),
    )

    model = await crud.get_threat_model(model_id)
    assert model is not None
    assert model["title"] == "my_system"
    assert model["description"] == "System under analysis"
    assert model["provider"] == "openai"
    assert model["framework"] == "STRIDE"
    assert model["iteration_count"] == 3


@pytest.mark.asyncio
async def test_persist_sets_status_completed(test_db):
    """Model status is set to 'completed' after all data is written."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_threats(),
    )

    model = await crud.get_threat_model(model_id)
    assert model["status"] == "completed"


@pytest.mark.asyncio
async def test_persist_saves_assets(test_db):
    """Assets are persisted with correct type, name, and description."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=_make_assets(),
        flows=None,
        threats=_make_threats(),
    )

    assets = await crud.list_assets(model_id)
    assert len(assets) == 2
    names = {a["name"] for a in assets}
    assert "PostgreSQL DB" in names
    assert "Admin User" in names


@pytest.mark.asyncio
async def test_persist_saves_data_flows(test_db):
    """Data flows are persisted with flow_type='data'."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=_make_flows(),
        threats=_make_threats(),
    )

    flows = await crud.list_flows(model_id)
    data_flows = [f for f in flows if f["flow_type"] == "data"]
    assert len(data_flows) == 1
    assert data_flows[0]["source_entity"] == "REST API"
    assert data_flows[0]["target_entity"] == "PostgreSQL DB"
    assert data_flows[0]["flow_description"] == "API reads user records"


@pytest.mark.asyncio
async def test_persist_saves_trust_boundaries(test_db):
    """Trust boundaries are persisted to the trust_boundaries table (not flows)."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=_make_flows(),
        threats=_make_threats(),
    )

    boundaries = await crud.list_trust_boundaries(model_id)
    assert len(boundaries) == 1
    assert boundaries[0]["source_entity"] == "Public Internet"
    assert boundaries[0]["target_entity"] == "API Gateway"
    assert "internal services" in boundaries[0]["purpose"]

    # Confirm trust boundaries are NOT stored as flows
    flows = await crud.list_flows(model_id)
    assert all(f["flow_type"] != "trust_boundary" for f in flows)


@pytest.mark.asyncio
async def test_persist_saves_threat_sources(test_db):
    """Threat sources (actors) are persisted correctly."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=_make_flows(),
        threats=_make_threats(),
    )

    sources = await crud.list_threat_sources(model_id)
    assert len(sources) == 1
    assert sources[0]["category"] == "External Attacker"
    assert "internet access" in sources[0]["description"]


@pytest.mark.asyncio
async def test_persist_saves_threats_with_mitigations(test_db):
    """Threats and their mitigations round-trip correctly through JSON serialisation."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_threats(),
    )

    threats = await crud.list_threats(model_id)
    assert len(threats) == 2
    names = {t["name"] for t in threats}
    assert "SQL Injection" in names
    assert "Session Hijacking" in names

    sql_threat = next(t for t in threats if t["name"] == "SQL Injection")
    assert sql_threat["stride_category"] == "Tampering"
    assert sql_threat["status"] == "pending"
    assert "Use parameterized queries" in sql_threat["mitigations"]


@pytest.mark.asyncio
async def test_persist_saves_individual_dread_fields(test_db):
    """All 5 individual DREAD fields and the aggregate score are stored."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_threats(with_dread=True),
    )

    threats = await crud.list_threats(model_id)
    dread_threat = next(t for t in threats if t["name"] == "SQL Injection")

    assert dread_threat["dread_damage"] == 7.5
    assert dread_threat["dread_reproducibility"] == 5.0
    assert dread_threat["dread_exploitability"] == 5.0
    assert dread_threat["dread_affected_users"] == 7.5
    assert dread_threat["dread_discoverability"] == 5.0
    # Aggregate = (7.5 + 5 + 5 + 7.5 + 5) / 5 = 6.0
    assert dread_threat["dread_score"] == pytest.approx(6.0)

    # Threat without DREAD should have NULL scores
    no_dread = next(t for t in threats if t["name"] == "Session Hijacking")
    assert no_dread["dread_score"] is None
    assert no_dread["dread_damage"] is None


@pytest.mark.asyncio
async def test_persist_handles_none_assets_flows_threats(test_db):
    """None inputs are handled gracefully — only threat_model row is created."""
    model_id = await persist_pipeline_result(
        title="partial_run",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=0,
        assets=None,
        flows=None,
        threats=None,
    )

    # Model still created
    assert model_id is not None
    model = await crud.get_threat_model(model_id)
    assert model is not None

    # Child tables empty
    assert await crud.list_assets(model_id) == []
    assert await crud.list_flows(model_id) == []
    assert await crud.list_threats(model_id) == []


@pytest.mark.asyncio
async def test_persist_returns_none_on_db_failure(test_db):
    """Non-fatal wrapper returns None (not raises) when DB operation fails."""
    from backend.db.connection import db

    await db.close()
    # Force the "initialized but no connection" state so db.get() raises
    # RuntimeError immediately, bypassing lazy re-init (which would otherwise
    # succeed now that sqlite_vec.loadable_path() loads the extension correctly).
    db._initialized = True

    result = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_threats(),
    )

    assert result is None
