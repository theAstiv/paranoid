"""Tests for per-step fast/main model routing (week 4a-2).

Covers: the default routing map (reproduces the pre-4a-2 hardcoded split
exactly), provider-specific overrides, the forbidden-fast validation on
PipelineConfig, step_models overriding the default per run, and the
fast-model-failure fallback to main.
"""

import pytest

from backend.config import settings
from backend.models.enums import Framework
from backend.models.extended import AttackTree, CodeSummary, TestSuite
from backend.models.state import AssetsList
from backend.models.usage import UsageRecord
from backend.pipeline.runner import (
    FORBIDDEN_FAST_STEPS,
    PipelineConfig,
    PipelineRunner,
    PipelineStep,
    default_step_models,
    run_pipeline_for_model,
    validate_step_models,
)
from backend.providers.usage import record_usage
from tests.fixtures.pipeline import make_code_context
from tests.mock_provider import MockProvider


class NamedMockProvider(MockProvider):
    """MockProvider with a settable model name, like UsageMockProvider."""

    def __init__(self, model: str = "mock-v1", **kwargs) -> None:
        super().__init__(**kwargs)
        self._model_name = model

    @property
    def model(self) -> str:
        return self._model_name

    async def generate_structured(self, *args, **kwargs):
        result = await super().generate_structured(*args, **kwargs)
        record_usage(UsageRecord(provider=self.name, model=self._model_name, input_tokens=10))
        return result


async def _collect_events(runner: PipelineRunner, description: str, framework: Framework):
    events = []
    async for event in runner.run(
        description=description, framework=framework, stop_after="extraction"
    ):
        events.append(event)
    return events


def test_default_step_models_reproduces_legacy_hardcoded_split():
    """Default map must match the split that predates per-step config —
    merging 4a-2 must not change behaviour for existing callers."""
    defaults = default_step_models("anthropic")
    assert defaults[PipelineStep.SUMMARIZE] == "main"
    assert defaults[PipelineStep.SUMMARIZE_CODE] == "main"
    assert defaults[PipelineStep.EXTRACT_ASSETS] == "fast"
    assert defaults[PipelineStep.EXTRACT_FLOWS] == "fast"
    assert defaults[PipelineStep.GENERATE_THREATS] == "main"
    assert defaults[PipelineStep.GAP_ANALYSIS] == "main"
    assert defaults[PipelineStep.GENERATE_ATTACK_TREE] == "fast"
    assert defaults[PipelineStep.GENERATE_TEST_CASES] == "fast"


def test_openai_default_keeps_extract_flows_on_main():
    """Conservative default pending the 4a-3 routing comparison — gpt-4.1-mini
    is suspected (unmeasured) to be thinner on dense MAESTRO flow extraction
    than gpt-4.1, so the OpenAI default overrides extract_flows to main."""
    defaults = default_step_models("openai")
    assert defaults[PipelineStep.EXTRACT_FLOWS] == "main"
    assert defaults[PipelineStep.EXTRACT_ASSETS] == "fast"  # unaffected


def test_unknown_provider_falls_back_to_base_defaults():
    defaults = default_step_models("ollama")
    assert defaults == default_step_models("anthropic")


def test_validate_step_models_rejects_forbidden_fast_steps():
    for step in FORBIDDEN_FAST_STEPS:
        with pytest.raises(ValueError, match="can never be routed to the fast model"):
            validate_step_models({step: "fast"})


def test_validate_step_models_allows_non_forbidden_fast_steps():
    validate_step_models({PipelineStep.EXTRACT_ASSETS: "fast", PipelineStep.SUMMARIZE: "fast"})


def test_pipeline_config_rejects_forbidden_step_models_at_construction():
    with pytest.raises(ValueError, match="can never be routed to the fast model"):
        PipelineConfig(step_models={PipelineStep.GAP_ANALYSIS: "fast"})


def test_pipeline_config_accepts_valid_step_models():
    config = PipelineConfig(step_models={PipelineStep.SUMMARIZE: "fast"})
    assert config.step_models[PipelineStep.SUMMARIZE] == "fast"


