"""The CLI in a directory with no ./data (BB-91: a wheel installed into an empty dir).

Nothing but `ConnectionManager.initialize()` creates the database's directory,
so `paranoid run` must save and `paranoid models list` must list from a cwd
that has never seen a run. The pipeline is faked (one COMPLETE event).
"""

import json

from click.testing import CliRunner

import backend.routes._helpers as route_helpers
import cli.commands.run as run_module
from backend.config import Settings
from backend.config import settings as global_settings
from backend.models.api import AnalyzeAssumptionsResponse, AnalyzeDescriptionResponse
from backend.pipeline.runner import PipelineEvent, PipelineStep
from backend.providers.usage import build_run_usage
from cli.commands.models import models
from tests.fixtures.pipeline import make_stride_threats
from tests.mock_provider import MockProvider


class _PreFlightProvider(MockProvider):
    """Answers the pre-flight checks; the faked pipeline makes no other calls."""

    async def generate_structured(self, *args, **kwargs):
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


def test_run_then_models_list_in_a_directory_without_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path = "./data/paranoid.db"  # the default, relative to the cwd
    cli_settings = Settings(
        default_provider="anthropic",
        default_model="claude-mock",
        anthropic_api_key="sk-test",
        fast_model="",
        default_iterations=1,
        db_path=db_path,
    )
    provider = _PreFlightProvider()
    monkeypatch.setattr(run_module, "_load_merged_settings", lambda: cli_settings)
    monkeypatch.setattr(global_settings, "db_path", db_path)
    monkeypatch.setattr(run_module, "create_provider", lambda *a, **k: provider)
    monkeypatch.setattr(route_helpers, "create_provider", lambda *a, **k: provider)
    monkeypatch.setattr(run_module, "build_fast_provider", lambda *a, **k: None)
    monkeypatch.setattr(run_module, "run_pipeline_for_model", _two_threat_pipeline)
    (tmp_path / "system.md").write_text(
        "A web API with JWT login, a Postgres database and an S3 upload bucket."
    )
    assert not (tmp_path / "data").exists()

    result = CliRunner().invoke(run_module.run, ["system.md", "-n", "1"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "data" / "paranoid.db").is_file()

    listed = CliRunner().invoke(models, ["list", "--json"])
    assert listed.exit_code == 0, listed.output
    saved = json.loads(listed.output)
    assert len(saved) == 1
    assert saved[0]["threat_count"] == 2
