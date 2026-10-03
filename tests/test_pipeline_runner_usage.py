"""Tests for pipeline runner usage accounting (week 4a-1).

Covers: usage attached to each instrumented step's PipelineEvent, the final
COMPLETE event's rolled-up RunUsage, the fast-model token share, and the
pipeline_runs audit rows — written only when the caller opts in
(`persist_usage=True`, since `pipeline_runs.model_id` has a foreign key to
threat_models and the CLI's run id is never a saved row until after the
pipeline finishes) *and* a DB connection is already up (see
backend/db/connection.py's ConnectionManager.is_initialized).
"""

import pytest

from backend.models.enums import Framework
from backend.models.usage import UsageRecord
from backend.pipeline.runner import PipelineConfig, PipelineRunner, PipelineStep
from backend.providers.usage import record_usage
from tests.mock_provider import MockProvider


class UsageMockProvider(MockProvider):
    """MockProvider that also records token usage, like a real provider does."""

    def __init__(self, model: str = "mock-v1", tokens_per_call: int = 100, **kwargs) -> None:
        super().__init__(**kwargs)
        self._usage_model = model
        self._tokens_per_call = tokens_per_call

    @property
    def model(self) -> str:
        return self._usage_model

    async def generate_structured(self, *args, **kwargs):
        result = await super().generate_structured(*args, **kwargs)
        record_usage(
            UsageRecord(
                provider=self.name,
                model=self._usage_model,
                input_tokens=self._tokens_per_call,
                output_tokens=self._tokens_per_call // 2,
            )
        )
        return result


async def _collect_events(runner: PipelineRunner, description: str, framework: Framework):
    events = []
    async for event in runner.run(description=description, framework=framework):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_each_instrumented_step_attaches_model_and_usage():
    provider = UsageMockProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-usage-1")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    instrumented_steps = {
        PipelineStep.SUMMARIZE,
        PipelineStep.EXTRACT_ASSETS,
        PipelineStep.EXTRACT_FLOWS,
        PipelineStep.GENERATE_THREATS,
    }
    completed = [e for e in events if e.status == "completed" and e.step in instrumented_steps]
    assert completed, "expected at least one completed instrumented-step event"

    for event in completed:
        assert event.data.get("model") == "mock-v1"
        usage = event.data.get("usage")
        assert usage, f"{event.step} completed event missing usage"
        assert usage[0]["model"] == "mock-v1"
        assert usage[0]["input_tokens"] == 100
        assert usage[0]["output_tokens"] == 50
        assert usage[0]["total_tokens"] == 150


@pytest.mark.asyncio
async def test_complete_event_rolls_up_run_usage_with_no_fast_model():
    provider = UsageMockProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-usage-2")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    complete = events[-1]
    assert complete.step == PipelineStep.COMPLETE

    usage = complete.data["usage"]
    assert usage["fast_model"] is None
    assert usage["fast_model_share"] is None
    assert usage["total_tokens"] > 0
    assert len(usage["by_model"]) == 1
    assert usage["by_model"][0]["model"] == "mock-v1"
    # summarize + extract_assets + extract_flows + generate_threats = 4 calls,
    # single framework, single iteration, gap analysis skipped (threshold=1
    # makes the very first gap call stop, but it never runs here since
    # max_iterations=1 skips gap analysis on the final iteration).
    assert usage["by_model"][0]["calls"] == 4


@pytest.mark.asyncio
async def test_fast_model_share_computed_when_fast_provider_distinct():
    main_provider = UsageMockProvider(model="main-v1", tokens_per_call=100, gap_call_threshold=1)
    fast_provider = UsageMockProvider(model="fast-v1", tokens_per_call=40, gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider,
        fast_provider=fast_provider,
        config=config,
        model_id="test-usage-fast",
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    complete = events[-1]
    usage = complete.data["usage"]

    assert usage["fast_model"] == "fast-v1"
    by_model = {m["model"]: m for m in usage["by_model"]}
    # extract_assets + extract_flows run on the fast provider: 2 calls * 60 tokens.
    assert by_model["fast-v1"]["total_tokens"] == 120
    # summarize + generate_threats run on the main provider: 2 calls * 150 tokens.
    assert by_model["main-v1"]["total_tokens"] == 300
    assert usage["fast_model_tokens"] == 120
    assert usage["total_tokens"] == 420
    # build_run_usage() rounds the share to 4 decimals — compare against that,
    # not the exact fraction.
    assert usage["fast_model_share"] == round(120 / 420, 4)


@pytest.mark.asyncio
async def test_fast_model_share_omitted_when_fast_and_main_models_share_a_name():
    """A distinct fast *provider* whose model identifier happens to match the
    main provider's must not report a 100% fast-model share — the two
    providers would be indistinguishable in the by-model token breakdown.
    Today's fast-provider builders never pair same-named models; this guards
    the case so a future builder change can't silently produce it."""
    main_provider = UsageMockProvider(model="same-v1", tokens_per_call=100, gap_call_threshold=1)
    fast_provider = UsageMockProvider(model="same-v1", tokens_per_call=40, gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider,
        fast_provider=fast_provider,
        config=config,
        model_id="test-usage-same-name",
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    usage = events[-1].data["usage"]

    assert usage["fast_model"] is None
    assert usage["fast_model_share"] is None
    assert usage["fast_model_tokens"] == 0
    # The tokens themselves are still all accounted for under the shared name.
    assert usage["by_model"][0]["model"] == "same-v1"
    assert usage["total_tokens"] == 420


@pytest.mark.asyncio
async def test_pipeline_runs_audit_row_written_when_opted_in_and_db_initialized(test_db):
    from backend.db import crud

    model_id = await crud.create_threat_model("Usage Test", "Desc", "mock", "mock-v1")
    provider = UsageMockProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1)
    runner = PipelineRunner(provider=provider, config=config, model_id=model_id, persist_usage=True)

    await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    rows = await crud.list_pipeline_runs(model_id)
    assert len(rows) >= 4  # summarize, extract_assets, extract_flows, generate_threats
    summarize_rows = [r for r in rows if r["step"] == "summarize"]
    assert len(summarize_rows) == 1
    row = summarize_rows[0]
    assert row["model"] == "mock-v1"
    assert row["input_tokens"] == 100
    assert row["output_tokens"] == 50
    assert row["tokens_used"] == 150


@pytest.mark.asyncio
async def test_no_audit_row_written_without_opting_in(test_db):
    """persist_usage defaults to False — this is the CLI's case, whose run id
    is never a saved threat_models row until after the pipeline finishes. A
    runner that doesn't opt in must not attempt the write at all (not just
    swallow a FOREIGN KEY failure), even when a DB connection is up."""
    from backend.db import crud

    model_id = await crud.create_threat_model("Usage Test", "Desc", "mock", "mock-v1")
    provider = UsageMockProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1)
    runner = PipelineRunner(provider=provider, config=config, model_id=model_id)
    assert runner.persist_usage is False

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    assert events[-1].step == PipelineStep.COMPLETE
    assert events[-1].data["usage"]["total_tokens"] > 0
    assert await crud.list_pipeline_runs(model_id) == []


