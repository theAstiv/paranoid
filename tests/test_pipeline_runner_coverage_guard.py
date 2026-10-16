"""Runner-level tests for the coverage guard (BB-15) and stop-text persistence (BB-16).

A scripted provider returns chosen threats per generate_threats call and a gap
analysis that always says stop, so each test controls exactly what is empty.
"""

import pytest

from backend.models.enums import AssetType, Framework, MaestroCategory, StrideCategory
from backend.models.state import Asset, AssetsList, GapAnalysis, Threat, ThreatsList
from backend.pipeline.runner import PipelineConfig, PipelineRunner, PipelineStep
from tests.mock_provider import MockProvider


ST = StrideCategory
MC = MaestroCategory


def _threat(name: str, stride: StrideCategory, maestro: MaestroCategory | None = None) -> Threat:
    return Threat(
        name=name,
        stride_category=stride,
        maestro_category=maestro,
        description=f"Scenario {name}: an attacker abuses this component in a way unique to it.",
        target="Target",
        impact="medium",
        likelihood="medium",
        mitigations=["Mitigation A", "Mitigation B"],
    )


def _pass(tag: str, skip: StrideCategory | None = None, per_category: int = 1) -> ThreatsList:
    """One pass of STRIDE threats with unique names, optionally leaving one category out."""
    return ThreatsList(
        threats=[
            _threat(f"{tag} {c.value} {i}", c)
            for c in StrideCategory
            if c != skip
            for i in range(per_category)
        ]
    )


class _ScriptedProvider(MockProvider):
    """threats: per STRIDE call; maestro: per MAESTRO call; gaps: per gap call (default stop)."""

    def __init__(self, threats, maestro=None, gaps=None):
        super().__init__()
        self.stride_script = list(threats)
        self.maestro_script = list(maestro or [])
        self.gap_script = list(gaps or [])
        self.stride_calls = 0
        self.maestro_calls = 0
        self.gap_calls = 0
        self.threat_prompts: list[str] = []

    async def generate_structured(self, prompt, response_model, *args, **kwargs):
        is_maestro = "Maestro" in response_model.__name__
        if "Threats" in response_model.__name__:
            self.threat_prompts.append(prompt)
        self._is_maestro = is_maestro
        return await super().generate_structured(prompt, response_model, *args, **kwargs)

    def _dispatch(self, response_model):
        name = response_model.__name__
        if name == "ThreatsList":
            if self._is_maestro:
                script, self.maestro_calls = self.maestro_script, self.maestro_calls + 1
                return script[min(self.maestro_calls, len(script)) - 1]
            self.stride_calls += 1
            return self.stride_script[min(self.stride_calls, len(self.stride_script)) - 1]
        if name == "GapAnalysis":
            self.gap_calls += 1
            if self.gap_script:
                return self.gap_script[min(self.gap_calls, len(self.gap_script)) - 1]
            return GapAnalysis(stop=True, gap=None)
        return super()._dispatch(response_model)


async def _run(provider, *, framework=Framework.STRIDE, **config):
    config.setdefault("max_iterations", 3)
    config.setdefault("similarity_threshold", 0.999)  # only identical text dedups
    config.setdefault("dedup_saturation_threshold", 1.1)
    config.setdefault("enable_rag", False)
    runner = PipelineRunner(provider=provider, config=PipelineConfig(**config), model_id="t")
    events = [e async for e in runner.run(description="A document app", framework=framework)]
    complete = events[-1]
    assert complete.step == PipelineStep.COMPLETE
    assert complete.status == "completed"
    return events, complete.data


def _report(data):
    return data["usage"]["coverage_guard"]


@pytest.mark.asyncio
async def test_stop_with_empty_stride_category_gets_exactly_one_targeted_pass():
    provider = _ScriptedProvider(
        [_pass("a", skip=ST.TAMPERING), _pass("b", skip=None)],
    )
    _, data = await _run(provider)

    assert provider.stride_calls == 2
    assert "no STRIDE threats exist yet for Tampering" in provider.threat_prompts[1]
    assert "no STRIDE threats exist yet" not in provider.threat_prompts[0]
    assert data["iterations_completed"] == 2
    assert data["stopped_reason"] == "gap_satisfied"
    assert data["gaps"][0].startswith("Coverage check:")
    assert _report(data)["triggered"] is True
    assert _report(data)["iteration"] == 1
    assert _report(data)["targeted"] == ["Tampering"]
    assert _report(data)["still_empty"] == []


