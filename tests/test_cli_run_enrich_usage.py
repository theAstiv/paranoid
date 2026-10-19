"""`paranoid run --enrich` usage accounting (bug-bash plan §5.6, run order item 25 / BB-78).

Enrichment runs after the pipeline on a fresh PipelineRunner, and the run's usage
summary is taken from the pipeline's COMPLETE event before enrichment starts. The
pipeline is faked here (one COMPLETE event with two threats), so the only LLM
calls are pre-flight and enrichment, each recorded like a real provider does.
"""

import json
import sqlite3

from click.testing import CliRunner

import backend.routes._helpers as route_helpers
import cli.commands.run as run_module
from backend.config import Settings
from backend.config import settings as global_settings
from backend.models.api import AnalyzeAssumptionsResponse, AnalyzeDescriptionResponse
from backend.models.usage import ModelUsage, StepRun, UsageRecord
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.providers.base import ProviderAuthError, ProviderRefusalError
from backend.providers.usage import build_run_usage, record_usage
from cli.commands.run import _merge_extra_usage
from tests.fixtures.pipeline import make_stride_threats
from tests.mock_provider import MockProvider


class _RecordingProvider(MockProvider):
    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def model(self) -> str:
        return "claude-mock"

    async def generate_structured(self, *args, **kwargs):
        record_usage(
            UsageRecord(
                provider="anthropic", model="claude-mock", input_tokens=100, output_tokens=10
            )
        )
        response_model = kwargs.get("response_model")
        if response_model is AnalyzeDescriptionResponse:
            return AnalyzeDescriptionResponse(gaps=[], is_sufficient=True)
        if response_model is AnalyzeAssumptionsResponse:
            return AnalyzeAssumptionsResponse(gaps=[], is_sufficient=True)
        return await super().generate_structured(*args, **kwargs)


class _RefusingProvider(_RecordingProvider):
    """Answers pre-flight, refuses every enrichment call."""

    async def generate_structured(self, *args, **kwargs):
        if kwargs.get("response_model") in (AnalyzeDescriptionResponse, AnalyzeAssumptionsResponse):
            return await super().generate_structured(*args, **kwargs)
        raise ProviderRefusalError("anthropic", "refused")


