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
async def test_persist_saves_usage_summary(test_db):
    """The COMPLETE event's RunUsage dict round-trips to usage_summary — the
    CLI's path to a model getting a Results-page "Run summary" card, since
    the CLI's pipeline_runs audit rows are skipped entirely (its run id
    isn't a saved threat_models row until this very call)."""
    import json

    usage = {
        "steps": [],
        "by_model": [
            {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "calls": 4,
                "input_tokens": 300,
                "output_tokens": 100,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 400,
            }
        ],
        "total_tokens": 400,
        "fast_model": None,
        "fast_model_tokens": 0,
        "fast_model_share": None,
    }
    model_id = await persist_pipeline_result(
        title="usage_run",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-5",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
        usage_summary=usage,
    )

    model = await crud.get_threat_model(model_id)
    assert json.loads(model["usage_summary"]) == usage


@pytest.mark.asyncio
async def test_persist_handles_none_usage_summary(test_db):
    """No usage_summary passed (e.g. the pipeline failed before any step
    completed) leaves the column unset rather than writing a null/empty
    JSON blob the frontend would have to special-case."""
    model_id = await persist_pipeline_result(
        title="no_usage_run",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-5",
        framework=Framework.STRIDE,
        iterations_completed=0,
        assets=None,
        flows=None,
        threats=None,
    )

    model = await crud.get_threat_model(model_id)
    assert model["usage_summary"] is None


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


# ---------------------------------------------------------------------------
# Dependency provenance persistence (Week 3)
# ---------------------------------------------------------------------------


def _make_dependency_threats() -> ThreatsList:
    from backend.models.state import DependencyRef

    return ThreatsList(
        threats=[
            Threat(
                name="Dynamic code loading in evil-pkg@1.0.0",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    "evil-pkg@1.0.0 loads or evaluates code modules it does not statically "
                    "declare, which can be used to load a payload at runtime that static "
                    "analysis of the package won't see."
                ),
                target="evil-pkg@1.0.0",
                impact="Medium",
                likelihood="Medium",
                mitigations=["Pin the exact version", "Review the capability diff"],
                source="dependency",
                dependency_ref=DependencyRef(
                    package="evil-pkg",
                    version="1.0.0",
                    file="index.js",
                    line=12,
                    rule_id="dynamic_code",
                ),
            ),
        ]
    )


def _make_dependency_context():
    from backend.models.dependencies import (
        CapabilityProfile,
        DependencyContext,
        PackageAnalysis,
        PackageRef,
        ResolvedPackage,
    )
    from backend.models.enums import SourceKind

    profile = CapabilityProfile(
        name="evil-pkg", version="1.0.0", source_kind=SourceKind.NPM_TARBALL, status="ok"
    )
    pa = PackageAnalysis(
        ref=PackageRef(name="evil-pkg", version="1.0.0"),
        resolved=ResolvedPackage(
            name="evil-pkg", version="1.0.0", tarball_url="https://x", integrity="sha512-x"
        ),
        npm_profile=profile,
    )
    return DependencyContext(packages=[pa], source_mode="npm")


@pytest.mark.asyncio
async def test_persist_saves_threat_dependency_ref(test_db):
    """A threat's dependency_ref round-trips through persistence as JSON."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_dependency_threats(),
    )

    threats = await crud.list_threats(model_id)
    assert len(threats) == 1
    threat = threats[0]
    assert threat["source"] == "dependency"
    assert threat["dependency_ref"] == {
        "package": "evil-pkg",
        "version": "1.0.0",
        "file": "index.js",
        "line": 12,
        "rule_id": "dynamic_code",
    }


@pytest.mark.asyncio
async def test_persist_llm_threat_has_no_dependency_ref(test_db):
    """An ordinary LLM threat's dependency_ref stays None/absent."""
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
    assert all(not t.get("dependency_ref") for t in threats)


def _make_technique_mapped_threats() -> ThreatsList:
    from backend.models.state import TechniqueRef

    return ThreatsList(
        threats=[
            Threat(
                name="Compromise Software Supply Chain",
                stride_category=StrideCategory.TAMPERING,
                description=(
                    "A tarball-only file in evil-pkg@1.0.0 ships code not present in its "
                    "public source repository, indicating possible supply-chain tampering."
                ),
                target="evil-pkg@1.0.0",
                impact="High",
                likelihood="Medium",
                mitigations=["Pin the exact version", "Review the capability diff"],
                attack_techniques=[
                    TechniqueRef(
                        id="T1195.002",
                        name="Compromise Software Supply Chain",
                        url="https://attack.mitre.org/techniques/T1195/002",
                        confidence=0.9,
                        method="table",
                    )
                ],
            ),
        ]
    )