@pytest.mark.asyncio
async def test_runner_uses_default_routing_when_step_models_unset():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t1"
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    by_step = {e.step: e for e in events if e.status == "completed"}

    assert by_step[PipelineStep.SUMMARIZE].data["model"] == "main-v1"
    assert by_step[PipelineStep.EXTRACT_ASSETS].data["model"] == "fast-v1"
    assert by_step[PipelineStep.EXTRACT_FLOWS].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_step_models_override_routes_a_normally_fast_step_to_main():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(
        enable_rag=False,
        step_models={
            PipelineStep.EXTRACT_ASSETS: "main",
            PipelineStep.EXTRACT_FLOWS: "fast",
        },
    )
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t2"
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    by_step = {e.step: e for e in events if e.status == "completed"}

    assert by_step[PipelineStep.EXTRACT_ASSETS].data["model"] == "main-v1"
    assert by_step[PipelineStep.EXTRACT_FLOWS].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_step_models_can_route_summarize_to_fast():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(enable_rag=False, step_models={PipelineStep.SUMMARIZE: "fast"})
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t3"
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)
    by_step = {e.step: e for e in events if e.status == "completed"}

    assert by_step[PipelineStep.SUMMARIZE].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_fast_model_failure_falls_back_to_main_and_completes():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    fast_provider.error_types = {AssetsList}  # fast provider fails extract_assets only
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t4"
    )

    events = await _collect_events(runner, "A document sharing app", Framework.STRIDE)

    info_events = [
        e for e in events if e.step == PipelineStep.EXTRACT_ASSETS and e.status == "info"
    ]
    assert info_events, "expected a fallback info event for extract_assets"
    assert "retried on main model" in info_events[0].message

    completed = [
        e for e in events if e.step == PipelineStep.EXTRACT_ASSETS and e.status == "completed"
    ]
    assert completed, "pipeline must still complete the step after falling back"
    assert completed[0].data["model"] == "main-v1"

    # extract_flows runs normally on the fast provider afterward — the
    # fallback for one step must not poison later steps.
    flows_completed = [
        e for e in events if e.step == PipelineStep.EXTRACT_FLOWS and e.status == "completed"
    ]
    assert flows_completed[0].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_main_model_failure_degrades_without_a_fallback_retry():
    """There's nothing to fall back to when the step is already on main
    (no distinct fast_provider configured) — the failure must surface as a
    single ProviderError, caught by the pipeline's existing pre-loop
    degrade-to-rule-engine handling, not an infinite or duplicate retry."""
    main_provider = NamedMockProvider(model="main-v1")
    main_provider.error_types = {AssetsList}
    config = PipelineConfig(enable_rag=False, max_iterations=1)
    runner = PipelineRunner(provider=main_provider, config=config, model_id="t5")

    events = []
    async for event in runner.run(description="A document sharing app", framework=Framework.STRIDE):
        events.append(event)

    assert events[-1].step == PipelineStep.COMPLETE
    assert events[-1].data["stopped_reason"] == "provider_offline"
    # extract_assets was attempted exactly once — no fallback retry since the
    # routed provider was already main.
    assets_calls = [c for c in main_provider.calls if c["response_model"] is AssetsList]
    assert len(assets_calls) == 1


@pytest.mark.asyncio
async def test_run_pipeline_for_model_merges_settings_step_models_env_override(monkeypatch):
    """settings.step_models (STEP_MODELS env) is merged over the provider's
    default map when the caller doesn't pass an explicit step_models."""
    monkeypatch.setattr(settings, "step_models", {"summarize": "fast"})
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")

    events = []
    async for event in run_pipeline_for_model(
        model_id="t6",
        description="A document sharing app",
        framework=Framework.STRIDE,
        provider=main_provider,
        fast_provider=fast_provider,
        max_iterations=1,
        stop_after="extraction",
    ):
        events.append(event)

    by_step = {e.step: e for e in events if e.status == "completed"}
    assert by_step[PipelineStep.SUMMARIZE].data["model"] == "fast-v1"
    # extract_assets keeps the provider default (fast) — the override only
    # touched summarize.
    assert by_step[PipelineStep.EXTRACT_ASSETS].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_run_pipeline_for_model_explicit_step_models_wins_over_settings(monkeypatch):
    monkeypatch.setattr(settings, "step_models", {"extract_assets": "fast"})
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")

    events = []
    async for event in run_pipeline_for_model(
        model_id="t7",
        description="A document sharing app",
        framework=Framework.STRIDE,
        provider=main_provider,
        fast_provider=fast_provider,
        max_iterations=1,
        stop_after="extraction",
        step_models={PipelineStep.EXTRACT_ASSETS: "main"},
    ):
        events.append(event)

    by_step = {e.step: e for e in events if e.status == "completed"}
    assert by_step[PipelineStep.EXTRACT_ASSETS].data["model"] == "main-v1"
    # A partial override must merge onto the provider defaults, not replace
    # them — extract_flows (not in the override) must still default to fast.
    assert by_step[PipelineStep.EXTRACT_FLOWS].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_summarize_code_defaults_to_main_and_is_routable_to_fast():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(enable_rag=False, step_models={PipelineStep.SUMMARIZE_CODE: "fast"})
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t9"
    )

    events = []
    async for event in runner.run(
        description="A document sharing app",
        framework=Framework.STRIDE,
        code_context=make_code_context(),
        stop_after="extraction",
    ):
        events.append(event)

    by_step = {e.step: e for e in events if e.status == "completed"}
    assert by_step[PipelineStep.SUMMARIZE_CODE].data["model"] == "fast-v1"


