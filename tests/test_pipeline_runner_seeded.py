"""Tests for seeded-input support in PipelineRunner (seeded_assets/flows/threats)."""

import pytest

from backend.models.enums import Framework, StrideCategory
from backend.models.state import (
    Asset,
    AssetsList,
    DataFlow,
    FlowsList,
    Threat,
    ThreatsList,
    TrustBoundary,
)
from backend.pipeline.runner import PipelineStep, run_pipeline_for_model
from tests.mock_provider import MockProvider


def _make_threat(
    name: str = "SQL Injection",
    source: str = "llm",
    category: StrideCategory = StrideCategory.TAMPERING,
) -> Threat:
    t = Threat(
        name=name,
        stride_category=category,
        description=(
            "An attacker manipulates SQL queries by injecting malicious input "
            "through unvalidated user-controlled parameters into the database layer."
        ),
        target="Database",
        impact="Data exfiltration or modification",
        likelihood="High",
        mitigations=["Use parameterized queries", "Validate all inputs"],
    )
    t.source = source
    return t


def _make_full_stride_seeds() -> ThreatsList:
    """One seed threat per STRIDE category — exactly balanced coverage."""
    return ThreatsList(
        threats=[
            _make_threat("Seeded Spoofing", category=StrideCategory.SPOOFING),
            _make_threat("Seeded Tampering", category=StrideCategory.TAMPERING),
            _make_threat("Seeded Repudiation", category=StrideCategory.REPUDIATION),
            _make_threat("Seeded Info Disclosure", category=StrideCategory.INFORMATION_DISCLOSURE),
            _make_threat("Seeded Denial of Service", category=StrideCategory.DENIAL_OF_SERVICE),
            _make_threat(
                "Seeded Elevation",
                category=StrideCategory.ELEVATION_OF_PRIVILEGE,
            ),
        ]
    )


def _make_assets() -> AssetsList:
    return AssetsList(
        assets=[Asset(type="Asset", name="WebApp", description="Main web application")]
    )


def _make_flows() -> FlowsList:
    return FlowsList(
        data_flows=[
            DataFlow(flow_description="HTTP", source_entity="User", target_entity="WebApp")
        ],
        trust_boundaries=[
            TrustBoundary(purpose="Internet", source_entity="User", target_entity="WebApp")
        ],
        threat_sources=[],
    )


@pytest.mark.asyncio
async def test_seeded_threats_tagged_as_seeded(mock_provider: MockProvider):
    """Seeded threats must have _source='seeded' after pipeline loads them."""
    seeded = ThreatsList(threats=[_make_threat("Seeded XSS")])
    events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        events.append(event)

    # The seeded threat load event must appear
    info_events = [
        e
        for e in events
        if e.step == PipelineStep.GENERATE_THREATS
        and e.status == "info"
        and e.data
        and e.data.get("seeded_threat_count") == 1
    ]
    assert info_events, "Expected a seeded_threat_count info event"

    # The threat object's _source must be 'seeded'
    assert seeded.threats[0].source == "seeded"


@pytest.mark.asyncio
async def test_seeded_threats_preserved_in_final_catalog(mock_provider: MockProvider):
    """Seeded threats survive the pipeline and appear in the final catalog with source='seeded'."""
    seeded = ThreatsList(threats=[_make_threat("Seeded Known XSS")])

    complete_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API with database",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        if event.step == PipelineStep.COMPLETE and event.status == "completed":
            complete_events.append(event)

    assert complete_events, "Pipeline must emit a COMPLETE event"
    final_threats = complete_events[0].data["threats"].threats
    seeded_in_catalog = [t for t in final_threats if t.source == "seeded"]
    assert seeded_in_catalog, "Seeded threat must appear in the final catalog with source='seeded'"


@pytest.mark.asyncio
async def test_seeded_assets_skips_extraction(mock_provider: MockProvider):
    """When seeded_assets provided, EXTRACT_ASSETS step emits a 'completed' event without 'started'."""
    seeded = _make_assets()
    extract_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_assets=seeded,
    ):
        if event.step == PipelineStep.EXTRACT_ASSETS:
            extract_events.append(event)

    statuses = [e.status for e in extract_events]
    # Should have 'completed' but NOT 'started' (extraction was skipped)
    assert "completed" in statuses
    assert "started" not in statuses


