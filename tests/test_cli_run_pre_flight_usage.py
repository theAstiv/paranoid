"""Tests for cli.commands.run._run_pre_flight / _merge_pre_flight_usage (4a-3 follow-up).

The CLI's pre-flight gap check (backend.pipeline.pre_flight.analyze_bundle)
runs before the pipeline runner opens its own collect_usage() scopes, so any
LLM call it makes was previously dropped from the run's usage_summary
entirely (record_usage() is a documented no-op outside an open scope). This
file tests both the fix itself (_run_pre_flight, exercised against the real
analyze_bundle() with a fake provider — not a mock of analyze_bundle, which
would hide a regression of the collect_usage() wrapping) and the merge step
that folds its result into a run's usage summary — see
tests/test_providers_usage.py for the underlying accounting math.
"""

import pytest

from backend.models.api import AnalyzeAssumptionsResponse, AnalyzeDescriptionResponse
from backend.models.usage import ModelUsage, RunUsage, StepRun, UsageRecord
from backend.providers.usage import record_usage
from cli.commands.run import _merge_pre_flight_usage, _run_pre_flight


class _FakePreFlightProvider:
    """Enough of LLMProvider to drive analyze_bundle()'s two LLM-backed checks
    and record usage like a real provider does."""

    def __init__(self) -> None:
        self.calls: list[type] = []

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return "claude-sonnet-5"

    async def generate_structured(self, *, prompt, response_model, **kwargs):
        self.calls.append(response_model)
        record_usage(
            UsageRecord(provider=self.name, model=self.model, input_tokens=40, output_tokens=20)
        )
        if response_model is AnalyzeDescriptionResponse:
            return AnalyzeDescriptionResponse(gaps=[], is_sufficient=True)
        if response_model is AnalyzeAssumptionsResponse:
            return AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True)
        raise AssertionError(f"unexpected response_model: {response_model}")


# A description deliberately covering all four deterministic keyword
# categories (auth/boundary/flow/external) so _deterministic_gaps() returns
# zero gaps — the skip condition (has_errors or len(det_gaps) >= 3) is then
# false and analyze_description_gaps() calls the LLM.
_RICH_DESCRIPTION = (
    "The web API performs JWT-based authentication for users, then sends "
    "requests to an internal database over TLS. The service is "
    "internet-facing and also calls a third-party payment API for "
    "settlement."
)

# Assumptions covering controls/scope/out-of-scope/focus terms, each well
# over the 30-char stub threshold, so _deterministic_assumptions_gaps()
# stays under its own skip threshold (len(det_gaps) >= 4) and
# analyze_assumptions_gaps() calls the LLM too.
_RICH_ASSUMPTIONS = [
    (
        "Security controls already in place include TLS, OAuth-based "
        "authentication, and rate limiting on the API gateway."
    ),
    (
        "In scope: the public API and the internal order-processing service. "
        "Out of scope: the third-party payment gateway's own infrastructure."
    ),
    (
        "The focus areas for this review are the authentication flow and data "
        "storage boundaries; these are the key risks to prioritize."
    ),
]


@pytest.mark.asyncio
async def test_run_pre_flight_captures_usage_from_both_concurrent_checks():
    # Mutation check for this test: removing the `with collect_usage()`
    # wrapper around analyze_bundle() in _run_pre_flight (reverting to a bare
    # `await analyze_bundle(...)`) makes this assert None, reproducing the
    # original bug — record_usage() is a documented no-op with no open scope.
    provider = _FakePreFlightProvider()
    _bundle, step = await _run_pre_flight(_RICH_DESCRIPTION, _RICH_ASSUMPTIONS, provider)

    assert step is not None
    assert step.step == "pre_flight"
    assert step.provider == "anthropic"
    assert step.model == "claude-sonnet-5"
    # analyze_bundle() runs the description and assumptions checks as two
    # concurrent tasks; both must have reached the LLM and both must have
    # recorded into the same collect_usage() scope.
    assert AnalyzeDescriptionResponse in provider.calls
    assert AnalyzeAssumptionsResponse in provider.calls
    assert step.usage[0].calls == 2
    assert step.usage[0].input_tokens == 80
    assert step.usage[0].output_tokens == 40


@pytest.mark.asyncio
async def test_run_pre_flight_returns_no_step_when_llm_is_skipped():
    # A short description (<80 chars) and no assumptions both hit
    # pre_flight.py's deterministic-only skip paths — no LLM call is made,
    # so there's no usage to report and no empty row should be added.
    provider = _FakePreFlightProvider()
    _bundle, step = await _run_pre_flight("A short system.", None, provider)

    assert step is None
    assert provider.calls == []


