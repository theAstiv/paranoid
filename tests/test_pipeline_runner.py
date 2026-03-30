"""Tests for pipeline runner (backend/pipeline/runner.py).

Full pipeline integration tests using MockProvider — no API tokens needed.
Collects events from the async generator and asserts step ordering and data.
"""

import pytest

from backend.models.enums import Framework
from backend.models.state import ThreatsList
from backend.pipeline.runner import (
    PipelineConfig,
    PipelineEvent,
    PipelineRunner,
    PipelineStep,
    run_pipeline_for_model,
)
from backend.providers.base import ProviderError
from tests.mock_provider import MockProvider


async def _collect_events(
    runner: PipelineRunner,
    description: str,
    framework: Framework,
) -> list[PipelineEvent]:
    """Helper to collect all events from a pipeline run."""
    events = []
    async for event in runner.run(description=description, framework=framework):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_runner_single_iteration_emits_all_steps():
    """Single iteration should emit: summarize, extract_assets, extract_flows,
    generate_threats, complete (no gap_analysis on final iteration)."""
    provider = MockProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-1")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    step_statuses = [(e.step, e.status) for e in events]

    # Must have started+completed for summarize, assets, flows, threats
    assert (PipelineStep.SUMMARIZE, "started") in step_statuses
    assert (PipelineStep.SUMMARIZE, "completed") in step_statuses
    assert (PipelineStep.EXTRACT_ASSETS, "started") in step_statuses
    assert (PipelineStep.EXTRACT_ASSETS, "completed") in step_statuses
    assert (PipelineStep.EXTRACT_FLOWS, "started") in step_statuses
    assert (PipelineStep.EXTRACT_FLOWS, "completed") in step_statuses
    assert (PipelineStep.GENERATE_THREATS, "started") in step_statuses
    assert (PipelineStep.GENERATE_THREATS, "completed") in step_statuses

    # Must end with COMPLETE
    assert events[-1].step == PipelineStep.COMPLETE
    assert events[-1].status == "completed"

    # No gap analysis on single iteration
    gap_events = [e for e in events if e.step == PipelineStep.GAP_ANALYSIS]
    assert len(gap_events) == 0


@pytest.mark.asyncio
async def test_runner_three_iterations():
    """Three iterations: threat gen + gap analysis on iters 1-2, just threat gen on iter 3."""
    provider = MockProvider(gap_call_threshold=10)  # Never auto-stop
    config = PipelineConfig(max_iterations=3)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-3iter")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    # Should have gap analysis events for iterations 1 and 2
    gap_events = [
        e for e in events if e.step == PipelineStep.GAP_ANALYSIS and e.status == "completed"
    ]
    assert len(gap_events) == 2

    # Should have threat generation events for all 3 iterations
    threat_events = [
        e for e in events if e.step == PipelineStep.GENERATE_THREATS and e.status == "completed"
    ]
    assert len(threat_events) == 3

    # Complete event has total_threats > 0
    complete = events[-1]
    assert complete.step == PipelineStep.COMPLETE
    assert complete.data["total_threats"] > 0
    assert complete.data["iterations_completed"] == 3


@pytest.mark.asyncio
async def test_runner_stops_on_gap_satisfied():
    """Runner should stop early when gap analysis returns stop=True."""
    provider = MockProvider(gap_call_threshold=1)  # Stop after 1st gap call
    config = PipelineConfig(max_iterations=5)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-early-stop")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    complete = events[-1]
    assert complete.step == PipelineStep.COMPLETE
    assert complete.data["stopped_reason"] == "gap_satisfied"
    assert complete.data["iterations_completed"] == 1

    # Should have exactly 1 gap analysis (the one that stopped)
    gap_events = [e for e in events if e.step == PipelineStep.GAP_ANALYSIS]
    assert len(gap_events) > 0


@pytest.mark.asyncio
async def test_runner_dual_framework():
    """Dual framework mode should generate both STRIDE and MAESTRO threats."""
    provider = MockProvider(gap_call_threshold=10)
    config = PipelineConfig(max_iterations=1, has_ai_components=True)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-dual")

    events = await _collect_events(runner, "An AI document classifier", Framework.STRIDE)

    # In dual mode, should see multiple GENERATE_THREATS completed events
    # (STRIDE + MAESTRO)
    threat_completed = [
        e for e in events if e.step == PipelineStep.GENERATE_THREATS and e.status == "completed"
    ]
    assert len(threat_completed) >= 2  # At least STRIDE + MAESTRO

    # Check that we got a "COMBINED" info event or dedup event
    threat_info = [
        e for e in events if e.step == PipelineStep.GENERATE_THREATS and e.status == "info"
    ]
    assert len(threat_info) > 0

    complete = events[-1]
    assert complete.data["total_threats"] > 0


@pytest.mark.asyncio
async def test_runner_emits_threat_count_in_events():
    """Threat generation completed events should include threat_count."""
    provider = MockProvider()
    config = PipelineConfig(max_iterations=1)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-count")

    events = await _collect_events(runner, "A web app", Framework.STRIDE)

    threat_completed = [
        e for e in events if e.step == PipelineStep.GENERATE_THREATS and e.status == "completed"
    ]
    assert len(threat_completed) > 0
    for e in threat_completed:
        assert "threat_count" in e.data
        assert e.data["threat_count"] > 0


@pytest.mark.asyncio
async def test_runner_handles_provider_error():
    """Provider error during pipeline should yield a failed COMPLETE event."""
    provider = MockProvider()
    provider.error_types.add(ThreatsList)  # Fail on threat generation
    config = PipelineConfig(max_iterations=1)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-error")

    with pytest.raises(ProviderError):
        await _collect_events(runner, "A web app", Framework.STRIDE)


@pytest.mark.asyncio
async def test_run_pipeline_for_model_convenience():
    """Convenience function should yield events like the runner."""
    provider = MockProvider(gap_call_threshold=1)
    events = []
    async for event in run_pipeline_for_model(
        model_id="convenience-test",
        description="A document sharing web app",
        framework=Framework.STRIDE,
        provider=provider,
        max_iterations=1,
    ):
        events.append(event)

    assert len(events) > 0
    assert events[-1].step == PipelineStep.COMPLETE
    assert events[-1].status == "completed"
