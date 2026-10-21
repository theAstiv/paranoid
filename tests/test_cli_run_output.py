"""`paranoid run` with and without -o (BB-94).

No file is written without -o (the docs used to promise
{input_basename}_threats.json); the run says where the result went instead.
The pipeline is faked (one COMPLETE event).
"""

from click.testing import CliRunner

import backend.routes._helpers as route_helpers
import cli.commands.run as run_module
from backend.config import Settings
from backend.config import settings as global_settings
from tests.test_cli_data_dir import _PreFlightProvider, _two_threat_pipeline


def _invoke(tmp_path, monkeypatch, args: list[str]):
    monkeypatch.chdir(tmp_path)
    db_path = str(tmp_path / "p.db")
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
    return CliRunner().invoke(run_module.run, ["system.md", "-n", "1", *args])


def test_without_output_no_file_is_written_and_the_run_says_how_to_export(tmp_path, monkeypatch):
    result = _invoke(tmp_path, monkeypatch, [])
    assert result.exit_code == 0, result.output
    assert "Saved as model " in result.output
    assert "paranoid models export " in result.output
    assert "--format full" in result.output
    assert not list(tmp_path.glob("*_threats.*"))


def test_the_hint_names_the_chosen_format(tmp_path, monkeypatch):
    result = _invoke(tmp_path, monkeypatch, ["--format", "sarif", "-q"])
    assert result.exit_code == 0, result.output
    assert "--format sarif" in result.output


def test_with_output_the_file_is_written_and_no_hint(tmp_path, monkeypatch):
    result = _invoke(tmp_path, monkeypatch, ["-o", "out/threats.json"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "out" / "threats.json").is_file()
    assert "Saved as model " not in result.output


def test_output_help_says_no_file_without_it():
    result = CliRunner().invoke(run_module.run, ["--help"])
    assert "_threats.json" not in result.output
    assert "Without -o no file is written" in " ".join(result.output.split())