@pytest.mark.asyncio
async def test_second_empty_result_is_accepted_without_a_third_pass():
    provider = _ScriptedProvider([_pass("a", skip=ST.TAMPERING), _pass("b", skip=ST.TAMPERING)])
    _, data = await _run(provider, max_iterations=5)

    assert provider.stride_calls == 2
    assert data["stopped_reason"] == "gap_satisfied"
    assert _report(data)["triggered"] is True
    assert _report(data)["still_empty"] == ["Tampering"]


@pytest.mark.asyncio
async def test_single_iteration_run_never_triggers_but_still_reports():
    provider = _ScriptedProvider([_pass("a", skip=ST.REPUDIATION)])
    _, data = await _run(provider, max_iterations=1)

    assert provider.stride_calls == 1
    assert provider.gap_calls == 0
    assert _report(data)["triggered"] is False
    assert _report(data)["still_empty"] == ["Repudiation"]


@pytest.mark.asyncio
async def test_targeted_pass_can_be_the_last_iteration():
    provider = _ScriptedProvider([_pass("a", skip=ST.TAMPERING), _pass("b", skip=ST.TAMPERING)])
    _, data = await _run(provider, max_iterations=2)

    assert provider.stride_calls == 2
    assert provider.gap_calls == 1  # none after the final iteration
    assert data["iterations_completed"] == 2
    assert _report(data)["still_empty"] == ["Tampering"]


@pytest.mark.asyncio
async def test_balanced_coverage_is_unchanged_and_reports_nothing():
    provider = _ScriptedProvider([_pass("a", per_category=2)])
    events, data = await _run(provider, max_iterations=5)

    assert provider.stride_calls == 1
    assert provider.gap_calls == 0  # deterministic STRIDE short-circuit
    assert data["stopped_reason"] == "gap_satisfied"
    assert _report(data) is None
    assert not [e for e in events if "coverage_guard" in (e.data or {})]


@pytest.mark.asyncio
async def test_covered_but_unbalanced_stop_is_accepted_as_before():
    provider = _ScriptedProvider([_pass("a")])  # one per category: no holes, not balanced
    _, data = await _run(provider, max_iterations=5)

    assert provider.stride_calls == 1
    assert provider.gap_calls == 1
    assert _report(data) is None


@pytest.mark.asyncio
async def test_dedup_saturation_after_the_targeted_pass_is_accepted_and_recorded():
    same = _pass("a", skip=ST.TAMPERING)
    provider = _ScriptedProvider([same, same])
    _, data = await _run(provider, max_iterations=5, dedup_saturation_threshold=0.7)

    assert data["stopped_reason"] == "dedup_saturated"
    assert provider.stride_calls == 2
    assert _report(data)["triggered"] is True
    assert _report(data)["still_empty"] == ["Tampering"]


@pytest.mark.asyncio
async def test_min_iterations_floor_does_not_consume_the_guard():
    provider = _ScriptedProvider([_pass("a", skip=ST.TAMPERING), _pass("b", skip=ST.TAMPERING)])
    _, data = await _run(provider, min_iterations=2)

    # Iteration 1: stop below the floor, ignored. Iteration 2: stop would be
    # accepted, so the guard fires there, once.
    assert _report(data)["triggered"] is True
    assert _report(data)["iteration"] == 2
    assert provider.stride_calls == 3


@pytest.mark.asyncio
async def test_provider_offline_run_has_no_coverage_report():
    provider = _ScriptedProvider([_pass("a")])
    provider.error_types = {ThreatsList}
    _, data = await _run(provider)

    assert data["stopped_reason"] == "provider_offline"
    assert data["usage"]["stopped_reason"] == "provider_offline"
    assert _report(data) is None


# --- MAESTRO -------------------------------------------------------------------

_AI_ASSETS = AssetsList(
    assets=[
        Asset(type=AssetType.ASSET, name="Support Chatbot LLM", description="Answers tickets"),
        Asset(type=AssetType.ASSET, name="API Gateway", description="FastAPI backend"),
    ]
)


def _maestro(tag: str, category: MaestroCategory) -> ThreatsList:
    return ThreatsList(threats=[_threat(f"{tag} {category.value}", ST.TAMPERING, category)])


def _hybrid(provider):
    provider.response_overrides[AssetsList] = _AI_ASSETS
    return _run(provider, has_ai_components=True)


