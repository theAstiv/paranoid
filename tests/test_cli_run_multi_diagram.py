"""Tests for the repeatable `--diagram/-d` CLI flag (Week 5a-1).

Mirrors test_cli_run_scoring_method.py's pattern: stubs _run_pipeline_async
so the test only verifies CLI argument wiring, not the full pipeline.
"""

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


def test_no_diagram_flag_gives_empty_tuple(monkeypatch, sample_input_file):
    result, captured = _invoke(monkeypatch, sample_input_file, [])
    assert result.exit_code == 0, result.output
    assert captured["diagram_paths"] == ()


def test_single_diagram_flag_behaves_as_before(monkeypatch, sample_input_file, tmp_path):
    diagram = tmp_path / "a.mmd"
    diagram.write_text("graph TD; A-->B")
    result, captured = _invoke(monkeypatch, sample_input_file, ["--diagram", str(diagram)])
    assert result.exit_code == 0, result.output
    assert captured["diagram_paths"] == (diagram,)


def test_repeated_short_flag_loads_two_paths(monkeypatch, sample_input_file, tmp_path):
    first = tmp_path / "a.mmd"
    first.write_text("graph TD; A-->B")
    second = tmp_path / "b.png"
    second.write_bytes(b"\x89PNG\r\n\x1a\n")  # content isn't loaded at this stage

    result, captured = _invoke(
        monkeypatch, sample_input_file, ["-d", str(first), "-d", str(second)]
    )
    assert result.exit_code == 0, result.output
    assert captured["diagram_paths"] == (first, second)


def test_nonexistent_diagram_path_rejected_by_click(monkeypatch, sample_input_file):
    result, _ = _invoke(monkeypatch, sample_input_file, ["-d", "/definitely/nonexistent.mmd"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# _load_cli_diagrams — name sanitization (load_diagram_file names a diagram
# after the raw file stem; nothing sanitized it before this fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_cli_diagrams_sanitizes_long_name_with_ampersand(tmp_path):
    from cli.commands.run import _load_cli_diagrams

    unsafe_stem = "a & b  [prod] " + "0" * 90
    diagram = tmp_path / f"{unsafe_stem}.mmd"
    diagram.write_text("graph TD; A-->B")

    diagrams_data = await _load_cli_diagrams((diagram,), quiet=True)

    assert len(diagrams_data) == 1
    name = diagrams_data[0].name
    assert "&" not in name
    assert "  " not in name
    assert len(name) <= 80


@pytest.mark.asyncio
async def test_load_cli_diagrams_empty_paths_returns_empty_list(tmp_path):
    from cli.commands.run import _load_cli_diagrams

    assert await _load_cli_diagrams((), quiet=True) == []
