"""Live pipeline tests: seeded inputs, dual-framework MAESTRO seeding, zero-threat
detection, and debug logging — the Week 1 gaps `tests/test_pipeline_e2e.py` doesn't
cover (that file predates --seeded-*, the MAESTRO seeded-context fix, and
zero-threat detection).

Requires a real ANTHROPIC_API_KEY (set in .env or the environment) and is
excluded by default (`-m "not live"` in pyproject.toml). Run explicitly:

    pytest -m live tests/live/test_pipeline_live.py -v
"""

import logging
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

import backend.pipeline.nodes as nodes_module
from backend.export.sarif import export_sarif
from backend.models.enums import Framework, StrideCategory
from backend.models.state import (
    Asset,
    AssetsList,
    AssetType,
    DreadScore,
    FlowsList,
    Threat,
    ThreatsList,
)
from backend.pipeline.runner import PipelineEvent, PipelineStep, run_pipeline_for_model
from backend.providers import create_provider


_dotenv = dotenv_values(Path(__file__).parent.parent.parent / ".env")
_api_key = _dotenv.get("ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.timeout(1800),
    pytest.mark.skipif(
        not _api_key or _api_key.startswith("sk-ant-xxx"),
        reason="Live pipeline tests require a real ANTHROPIC_API_KEY (set in .env or environment)",
    ),
]

_DESCRIPTION = (
    "A web application with a React frontend, a FastAPI backend, and a PostgreSQL "
    "database. Users authenticate via JWT. The backend calls a third-party payment "
    "API over HTTPS."
)
_NONSENSE_DESCRIPTION = "purple mango velocity seventeen umbrella think blue"


def _seeded_assets() -> AssetsList:
    return AssetsList(
        assets=[
            Asset(type=AssetType.ASSET, name="User database", description="PostgreSQL instance"),
        ]
    )


def _seeded_flows() -> FlowsList:
    return FlowsList(data_flows=[], trust_boundaries=[], threat_sources=[])


def _seeded_threats() -> ThreatsList:
    return ThreatsList(
        threats=[
            Threat(
                name="Seeded JWT replay",
                stride_category=StrideCategory.SPOOFING,
                description=(
                    "An attacker who intercepts a valid JWT can replay it before "
                    "expiry to impersonate the original user against the backend API."
                ),
                target="Authentication",
                impact="High",
                likelihood="Medium",
                dread=DreadScore(
                    damage=7.5,
                    reproducibility=5,
                    exploitability=5,
                    affected_users=5,
                    discoverability=5,
                ),
                mitigations=["Short-lived tokens", "Bind tokens to client fingerprint"],
            )
        ]
    )


@pytest.fixture
def anthropic_provider():
    return create_provider(
        provider_type="anthropic",
        model=_dotenv.get("DEFAULT_MODEL", "claude-sonnet-4-20250514"),
        api_key=_api_key,
        max_retries=2,
        timeout=120.0,
    )


async def _run(provider, framework, *, max_iterations=1, has_ai_components=False, **seeds):
    events: list[PipelineEvent] = []
    async for event in run_pipeline_for_model(
        model_id="live-test",
        description=_DESCRIPTION,
        framework=framework,
        provider=provider,
        max_iterations=max_iterations,
        has_ai_components=has_ai_components,
        **seeds,
    ):
        events.append(event)
    return events


def _complete_event(events: list[PipelineEvent]) -> PipelineEvent:
    final = events[-1]
    assert final.step == PipelineStep.COMPLETE
    assert final.status == "completed"
    return final


# ---------------------------------------------------------------------------
# 1. Seeded assets/flows/threats survive into the run and into exports,
#    and extraction steps are skipped when seeded input is provided.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_seeded_inputs_survive_run_and_exports(anthropic_provider):
    events = await _run(
        anthropic_provider,
        Framework.STRIDE,
        max_iterations=1,
        seeded_assets=_seeded_assets(),
        seeded_flows=_seeded_flows(),
        seeded_threats=_seeded_threats(),
    )

    step_statuses = [(e.step, e.status) for e in events]
    # Extraction steps must not run when seeded input was supplied.
    assert (PipelineStep.EXTRACT_ASSETS, "started") not in step_statuses
    assert (PipelineStep.EXTRACT_FLOWS, "started") not in step_statuses

    final = _complete_event(events)
    threats: ThreatsList = final.data["threats"]
    seeded = [t for t in threats.threats if t.source == "seeded"]
    assert seeded, "seeded threat did not survive into the completed catalog"
    assert seeded[0].name == "Seeded JWT replay"

    sarif = export_sarif(threats, model_id="live-test", framework="stride")
    sarif_sources = {
        r["properties"]["threatName"]: r["properties"].get("source")
        for r in sarif["runs"][0]["results"]
    }
    assert sarif_sources.get("Seeded JWT replay") == "seeded", (
        "seeded threat's source did not survive into the SARIF export"
    )