@pytest.mark.asyncio
async def test_summarize_code_fast_failure_degrades_deterministically_not_via_fallback():
    """Known limitation (documented at the SUMMARIZE_CODE call site in
    runner.py): nodes.summarize_code() catches ProviderError itself and
    returns a deterministic summary, so _call_step's fast-to-main fallback
    never triggers for this step — the deterministic fallback wins instead
    of a retry on main. This test locks in that current behaviour so a
    future change to the node either fixes it deliberately or this test
    catches the drift."""
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    fast_provider.error_types = {CodeSummary}
    config = PipelineConfig(enable_rag=False, step_models={PipelineStep.SUMMARIZE_CODE: "fast"})
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t10"
    )

    events = []
    async for event in runner.run(
        description="A document sharing app",
        framework=Framework.STRIDE,
        code_context=make_code_context(),
        stop_after="extraction",
    ):
        events.append(event)

    # No fallback "info" event — the node swallowed the error before
    # _call_step ever saw it.
    info_events = [
        e for e in events if e.step == PipelineStep.SUMMARIZE_CODE and e.status == "info"
    ]
    assert info_events == []
    completed = [
        e for e in events if e.step == PipelineStep.SUMMARIZE_CODE and e.status == "completed"
    ]
    # "model" still reports fast-v1 (the routed provider), even though the
    # actual content came from the deterministic fallback inside the node.
    assert completed[0].data["model"] == "fast-v1"
    # main provider was never called for this step.
    assert not any(c["response_model"] is CodeSummary for c in main_provider.calls)


@pytest.mark.asyncio
async def test_attack_tree_enrichment_uses_fast_provider_by_default():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t11"
    )

    await runner.generate_attack_tree_for_threat(
        threat_id="1",
        threat_name="Spoofed login",
        threat_description="An attacker spoofs a login request.",
        target="auth-service",
        stride_category="spoofing",
        maestro_category=None,
        mitigations=["MFA"],
    )

    assert not any(c["response_model"] is AttackTree for c in main_provider.calls)
    assert any(c["response_model"] is AttackTree for c in fast_provider.calls)


@pytest.mark.asyncio
async def test_attack_tree_enrichment_falls_back_to_main_on_fast_failure():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    fast_provider.error_types = {AttackTree}
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t12"
    )

    result = await runner.generate_attack_tree_for_threat(
        threat_id="1",
        threat_name="Spoofed login",
        threat_description="An attacker spoofs a login request.",
        target="auth-service",
        stride_category="spoofing",
        maestro_category=None,
        mitigations=["MFA"],
    )

    assert isinstance(result, AttackTree)
    assert any(c["response_model"] is AttackTree for c in main_provider.calls)


@pytest.mark.asyncio
async def test_test_cases_enrichment_uses_fast_provider_by_default():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t13"
    )

    await runner.generate_test_cases_for_threat(
        threat_id="1",
        threat_name="Spoofed login",
        threat_description="An attacker spoofs a login request.",
        target="auth-service",
        mitigations=["MFA"],
    )

    assert not any(c["response_model"] is TestSuite for c in main_provider.calls)
    assert any(c["response_model"] is TestSuite for c in fast_provider.calls)


@pytest.mark.asyncio
async def test_test_cases_enrichment_falls_back_to_main_on_fast_failure():
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    fast_provider.error_types = {TestSuite}
    config = PipelineConfig(enable_rag=False)
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t14"
    )

    result = await runner.generate_test_cases_for_threat(
        threat_id="1",
        threat_name="Spoofed login",
        threat_description="An attacker spoofs a login request.",
        target="auth-service",
        mitigations=["MFA"],
    )

    assert isinstance(result, TestSuite)
    assert any(c["response_model"] is TestSuite for c in main_provider.calls)


def test_pipeline_config_step_models_merges_with_provider_defaults_in_runner():
    """Regression for the bug where a partial PipelineConfig.step_models
    override silently dropped every other step to "main" because
    PipelineRunner used `config.step_models or default_step_models(...)`
    (replace) instead of merging the override onto the defaults."""
    main_provider = NamedMockProvider(model="main-v1")
    fast_provider = NamedMockProvider(model="fast-v1")
    config = PipelineConfig(step_models={PipelineStep.SUMMARIZE: "fast"})
    runner = PipelineRunner(
        provider=main_provider, fast_provider=fast_provider, config=config, model_id="t8"
    )

    assert runner._step_models[PipelineStep.SUMMARIZE] == "fast"  # the override
    assert runner._step_models[PipelineStep.EXTRACT_ASSETS] == "fast"  # untouched default
    assert runner._step_models[PipelineStep.EXTRACT_FLOWS] == "fast"  # untouched default
    assert runner._step_models[PipelineStep.GENERATE_THREATS] == "main"  # untouched default