@pytest.mark.asyncio
async def test_seeded_flows_skips_extraction(mock_provider: MockProvider):
    """When seeded_flows provided, EXTRACT_FLOWS step emits 'completed' without 'started'."""
    seeded = _make_flows()
    extract_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_flows=seeded,
    ):
        if event.step == PipelineStep.EXTRACT_FLOWS:
            extract_events.append(event)

    statuses = [e.status for e in extract_events]
    assert "completed" in statuses
    assert "started" not in statuses


@pytest.mark.asyncio
async def test_seeded_threats_message_in_event(mock_provider: MockProvider):
    """The seeded threats load event message must name the count."""
    seeded = ThreatsList(threats=[_make_threat("A"), _make_threat("B")])
    messages = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="API gateway system",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        if event.step == PipelineStep.GENERATE_THREATS and event.status == "info":
            messages.append(event.message)

    assert any("2" in m and "seeded" in m.lower() for m in messages), (
        f"Expected a seeded count message in {messages}"
    )


@pytest.mark.asyncio
async def test_empty_seeded_threats_no_event(mock_provider: MockProvider):
    """Passing an empty ThreatsList as seeded_threats should not emit a seeded event."""
    seeded = ThreatsList(threats=[])
    seeded_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        if (
            event.step == PipelineStep.GENERATE_THREATS
            and event.status == "info"
            and event.data
            and "seeded_threat_count" in event.data
        ):
            seeded_events.append(event)

    assert not seeded_events, "Empty seeded threats should not emit a seeded_threat_count event"


@pytest.mark.asyncio
async def test_saturation_cannot_fire_on_iteration_1(mock_provider: MockProvider):
    """Dedup saturation requires iteration > 1 — a single-iteration run can never be dedup_saturated.

    Regression: before the fix, the saturation guard lacked the `and iteration > 1` clause,
    so a high dedup ratio on iteration 1 (seeds pre-populating cumulative) could stop the
    pipeline prematurely.
    """
    seeded = _make_full_stride_seeds()

    complete_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        if event.step == PipelineStep.COMPLETE and event.status == "completed":
            complete_events.append(event)

    assert complete_events, "Pipeline must emit a COMPLETE event"
    stopped_reason = complete_events[0].data["stopped_reason"]
    assert stopped_reason != "dedup_saturated", (
        f"Saturation fired on iteration 1 — 'and iteration > 1' guard is missing. "
        f"stopped_reason={stopped_reason!r}"
    )


@pytest.mark.asyncio
async def test_balance_gate_excludes_seeded_threats(mock_provider: MockProvider):
    """STRIDE balance gate must evaluate only LLM-generated threats, not seeds.

    Regression: before the fix, _is_stride_coverage_balanced was called against
    cumulative_threats (seeds + LLM). A full-STRIDE seed catalog would appear
    balanced and trigger gap_satisfied on iteration 1 even if the LLM produced nothing.
    """
    seeded = _make_full_stride_seeds()
    # Override LLM to return only TAMPERING threats — unbalanced on its own.
    mock_provider.response_overrides[ThreatsList] = ThreatsList(
        threats=[_make_threat("LLM Tampering Only", category=StrideCategory.TAMPERING)]
    )

    complete_events = []
    async for event in run_pipeline_for_model(
        model_id="test-model",
        description="Simple web API",
        framework=Framework.STRIDE,
        provider=mock_provider,
        max_iterations=1,
        seeded_threats=seeded,
    ):
        if event.step == PipelineStep.COMPLETE and event.status == "completed":
            complete_events.append(event)

    assert complete_events, "Pipeline must emit a COMPLETE event"
    stopped_reason = complete_events[0].data["stopped_reason"]
    # Balance gate must not fire: LLM output is TAMPERING-only (not balanced).
    # If it fires, the balance gate counted seeds instead of LLM-only threats.
    assert stopped_reason != "gap_satisfied", (
        f"Balance gate fired against seeds — filter by source!='seeded' is missing. "
        f"stopped_reason={stopped_reason!r}"
    )