@pytest.mark.asyncio
async def test_no_audit_row_written_without_an_initialized_db_connection():
    """Even an opted-in runner must not open the real on-disk database as a
    side effect when nothing has initialized a connection yet (RAG off here —
    the pre-existing RAG project-id lookup has its own, unrelated, lazy-init
    call). Force-resets ConnectionManager state so this is order-independent:
    an earlier test in the same session may have already initialized the
    singleton via its own test_db fixture or the RAG path."""
    from backend.db.connection import db

    previous = (db._connection, db._db_path, db._initialized, db._reader_pool)
    db._connection, db._db_path, db._initialized, db._reader_pool = None, None, False, None
    try:
        provider = UsageMockProvider(gap_call_threshold=1)
        config = PipelineConfig(max_iterations=1, enable_rag=False)
        runner = PipelineRunner(
            provider=provider, config=config, model_id="test-no-db", persist_usage=True
        )

        events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

        # The run still completes and still reports usage in events —
        # persistence is the only thing skipped.
        assert events[-1].step == PipelineStep.COMPLETE
        assert events[-1].data["usage"]["total_tokens"] > 0
        assert not db.is_initialized
    finally:
        db._connection, db._db_path, db._initialized, db._reader_pool = previous


@pytest.mark.asyncio
async def test_usage_recorded_even_when_provider_fails_after_auto_bump_attempts():
    """A step that ultimately raises ProviderError still billed its attempts —
    the failed StepRun must carry whatever usage was recorded before the
    failure, not an empty list."""

    class FlakyProvider(UsageMockProvider):
        async def generate_structured(self, *args, **kwargs):
            # Record usage as if an attempt was billed, then fail — mirrors a
            # real provider's auto-bump retry exhausting without success.
            record_usage(UsageRecord(provider=self.name, model=self.model, input_tokens=100))
            from backend.providers.base import ProviderError

            raise ProviderError(provider=self.name, message="simulated exhaustion")

    provider = FlakyProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-usage-fail")

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    # Pipeline degrades to rule-engine-only mode rather than raising.
    assert events[-1].step == PipelineStep.COMPLETE
    failed_steps = [s for s in runner._step_runs if s.status == "failed"]
    assert failed_steps, "expected at least one failed StepRun"
    assert failed_steps[0].usage
    assert failed_steps[0].usage[0].input_tokens == 100


@pytest.mark.asyncio
async def test_usage_recorded_for_a_non_provider_error_too():
    """A cancellation or timeout isn't a ProviderError, but still billed
    whatever the provider had already recorded before it propagated —
    _instrument's `finally` must catch every exception type, not just
    ProviderError."""

    class CancelledMidCallProvider(UsageMockProvider):
        async def generate_structured(self, *args, **kwargs):
            record_usage(UsageRecord(provider=self.name, model=self.model, input_tokens=77))
            raise TimeoutError("simulated request timeout")

    provider = CancelledMidCallProvider(gap_call_threshold=1)
    config = PipelineConfig(max_iterations=1, enable_rag=False)
    runner = PipelineRunner(provider=provider, config=config, model_id="test-usage-timeout")

    # The runner's own try/except only degrades gracefully for ProviderError;
    # a TimeoutError propagates all the way out of run() as a genuine failure.
    # That's expected — the point here is only that the StepRun was recorded
    # before it propagated.
    with pytest.raises(TimeoutError):
        await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    failed_steps = [s for s in runner._step_runs if s.status == "failed"]
    assert failed_steps, "expected a failed StepRun even for a non-ProviderError exception"
    assert failed_steps[0].usage
    assert failed_steps[0].usage[0].input_tokens == 77
