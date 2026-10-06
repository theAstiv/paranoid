"""Tests for `paranoid run --scoring-method` (Week 4b-3)."""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from backend.config import Settings
from cli.commands.run import run


@pytest.fixture
def sample_input_file(tmp_path):
    input_file = tmp_path / "system.md"
    input_file.write_text("A document sharing web application for threat modeling")
    return input_file


def _invoke(monkeypatch, sample_input_file, args):
    """Run the CLI up to (not into) the pipeline; return (result, captured)."""
    settings = Settings(
        default_provider="anthropic",
        default_model="claude-sonnet-5",
        anthropic_api_key="sk-ant-test",
        default_iterations=1,
    )
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: settings)

    def _fake_create(provider_type, model, **kwargs):
        provider = MagicMock()
        provider.model = model
        return provider

    monkeypatch.setattr("cli.commands.run.create_provider", _fake_create)
    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)

    captured: dict = {}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("cli.commands.run._run_pipeline_async", _capture)
    result = CliRunner().invoke(run, [str(sample_input_file), *args])
    return result, captured


def test_scoring_method_defaults_to_dread(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, [])
    assert result.exit_code == 0, result.output
    assert captured["scoring_method"] == "dread"


def test_scoring_method_flag_reaches_the_pipeline(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, ["--scoring-method", "cvss"])
    assert result.exit_code == 0, result.output
    assert captured["scoring_method"] == "cvss"


def test_scoring_method_both(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, ["--scoring-method", "both"])
    assert result.exit_code == 0, result.output
    assert captured["scoring_method"] == "both"


def test_scoring_method_rejects_invalid_choice(monkeypatch, sample_input_file):
    result, _ = _invoke(monkeypatch, sample_input_file, ["--scoring-method", "nope"])
    assert result.exit_code != 0
