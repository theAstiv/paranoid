"""Tests that `paranoid run` builds its fast provider through the single
shared builder (backend.routes._helpers.build_fast_provider), for any
provider type — not just Anthropic — following week 4a-2's de-duplication
of the CLI's previously-inline, Anthropic-only fast-provider logic.
"""

from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from backend.config import Settings
from cli.commands.run import run


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_input_file(tmp_path):
    input_file = tmp_path / "system.md"
    input_file.write_text("A document sharing web application for threat modeling")
    return input_file


def test_run_builds_openai_fast_provider_from_configured_fast_model(
    runner, sample_input_file, monkeypatch
):
    fake_settings = Settings(
        default_provider="openai",
        default_model="gpt-4.1",
        openai_api_key="sk-test",
        fast_model_openai="gpt-4.1-mini",
        default_iterations=1,
    )
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: fake_settings)

    calls: list[dict] = []

    def _fake_create(provider_type, model, **kwargs):
        calls.append({"provider_type": provider_type, "model": model, **kwargs})
        return MagicMock()

    # The CLI's main-provider construction and build_fast_provider() each
    # hold their own reference to create_provider — both must be patched.
    monkeypatch.setattr("cli.commands.run.create_provider", _fake_create)
    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)

    async def _stop_before_real_pipeline(*args, **kwargs):
        raise RuntimeError("test stops here — before any real pipeline/network call")

    monkeypatch.setattr("cli.commands.run._run_pipeline_async", _stop_before_real_pipeline)

    runner.invoke(run, [str(sample_input_file)])

    fast_calls = [c for c in calls if c["model"] == "gpt-4.1-mini"]
    assert fast_calls, f"expected a fast-provider create_provider('gpt-4.1-mini') call, got {calls}"
    assert fast_calls[0]["provider_type"] == "openai"

    main_calls = [c for c in calls if c["model"] == "gpt-4.1"]
    assert main_calls, "expected the main provider to also be built"


def test_run_skips_fast_provider_when_fast_equals_main(runner, sample_input_file, monkeypatch):
    fake_settings = Settings(
        default_provider="openai",
        default_model="gpt-4.1-mini",
        openai_api_key="sk-test",
        fast_model_openai="gpt-4.1-mini",
        default_iterations=1,
    )
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: fake_settings)

    calls: list[dict] = []

    def _fake_create(provider_type, model, **kwargs):
        calls.append({"provider_type": provider_type, "model": model, **kwargs})
        return MagicMock()

    monkeypatch.setattr("cli.commands.run.create_provider", _fake_create)
    monkeypatch.setattr("backend.routes._helpers.create_provider", _fake_create)

    async def _stop_before_real_pipeline(*args, **kwargs):
        raise RuntimeError("test stops here — before any real pipeline/network call")

    monkeypatch.setattr("cli.commands.run._run_pipeline_async", _stop_before_real_pipeline)

    runner.invoke(run, [str(sample_input_file)])

    # create_provider is called exactly once — for the main provider only.
    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-4.1-mini"