class _BrokenFastProvider(_RecordingProvider):
    """A fast model the account can't use: every call is a non-transient failure."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    @property
    def model(self) -> str:
        return "claude-mock-fast"

    async def generate_structured(self, *args, **kwargs):
        self.calls += 1
        raise ProviderAuthError("anthropic", "no access to this model")


def _two_threat_pipeline(*, fast_routing_disabled: bool = False):
    async def _pipeline(*args, **kwargs):
        threats = make_stride_threats()
        threats.threats = threats.threats[:2]
        usage = build_run_usage([], fast_model="claude-mock-fast")
        usage.fast_routing_disabled = fast_routing_disabled
        yield PipelineEvent(
            step=PipelineStep.COMPLETE,
            status="completed",
            message="done",
            data={"threats": threats, "total_threats": 2, "usage": usage.model_dump(mode="json")},
        )

    return _pipeline


def _run_enrich(tmp_path, monkeypatch, provider, *, fast_provider=None, pipeline=None) -> dict:
    """Invoke `paranoid run --enrich` and return the saved usage_summary."""
    settings = Settings(
        default_provider="anthropic",
        default_model="claude-mock",
        anthropic_api_key="sk-test",
        fast_model="",
        default_iterations=1,
        db_path=str(tmp_path / "enrich.db"),
    )
    monkeypatch.setattr(run_module, "_load_merged_settings", lambda: settings)
    # persist_pipeline_result opens the shared connection from the global settings.
    monkeypatch.setattr(global_settings, "db_path", settings.db_path)
    monkeypatch.setattr(run_module, "create_provider", lambda *a, **k: provider)
    monkeypatch.setattr(route_helpers, "create_provider", lambda *a, **k: provider)
    monkeypatch.setattr(run_module, "build_fast_provider", lambda *a, **k: fast_provider)
    monkeypatch.setattr(run_module, "run_pipeline_for_model", pipeline or _two_threat_pipeline())
    system = tmp_path / "system.md"
    system.write_text("A web API with JWT login, a Postgres database and an S3 upload bucket.")

    result = CliRunner().invoke(run_module.run, [str(system), "-n", "1", "--enrich"])
    assert result.exit_code == 0, result.output

    with sqlite3.connect(tmp_path / "enrich.db") as conn:
        (raw,) = conn.execute("SELECT usage_summary FROM threat_models").fetchone()
    return json.loads(raw)


def test_enrichment_calls_are_counted_in_the_run_usage(tmp_path, monkeypatch):
    usage = _run_enrich(tmp_path, monkeypatch, _RecordingProvider())

    steps = [step["step"] for step in usage["steps"]]
    assert steps.count("generate_attack_tree") == 2
    assert steps.count("generate_test_cases") == 2
    # Every enrichment call's tokens reach the totals, not just the step list.
    enrich_tokens = sum(
        m["total_tokens"]
        for s in usage["steps"]
        if s["step"] in ("generate_attack_tree", "generate_test_cases")
        for m in s["usage"]
    )
    assert enrich_tokens > 0
    assert usage["total_tokens"] >= enrich_tokens


def test_enrichment_refusals_raise_the_refusal_count(tmp_path, monkeypatch):
    usage = _run_enrich(tmp_path, monkeypatch, _RefusingProvider())

    # Two threats, each with a refused attack tree and a refused test suite.
    assert usage["refusal_count"] == 4


def test_fast_breaker_tripped_in_the_pipeline_stays_tripped_for_enrichment(tmp_path, monkeypatch):
    fast = _BrokenFastProvider()
    usage = _run_enrich(
        tmp_path,
        monkeypatch,
        _RecordingProvider(),
        fast_provider=fast,
        pipeline=_two_threat_pipeline(fast_routing_disabled=True),
    )

    assert fast.calls == 0
    assert usage["fast_routing_disabled"] is True
    assert {s["model"] for s in usage["steps"]} == {"claude-mock"}


def _step(name: str, tokens: int, model: str = "claude-mock") -> StepRun:
    return StepRun(
        step=name,
        iteration=0,
        status="completed",
        provider="anthropic",
        model=model,
        duration_ms=10,
        input_hash="",
        output_hash="",
        usage=[
            ModelUsage(
                provider="anthropic",
                model=model,
                calls=1,
                input_tokens=tokens,
                output_tokens=0,
                total_tokens=tokens,
            )
        ],
    )


def test_merge_extra_usage_appends_steps_and_keeps_other_fields():
    base = build_run_usage([_step("generate_threats", 300)], fast_model="claude-mock-fast")
    base.refusal_count = 1
    base.effort = "medium"
    base.stopped_reason = "gap_satisfied"
    run_usage = base.model_dump()
    run_usage["coverage_guard"] = {
        "triggered": True,
        "iteration": 1,
        "targeted": ["Tampering"],
        "still_empty": [],
        "na_maestro": [],
        "unknown_maestro": False,
    }

    merged = _merge_extra_usage(
        run_usage,
        [_step("generate_attack_tree", 50, "claude-mock-fast"), _step("generate_test_cases", 25)],
        extra_refusals=2,
        fast_disabled=True,
    )

    assert [s["step"] for s in merged["steps"]] == [
        "generate_threats",
        "generate_attack_tree",
        "generate_test_cases",
    ]
    assert merged["total_tokens"] == 375
    by_model = {m["model"]: m for m in merged["by_model"]}
    assert by_model["claude-mock"]["calls"] == 2
    assert by_model["claude-mock-fast"]["total_tokens"] == 50
    assert merged["fast_model_share"] == round(50 / 375, 4)
    assert merged["refusal_count"] == 3
    assert merged["fast_routing_disabled"] is True
    assert merged["effort"] == "medium"
    assert merged["stopped_reason"] == "gap_satisfied"
    assert merged["coverage_guard"]["targeted"] == ["Tampering"]


def test_merge_extra_usage_is_a_noop_without_a_completed_run_or_extras():
    run_usage = build_run_usage([_step("generate_threats", 300)]).model_dump()
    assert _merge_extra_usage(None, [_step("generate_attack_tree", 50)], extra_refusals=1) is None
    assert _merge_extra_usage(run_usage, []) is run_usage