@pytest.mark.asyncio
async def test_applicable_maestro_category_with_no_threats_overrides_the_stride_short_circuit():
    provider = _ScriptedProvider(
        [_pass("a", per_category=2), _pass("b", per_category=2)],
        maestro=[_maestro("a", MC.MODEL_SECURITY), _maestro("b", MC.LLM_SECURITY)],
    )
    _, data = await _hybrid(provider)

    assert provider.gap_calls == 0  # both stops came from the deterministic gate
    assert provider.stride_calls == 2
    assert provider.maestro_calls == 2
    assert "no MAESTRO threats exist yet for LLM Security" in provider.threat_prompts[2]
    assert "Support Chatbot LLM" in provider.threat_prompts[2]
    assert _report(data)["triggered"] is True
    assert _report(data)["targeted"] == ["MAESTRO: LLM Security"]
    assert _report(data)["still_empty"] == []
    assert "LLM Security" not in _report(data)["na_maestro"]
    # Model Security has a threat (pass "a"), so it is not N/A even though no
    # component matched it; Privacy has neither a component nor a threat.
    assert "Model Security" not in _report(data)["na_maestro"]
    assert "Privacy" in _report(data)["na_maestro"]


@pytest.mark.asyncio
async def test_maestro_hole_left_after_the_targeted_pass_is_accepted():
    provider = _ScriptedProvider(
        [_pass("a", per_category=2), _pass("b", per_category=2)],
        maestro=[_maestro("a", MC.MODEL_SECURITY), _maestro("b", MC.MODEL_SECURITY)],
    )
    _, data = await _hybrid(provider)

    assert provider.stride_calls == 2  # no third pass although max_iterations is 3
    assert data["stopped_reason"] == "gap_satisfied"
    assert _report(data)["still_empty"] == ["MAESTRO: LLM Security"]


@pytest.mark.asyncio
async def test_not_applicable_maestro_categories_never_trigger():
    provider = _ScriptedProvider(
        [_pass("a", per_category=2)],
        maestro=[_maestro("a", MC.LLM_SECURITY)],
    )
    _, data = await _hybrid(provider)

    assert provider.stride_calls == 1
    assert _report(data)["triggered"] is False
    assert _report(data)["still_empty"] == []
    assert "Privacy" in _report(data)["na_maestro"]


@pytest.mark.asyncio
async def test_unknown_maestro_applicability_never_triggers_and_is_flagged():
    provider = _ScriptedProvider([_pass("a", per_category=2)], maestro=[_maestro("a", MC.PRIVACY)])
    _, data = await _run(provider, has_ai_components=True)  # default assets: no AI terms

    assert provider.stride_calls == 1
    assert _report(data)["triggered"] is False
    assert _report(data)["unknown_maestro"] is True
    assert _report(data)["na_maestro"] == []


@pytest.mark.asyncio
async def test_maestro_only_run_also_requires_stride_categories():
    provider = _ScriptedProvider(
        [],
        maestro=[
            ThreatsList(
                threats=[
                    _threat(f"m{c.value}", c, MC.LLM_SECURITY)
                    for c in StrideCategory
                    if c != ST.SPOOFING
                ]
            ),
            ThreatsList(threats=[_threat("m2", ST.SPOOFING, MC.LLM_SECURITY)]),
        ],
    )
    provider.response_overrides[AssetsList] = _AI_ASSETS
    _, data = await _run(provider, framework=Framework.MAESTRO)

    assert provider.maestro_calls == 2
    assert _report(data)["targeted"] == ["Spoofing"]


# --- BB-16: the stop text is kept ------------------------------------------------


@pytest.mark.asyncio
async def test_llm_stop_text_is_persisted_in_gaps():
    provider = _ScriptedProvider(
        [_pass("a")], gaps=[GapAnalysis(stop=True, gap="Coverage looks comprehensive")]
    )
    _, data = await _run(provider, max_iterations=5)

    assert data["gaps"] == ["Coverage looks comprehensive"]
    assert data["usage"]["stopped_reason"] == "gap_satisfied"


@pytest.mark.asyncio
async def test_llm_stop_without_text_adds_nothing():
    provider = _ScriptedProvider([_pass("a")])
    _, data = await _run(provider, max_iterations=5)

    assert data["gaps"] == []


@pytest.mark.asyncio
async def test_deterministic_stop_text_is_persisted_in_gaps():
    provider = _ScriptedProvider([_pass("a", per_category=2)])
    _, data = await _run(provider, max_iterations=5)

    assert data["gaps"] == ["Coverage balanced across all STRIDE categories"]


@pytest.mark.asyncio
async def test_override_keeps_the_models_own_gap_text_first():
    provider = _ScriptedProvider(
        [_pass("a", skip=ST.TAMPERING), _pass("b")],
        gaps=[GapAnalysis(stop=True, gap="Looks done")],
    )
    _, data = await _run(provider)

    assert data["gaps"][0].startswith("Looks done Coverage check:")