@pytest.mark.asyncio
async def test_persist_saves_threat_attack_techniques(test_db):
    """A threat's attack_techniques round-trips through persistence as JSON."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=_make_technique_mapped_threats(),
    )

    threats = await crud.list_threats(model_id)
    assert len(threats) == 1
    assert threats[0]["attack_techniques"] == [
        {
            "id": "T1195.002",
            "name": "Compromise Software Supply Chain",
            "url": "https://attack.mitre.org/techniques/T1195/002",
            "confidence": 0.9,
            "method": "table",
        }
    ]


@pytest.mark.asyncio
async def test_persist_threat_with_no_techniques_matched(test_db):
    """A threat with no technique matches stores an empty/absent column, not a crash."""
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
    assert all(not t.get("attack_techniques") for t in threats)


@pytest.mark.asyncio
async def test_persist_saves_dependency_scans(test_db):
    """dependency_context packages are persisted to dependency_scans."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
        dependency_context=_make_dependency_context(),
    )

    scans = await crud.list_dependency_scans(model_id)
    assert len(scans) == 1
    assert scans[0]["package"] == "evil-pkg"
    assert scans[0]["version"] == "1.0.0"
    assert scans[0]["source_mode"] == "npm"
    assert scans[0]["analysis"]["resolved"]["name"] == "evil-pkg"


@pytest.mark.asyncio
async def test_persist_no_dependency_context_saves_no_scans(test_db):
    """When dependency_context is None, dependency_scans stays empty."""
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
    )

    assert await crud.list_dependency_scans(model_id) == []


@pytest.mark.asyncio
async def test_persist_saves_errored_package_by_ref(test_db):
    """A package that failed resolution (pa.resolved is None) is still saved,
    using pa.ref's name/version, so the UI can show why it's missing rather
    than dropping it silently."""
    from backend.models.dependencies import DependencyContext, PackageAnalysis, PackageRef

    pa = PackageAnalysis(
        ref=PackageRef(name="left-pad", version="1.0.0"),
        resolved=None,
        error="no resolvable version",
    )
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
        dependency_context=DependencyContext(packages=[pa], source_mode="npm"),
    )

    scans = await crud.list_dependency_scans(model_id)
    assert len(scans) == 1
    assert scans[0]["package"] == "left-pad"
    assert scans[0]["version"] == "1.0.0"
    assert scans[0]["analysis"]["error"] == "no resolvable version"


@pytest.mark.asyncio
async def test_persist_saves_skipped_dependencies(test_db):
    """Dependencies dropped before analysis ever ran (skipped: no resolvable
    pinned version, or over the manifest size cap) are persisted too, so
    every declared dependency shows up somewhere in the UI."""
    from backend.models.dependencies import DependencyContext

    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
        dependency_context=DependencyContext(
            packages=[], source_mode="npm", skipped={"too-many-deps": "manifest size cap exceeded"}
        ),
    )

    scans = await crud.list_dependency_scans(model_id)
    assert len(scans) == 1
    assert scans[0]["package"] == "too-many-deps"
    assert scans[0]["version"] == ""
    # skip_reason (never analyzed), not error (analysis attempted and failed)
    assert scans[0]["analysis"]["skip_reason"] == "manifest size cap exceeded"
    assert "error" not in scans[0]["analysis"]


@pytest.mark.asyncio
async def test_persist_caps_skipped_dependency_rows(test_db):
    """A manifest crafted with thousands of bogus dependency keys must not
    turn into thousands of dependency_scans rows — capped at
    MAX_SKIPPED_DEPENDENCY_ROWS, with one summary row for the rest."""
    from backend.deps.analyze import MAX_SKIPPED_DEPENDENCY_ROWS
    from backend.models.dependencies import DependencyContext

    skipped = {
        f"pkg-{i}": "unresolvable_version_range" for i in range(MAX_SKIPPED_DEPENDENCY_ROWS + 10)
    }
    model_id = await persist_pipeline_result(
        title="test",
        description="desc",
        provider="anthropic",
        model_name="claude-sonnet-4",
        framework=Framework.STRIDE,
        iterations_completed=1,
        assets=None,
        flows=None,
        threats=None,
        dependency_context=DependencyContext(packages=[], source_mode="npm", skipped=skipped),
    )

    scans = await crud.list_dependency_scans(model_id)
    assert len(scans) == MAX_SKIPPED_DEPENDENCY_ROWS + 1
    summary = [s for s in scans if s["package"] == "+10 more skipped"]
    assert len(summary) == 1
    assert "10 additional" in summary[0]["analysis"]["skip_reason"]
