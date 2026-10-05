"""Tests for the map_techniques pipeline node and its runner wiring.

- backend.pipeline.nodes.attack_mapping.map_threat_techniques: pure function
- backend.pipeline.runner: MAP_TECHNIQUES step wiring, runs regardless of
  LLM success, degrades gracefully on a matching failure

Real embedding calls are mocked at the module level (see
tests/conftest.py's mock_technique_embeddings autouse fixture), consistent
with how tests/test_dedup.py avoids the fastembed model download.
"""

from unittest.mock import patch

import pytest

from backend.models.enums import Framework
from backend.models.state import DependencyRef, Threat, ThreatsList
from backend.pipeline.nodes.attack_mapping import map_threat_techniques
from backend.pipeline.runner import PipelineConfig, PipelineRunner, PipelineStep
from backend.rules import techniques as techniques_module
from tests.mock_provider import MockProvider


def _threat(**overrides) -> Threat:
    defaults = {
        "name": "Some threat",
        "stride_category": "Tampering",
        "description": "x " * 40,
        "target": "A service",
        "impact": "High",
        "likelihood": "Medium",
        "mitigations": ["mitigate one", "mitigate two"],
    }
    defaults.update(overrides)
    return Threat(**defaults)


class TestMapThreatTechniques:
    def test_sets_attack_techniques_on_every_threat(self):
        threats = ThreatsList(threats=[_threat(), _threat(name="Another threat")])
        result, _matched = map_threat_techniques(threats)
        assert len(result.threats) == 2
        for t in result.threats:
            assert isinstance(t.attack_techniques, list)

    def test_dependency_threat_matches_via_rule_table(self):
        threat = _threat(
            source="dependency",
            dependency_ref=DependencyRef(
                package="evil-pkg", version="1.0.0", rule_id="drift_signal"
            ),
        )
        result, matched = map_threat_techniques(ThreatsList(threats=[threat]))
        assert matched == 1
        assert result.threats[0].attack_techniques[0].id == "T1195.002"

    def test_matching_failure_on_one_threat_does_not_raise(self):
        threats = ThreatsList(threats=[_threat()])
        with patch(
            "backend.pipeline.nodes.attack_mapping.match_techniques",
            side_effect=ValueError("boom"),
        ):
            result, matched = map_threat_techniques(threats)
        assert matched == 0
        assert result.threats[0].attack_techniques == []


@pytest.mark.asyncio
class TestRunnerMapTechniquesWiring:
    async def test_map_techniques_step_runs_and_completes(self):
        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        events = [e async for e in runner.run(description="A service", framework=Framework.STRIDE)]

        map_events = [e for e in events if e.step == PipelineStep.MAP_TECHNIQUES]
        assert any(e.status == "started" for e in map_events)
        assert any(e.status == "completed" for e in map_events)
        # Runs after every other merge, before COMPLETE.
        assert events.index(map_events[-1]) < events.index(events[-1])
        assert events[-1].step == PipelineStep.COMPLETE

    async def test_threats_in_final_result_carry_attack_techniques_field(self):
        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        complete_event = None
        async for e in runner.run(description="A service", framework=Framework.STRIDE):
            if e.step == PipelineStep.COMPLETE:
                complete_event = e

        assert complete_event is not None
        final_threats = complete_event.data["threats"]
        for threat in final_threats.threats:
            assert isinstance(threat.attack_techniques, list)

    async def test_map_techniques_runs_even_when_catalog_load_fails(self):
        provider = MockProvider(gap_call_threshold=1)
        runner = PipelineRunner(
            provider=provider, config=PipelineConfig(max_iterations=1), model_id="t"
        )

        techniques_module._catalog_by_id.cache_clear()
        techniques_module._embedded_catalog.cache_clear()
        with patch(
            "backend.rules.techniques._load_catalog",
            side_effect=ValueError("catalog unavailable"),
        ):
            events = [
                e async for e in runner.run(description="A service", framework=Framework.STRIDE)
            ]
        techniques_module._load_catalog.cache_clear()
        techniques_module._catalog_by_id.cache_clear()
        techniques_module._embedded_catalog.cache_clear()

        # Pipeline must still complete despite the matching failure.
        assert events[-1].step == PipelineStep.COMPLETE
        assert events[-1].status == "completed"
