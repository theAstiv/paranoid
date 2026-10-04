"""Tests for `paranoid run --fast-model` and `--step-model` (week 4a-3)."""

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


def _invoke(monkeypatch, sample_input_file, args, **settings_kwargs):
    """Run the CLI up to (not into) the pipeline; return (result, captured)."""
    base = {
        "default_provider": "anthropic",
        "default_model": "claude-sonnet-5",
        "anthropic_api_key": "sk-ant-test",
        "fast_model": "claude-haiku-4-5",
        "default_iterations": 1,
    }
    base.update(settings_kwargs)
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: Settings(**base))

    created: list[str] = []

    def _fake_create(provider_type, model, **kwargs):
        created.append(model)
        provider = MagicMock()
        provider.model = model
        return provider

    monkeypatch.setattr("cli.commands.run.create_provider", _fake_create)
    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)

    captured: dict = {"created": created}

    async def _capture(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("cli.commands.run._run_pipeline_async", _capture)
    result = CliRunner().invoke(run, [str(sample_input_file), *args])
    return result, captured


def test_fast_model_flag_overrides_the_active_providers_fast_model(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, ["--fast-model", "claude-haiku-9"])
    assert result.exit_code == 0, result.output
    assert captured["fast_provider"].model == "claude-haiku-9"
    assert captured["settings"].fast_model == "claude-haiku-9"
    assert "Fast model: claude-haiku-9" in result.output


def test_fast_model_flag_applies_to_non_anthropic_providers(monkeypatch, sample_input_file):
    result, captured = _invoke(
        monkeypatch,
        sample_input_file,
        ["--fast-model", "gpt-4.1-nano"],
        default_provider="openai",
        default_model="gpt-4.1",
        openai_api_key="sk-test",
    )
    assert result.exit_code == 0, result.output
    assert captured["settings"].fast_model_openai == "gpt-4.1-nano"
    assert captured["fast_provider"].model == "gpt-4.1-nano"


def test_empty_fast_model_flag_disables_routing(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, ["--fast-model", ""])
    assert result.exit_code == 0, result.output
    assert captured["fast_provider"] is None
    assert captured["created"] == ["claude-sonnet-5"]
    assert "Fast model: off" in result.output


def test_step_model_flags_replace_settings_step_models(monkeypatch, sample_input_file):
    result, captured = _invoke(
        monkeypatch,
        sample_input_file,
        ["--step-model", "extract_flows=main", "--step-model", "summarize=fast"],
        step_models={"extract_assets": "main"},
    )
    assert result.exit_code == 0, result.output
    assert captured["settings"].step_models == {"extract_flows": "main", "summarize": "fast"}
    assert "Step models: extract_flows=main, summarize=fast" in result.output


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("generate_threats=fast", "can never be routed to the fast model"),
        ("gap_analysis=fast", "can never be routed to the fast model"),
        ("no_such_step=main", "Unknown pipeline step"),
        ("extract_flows=medium", "must be 'fast' or 'main'"),
        ("extract_flows", "STEP=fast|main"),
    ],
)
def test_invalid_step_model_flag_exits_with_a_clear_error(
    monkeypatch, sample_input_file, value, message
):
    result, captured = _invoke(monkeypatch, sample_input_file, ["--step-model", value])
    assert result.exit_code == 2
    assert message in result.output
    assert "settings" not in captured  # never reached the pipeline


def test_no_routing_flags_keeps_settings_untouched(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, [])
    assert result.exit_code == 0, result.output
    assert captured["settings"].fast_model == "claude-haiku-4-5"
    assert captured["settings"].step_models == {}
    assert captured["fast_provider"].model == "claude-haiku-4-5"
    assert "Step models:" not in result.output
