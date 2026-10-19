"""`paranoid run --enrich` usage accounting (bug-bash plan §5.6, run order item 25).

Enrichment runs after the pipeline on a fresh PipelineRunner, and the run's usage
summary is taken from the pipeline's COMPLETE event before enrichment starts. The
pipeline is faked here (one COMPLETE event with two threats), so the only LLM
calls are pre-flight and enrichment, each recorded like a real provider does.
"""

import json
import sqlite3

import pytest
from click.testing import CliRunner

import backend.routes._helpers as route_helpers
import cli.commands.run as run_module
from backend.config import Settings
from backend.config import settings as global_settings
from backend.models.api import AnalyzeAssumptionsResponse, AnalyzeDescriptionResponse
from backend.models.usage import UsageRecord
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.providers.usage import build_run_usage, record_usage
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


async def _two_threat_pipeline(*args, **kwargs):
    threats = make_stride_threats()
    threats.threats = threats.threats[:2]
    yield PipelineEvent(
        step=PipelineStep.COMPLETE,
        status="completed",
        message="done",
        data={
            "threats": threats,
            "total_threats": 2,
            "usage": build_run_usage([]).model_dump(mode="json"),
        },
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Bug-bash finding (item 25): --enrich runs on a fresh PipelineRunner after "
        "run_usage is taken from the COMPLETE event, so every attack-tree and test-case "
        "call is missing from the printed summary and the saved usage_summary (and so "
        "from bench costs and refusal counts)."
    ),
)
def test_enrichment_calls_are_counted_in_the_run_usage(tmp_path, monkeypatch):
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
    monkeypatch.setattr(run_module, "create_provider", lambda *a, **k: _RecordingProvider())
    monkeypatch.setattr(route_helpers, "create_provider", lambda *a, **k: _RecordingProvider())
    monkeypatch.setattr(run_module, "run_pipeline_for_model", _two_threat_pipeline)
    system = tmp_path / "system.md"
    system.write_text("A web API with JWT login, a Postgres database and an S3 upload bucket.")

    result = CliRunner().invoke(run_module.run, [str(system), "-n", "1", "--enrich"])
    assert result.exit_code == 0, result.output
    assert "Enrichment complete: 2 attack trees, 2 test suites" in result.output

    with sqlite3.connect(tmp_path / "enrich.db") as conn:
        (raw,) = conn.execute("SELECT usage_summary FROM threat_models").fetchone()
    steps = {step["step"] for step in json.loads(raw)["steps"]}
    assert {"generate_attack_tree", "generate_test_cases"} <= steps