# ---------------------------------------------------------------------------
# 2. Dual STRIDE + AI-components (MAESTRO) run with seeded threats — the
#    fix in fix/maestro-seeded-context (runner.py) is that MAESTRO's
#    iteration-1 call receives seeds/prior threats the same way STRIDE's does.
#    `has_ai_components=True` alongside `framework=STRIDE` is what triggers
#    the combined STRIDE+MAESTRO pass (runner.py: `if has_ai_components and
#    framework == Framework.STRIDE`) — framework=MAESTRO alone runs MAESTRO
#    only and never exercises the dual-framework code path this fix is in.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_maestro_seeded_iteration_one_receives_seeds(anthropic_provider, monkeypatch):
    # Seeds reaching the *final* catalog proves nothing about this fix on its
    # own — dedup appends unmatched seeds regardless of whether MAESTRO's
    # iteration-1 call ever saw them. Spy on nodes.generate_threats (the exact
    # call site runner.py:563 makes) and inspect what `existing_threats` it
    # was actually invoked with, then delegate to the real implementation so
    # the run still executes normally against the live API.
    calls: list[dict] = []
    original_generate_threats = nodes_module.generate_threats

    async def _spy(*args, **kwargs):
        calls.append(
            {
                "framework": kwargs.get("framework"),
                "existing_threats": kwargs.get("existing_threats"),
            }
        )
        return await original_generate_threats(*args, **kwargs)

    monkeypatch.setattr(nodes_module, "generate_threats", _spy)

    await _run(
        anthropic_provider,
        Framework.STRIDE,
        max_iterations=1,
        has_ai_components=True,
        seeded_threats=_seeded_threats(),
    )

    maestro_calls = [c for c in calls if c["framework"] == Framework.MAESTRO]
    assert maestro_calls, "MAESTRO's generate_threats was never called"
    existing = maestro_calls[0]["existing_threats"]
    assert existing is not None, "MAESTRO iteration 1 was called with existing_threats=None"
    assert existing.threats, "MAESTRO iteration 1's existing_threats had no threats"
    assert any(t.name == "Seeded JWT replay" for t in existing.threats), (
        "MAESTRO iteration 1 received existing_threats but not the seeded threat"
    )


# ---------------------------------------------------------------------------
# 3. Zero-threat path: a nonsense description over 3 iterations should
#    surface zero_threats warning events without the pipeline erroring out.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_zero_threat_path_emits_warning_events(anthropic_provider, monkeypatch):
    # A nonsense description does NOT reliably make a capable model return zero
    # threats (the rule engine also contributes independently of the LLM), so
    # gating the assertion on total_threats==0 made this a near-permanent
    # no-op. Stub only the threat-generation node to deterministically return
    # nothing — extract_assets/extract_flows/summarize still make real calls
    # against the live API, so this still exercises the real pipeline/runner
    # machinery, just with a guaranteed zero-threat LLM response.
    async def _empty_threats(*args, **kwargs):
        return ThreatsList(threats=[])

    monkeypatch.setattr(nodes_module, "generate_threats", _empty_threats)

    events = []
    async for event in run_pipeline_for_model(
        model_id="live-test-zero",
        description=_NONSENSE_DESCRIPTION,
        framework=Framework.STRIDE,
        provider=anthropic_provider,
        max_iterations=3,
    ):
        events.append(event)

    _complete_event(events)
    zero_threat_events = [e for e in events if e.data and e.data.get("warning") == "zero_threats"]
    assert zero_threat_events, "generate_threats returned nothing but no zero_threats event fired"


# ---------------------------------------------------------------------------
# 4. LOG_LEVEL=debug: start/iteration/dedup/complete log lines are present.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_debug_logging_emits_lifecycle_lines(anthropic_provider, caplog, monkeypatch):
    # The env var -> Settings wiring and the DEBUG/ERROR gating mechanism
    # itself are covered deterministically and offline in
    # tests/test_logging_config.py (no need to duplicate that here, and no
    # need for a live API call to prove it). This test only needs to confirm
    # that with LOG_LEVEL=debug's *effect* applied — the root logger's level
    # set to DEBUG, exactly what backend/main.py's `logging.basicConfig(level=
    # settings.log_level.upper())` does — the runner's real lifecycle lines
    # come through against a live run.
    #
    # `caplog.set_level(logging.DEBUG)` (no `logger=` arg) sets the ROOT
    # logger's level, letting backend.pipeline.runner's logger inherit it —
    # unlike `caplog.at_level(level, logger=...)`, which forces that specific
    # logger's level directly and would make this assertion pass even under
    # LOG_LEVEL=error, since it bypasses the inheritance being tested here.
    monkeypatch.setenv("LOG_LEVEL", "debug")
    from backend.config import Settings

    assert Settings().log_level == "debug", "LOG_LEVEL env var was not picked up by Settings"

    caplog.set_level(logging.DEBUG)
    await _run(anthropic_provider, Framework.STRIDE, max_iterations=2)

    messages = "\n".join(r.message for r in caplog.records)
    assert "Pipeline started" in messages
    assert "Iteration 1/2 started" in messages
    assert "dedup" in messages
    assert "Pipeline complete" in messages