def _sample_run_usage() -> dict:
    """A plausible COMPLETE-event usage dict: one main-model step, one
    fast-model step, matching what build_run_usage() would have produced."""
    return RunUsage(
        steps=[
            StepRun(
                step="extract_assets",
                iteration=0,
                status="completed",
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                duration_ms=1000,
                input_hash="h1",
                output_hash="h2",
                usage=[
                    ModelUsage(
                        provider="anthropic",
                        model="claude-haiku-4-5-20251001",
                        calls=1,
                        input_tokens=100,
                        output_tokens=50,
                        total_tokens=150,
                    )
                ],
            ),
            StepRun(
                step="generate_threats",
                iteration=1,
                status="completed",
                provider="anthropic",
                model="claude-sonnet-5",
                duration_ms=2000,
                input_hash="h3",
                output_hash="h4",
                usage=[
                    ModelUsage(
                        provider="anthropic",
                        model="claude-sonnet-5",
                        calls=1,
                        input_tokens=200,
                        output_tokens=100,
                        total_tokens=300,
                    )
                ],
            ),
        ],
        by_model=[],  # overwritten below via build_run_usage, not read by the merge
        total_tokens=450,
        fast_model="claude-haiku-4-5-20251001",
        fast_model_tokens=150,
        fast_model_share=round(150 / 450, 4),
        fast_routing_disabled=False,
    ).model_dump()


def _pre_flight_step(tokens: int = 60) -> StepRun:
    return StepRun(
        step="pre_flight",
        iteration=0,
        status="completed",
        provider="anthropic",
        model="claude-sonnet-5",
        duration_ms=500,
        input_hash="",
        output_hash="",
        usage=[
            ModelUsage(
                provider="anthropic",
                model="claude-sonnet-5",
                calls=1,
                input_tokens=40,
                output_tokens=20,
                total_tokens=tokens,
            )
        ],
    )


def test_noop_when_no_pre_flight_usage():
    run_usage = _sample_run_usage()
    assert _merge_pre_flight_usage(run_usage, None) is run_usage


def test_noop_when_run_never_completed():
    # The pipeline failed before a COMPLETE event, so there's nothing to
    # attach the pre-flight step to (consistent with existing behaviour:
    # all usage is already dropped in that case).
    assert _merge_pre_flight_usage(None, _pre_flight_step()) is None


def test_pre_flight_step_is_added_and_totals_recomputed():
    merged = _merge_pre_flight_usage(_sample_run_usage(), _pre_flight_step(tokens=60))

    steps = [s["step"] for s in merged["steps"]]
    assert "pre_flight" in steps
    assert steps[0] == "pre_flight"  # prepended, execution order preserved otherwise

    # Sonnet's by_model total now includes the pre-flight call's tokens.
    by_model = {m["model"]: m for m in merged["by_model"]}
    assert by_model["claude-sonnet-5"]["total_tokens"] == 300 + 60
    assert by_model["claude-sonnet-5"]["calls"] == 2
    assert merged["total_tokens"] == 450 + 60


def test_fast_model_share_is_recomputed_not_carried_over_stale():
    # Pre-flight always runs on the main model, so adding its tokens must
    # shrink the fast-model's share of the (now larger) total — a stale
    # carried-over share would silently overstate the fast model's share.
    original = _sample_run_usage()
    merged = _merge_pre_flight_usage(original, _pre_flight_step(tokens=60))

    assert merged["fast_model_share"] < original["fast_model_share"]
    assert merged["fast_model_tokens"] == 150  # fast model's own tokens are unchanged
    assert merged["fast_model_share"] == round(150 / (450 + 60), 4)


def test_fast_routing_disabled_is_preserved_through_the_rebuild():
    run_usage = _sample_run_usage()
    run_usage["fast_routing_disabled"] = True

    merged = _merge_pre_flight_usage(run_usage, _pre_flight_step())

    assert merged["fast_routing_disabled"] is True


def test_no_fast_model_run_stays_without_a_fast_share():
    run_usage = _sample_run_usage()
    run_usage["fast_model"] = None
    run_usage["fast_model_tokens"] = 0
    run_usage["fast_model_share"] = None

    merged = _merge_pre_flight_usage(run_usage, _pre_flight_step())

    assert merged["fast_model"] is None
    assert merged["fast_model_share"] is None
