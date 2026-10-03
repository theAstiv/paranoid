"""Tests for backend/providers/usage.py — the usage-accounting contextvar collector.

Exercises the collector in isolation (record_usage/collect_usage/summarize_usage/
build_run_usage) rather than through a live provider call, since the four real
providers are covered by their own call-shape tests; this file is about the
accounting math itself.
"""

from backend.models.usage import ModelUsage, StepRun, UsageRecord
from backend.providers.usage import (
    as_token_count,
    build_run_usage,
    collect_usage,
    record_usage,
    summarize_usage,
)


def test_as_token_count_coerces_missing_and_non_numeric_to_zero():
    assert as_token_count(None) == 0
    assert as_token_count("not a number") == 0
    assert as_token_count(True) == 0  # bool is an int subclass — must not leak through as 1
    assert as_token_count(42) == 42
    assert as_token_count(3.7) == 3
    assert as_token_count(-5) == 0  # negative counts never come from a real API; clamp defensively


def test_record_usage_outside_any_scope_is_a_noop():
    # No collect_usage() open — must not raise, must not leak into a later scope.
    record_usage(UsageRecord(provider="anthropic", model="claude-sonnet-5", input_tokens=10))
    with collect_usage() as records:
        pass
    assert records == []


def test_collect_usage_scopes_to_the_with_block():
    with collect_usage() as records:
        record_usage(UsageRecord(provider="anthropic", model="claude-sonnet-5", input_tokens=10))
        record_usage(UsageRecord(provider="anthropic", model="claude-sonnet-5", output_tokens=5))
    assert len(records) == 2

    # A second, later scope starts empty — no leakage from the first.
    with collect_usage() as records2:
        pass
    assert records2 == []


def test_collect_usage_records_survive_a_raised_exception():
    # A provider auto-bump retry that ultimately raises ProviderError still
    # billed every attempt — those records must not be lost.
    records_seen = None
    try:
        with collect_usage() as records:
            record_usage(UsageRecord(provider="openai", model="gpt-4.1-mini", input_tokens=7))
            records_seen = records
            raise ValueError("simulated provider failure")
    except ValueError:
        pass
    assert records_seen is not None
    assert len(records_seen) == 1


def test_summarize_usage_sums_per_provider_model_pair():
    records = [
        UsageRecord(
            provider="anthropic", model="claude-sonnet-5", input_tokens=100, output_tokens=20
        ),
        UsageRecord(
            provider="anthropic", model="claude-sonnet-5", input_tokens=50, output_tokens=10
        ),
        UsageRecord(
            provider="anthropic", model="claude-haiku-4-5", input_tokens=30, output_tokens=5
        ),
    ]
    totals = summarize_usage(records)
    by_model = {m.model: m for m in totals}

    assert by_model["claude-sonnet-5"].calls == 2
    assert by_model["claude-sonnet-5"].input_tokens == 150
    assert by_model["claude-sonnet-5"].output_tokens == 30
    assert by_model["claude-sonnet-5"].total_tokens == 180

    assert by_model["claude-haiku-4-5"].calls == 1
    assert by_model["claude-haiku-4-5"].total_tokens == 35


def test_summarize_usage_preserves_first_seen_order():
    records = [
        UsageRecord(provider="a", model="m2", input_tokens=1),
        UsageRecord(provider="a", model="m1", input_tokens=1),
        UsageRecord(provider="a", model="m2", input_tokens=1),
    ]
    totals = summarize_usage(records)
    assert [m.model for m in totals] == ["m2", "m1"]


def test_summarize_usage_accepts_already_summed_model_usage_rows():
    # Step totals (ModelUsage) rolling up into a run total — calls must add,
    # not reset to 1 per row.
    rows = [
        ModelUsage(provider="anthropic", model="claude-sonnet-5", calls=3, input_tokens=90),
        ModelUsage(provider="anthropic", model="claude-sonnet-5", calls=2, input_tokens=60),
    ]
    totals = summarize_usage(rows)
    assert len(totals) == 1
    assert totals[0].calls == 5
    assert totals[0].input_tokens == 150


def test_build_run_usage_with_no_fast_model_omits_share():
    steps = [
        StepRun(
            step="summarize",
            iteration=0,
            status="completed",
            provider="anthropic",
            model="claude-sonnet-5",
            duration_ms=100,
            input_hash="a",
            output_hash="b",
            usage=[
                ModelUsage(
                    provider="anthropic",
                    model="claude-sonnet-5",
                    calls=1,
                    input_tokens=100,
                    output_tokens=50,
                    total_tokens=150,
                )
            ],
        )
    ]
    run_usage = build_run_usage(steps, fast_model=None)
    assert run_usage.total_tokens == 150
    assert run_usage.fast_model is None
    assert run_usage.fast_model_share is None
    assert run_usage.fast_model_tokens == 0


def test_build_run_usage_computes_fast_model_share():
    steps = [
        StepRun(
            step="extract_assets",
            iteration=0,
            status="completed",
            provider="anthropic",
            model="claude-haiku-4-5",
            duration_ms=50,
            input_hash="a",
            output_hash="b",
            usage=[
                ModelUsage(
                    provider="anthropic",
                    model="claude-haiku-4-5",
                    calls=1,
                    input_tokens=80,
                    total_tokens=80,
                )
            ],
        ),
        StepRun(
            step="generate_threats",
            iteration=1,
            status="completed",
            provider="anthropic",
            model="claude-sonnet-5",
            duration_ms=200,
            input_hash="c",
            output_hash="d",
            usage=[
                ModelUsage(
                    provider="anthropic",
                    model="claude-sonnet-5",
                    calls=1,
                    input_tokens=120,
                    total_tokens=120,
                )
            ],
        ),
    ]
    run_usage = build_run_usage(steps, fast_model="claude-haiku-4-5")
    assert run_usage.total_tokens == 200
    assert run_usage.fast_model == "claude-haiku-4-5"
    assert run_usage.fast_model_tokens == 80
    assert run_usage.fast_model_share == 0.4


def test_build_run_usage_zero_total_tokens_gives_none_share_not_zero_division():
    # A step that failed before any response produced an empty usage list —
    # total_tokens is 0, and 0/0 must not raise or silently report 0.0.
    steps = [
        StepRun(
            step="summarize",
            iteration=0,
            status="failed",
            provider="anthropic",
            model="claude-sonnet-5",
            duration_ms=10,
            input_hash="a",
            output_hash="",
            usage=[],
        )
    ]
    run_usage = build_run_usage(steps, fast_model="claude-haiku-4-5")
    assert run_usage.total_tokens == 0
    assert run_usage.fast_model_share is None
