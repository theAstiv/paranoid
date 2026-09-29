"""Tests for CLI --manifest/--lockfile/--deps-source flags on `paranoid run`.

Mirrors tests/test_cli_run_code.py's style: exercises Click-level validation
without running a real pipeline (no network, no API keys).
"""

import json

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


@pytest.fixture
def fake_settings():
    """A Settings object that passes CLI config/provider setup without
    touching the network — just enough to reach the --manifest/--lockfile
    parsing block, which runs before any provider call."""
    return Settings(
        default_provider="anthropic",
        default_model="claude-sonnet-4-20250514",
        anthropic_api_key="sk-ant-test-key",
        fast_model="",
        default_iterations=1,
    )


def _patch_settings(monkeypatch, fake_settings):
    monkeypatch.setattr("cli.commands.run._load_merged_settings", lambda: fake_settings)


def test_run_manifest_rejects_nonexistent_path(runner, sample_input_file):
    result = runner.invoke(run, [str(sample_input_file), "--manifest", "/nope/package.json"])
    assert result.exit_code != 0
    assert "does not exist" in result.output.lower() or "error" in result.output.lower()


def test_run_lockfile_without_manifest_is_rejected(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    _patch_settings(monkeypatch, fake_settings)
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(json.dumps({"lockfileVersion": 3}))

    result = runner.invoke(run, [str(sample_input_file), "--lockfile", str(lockfile)])
    assert result.exit_code != 0
    assert "requires --manifest" in result.output


def test_run_invalid_manifest_json_is_rejected(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    _patch_settings(monkeypatch, fake_settings)
    manifest = tmp_path / "package.json"
    manifest.write_text("not valid json")

    result = runner.invoke(run, [str(sample_input_file), "--manifest", str(manifest)])
    assert result.exit_code != 0
    assert "invalid package.json" in result.output.lower()


def test_run_manifest_array_instead_of_object_is_rejected(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    _patch_settings(monkeypatch, fake_settings)
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps([1, 2, 3]))

    result = runner.invoke(run, [str(sample_input_file), "--manifest", str(manifest)])
    assert result.exit_code != 0
    assert "invalid package.json" in result.output.lower()


def test_run_invalid_lockfile_json_is_rejected(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    _patch_settings(monkeypatch, fake_settings)
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"lodash": "^4.17.21"}}))
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text("{broken")

    result = runner.invoke(
        run, [str(sample_input_file), "--manifest", str(manifest), "--lockfile", str(lockfile)]
    )
    assert result.exit_code != 0
    assert "invalid package-lock.json" in result.output.lower()


def test_run_deps_source_invalid_choice_is_rejected(runner, sample_input_file):
    result = runner.invoke(run, [str(sample_input_file), "--deps-source", "github"])
    assert result.exit_code != 0
    assert "invalid value" in result.output.lower() or "error" in result.output.lower()


def test_run_manifest_and_lockfile_reach_pipeline_call(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    """A valid --manifest/--lockfile pair is parsed and threaded through to
    run_pipeline_for_model (mocked here as a no-op async generator so this
    test never touches the network)."""
    _patch_settings(monkeypatch, fake_settings)
    manifest_data = {"dependencies": {"lodash": "^4.17.21"}}
    lockfile_data = {"lockfileVersion": 3}
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps(manifest_data))
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(json.dumps(lockfile_data))

    captured: dict = {}

    async def _fake_run_pipeline_for_model(*args, **kwargs):
        captured.update(kwargs)
        return
        yield  # pragma: no cover - makes this an async generator

    class _FakeBundleResult:
        is_sufficient = True
        gaps: list = []

    class _FakeBundle:
        description = _FakeBundleResult()
        assumptions = _FakeBundleResult()

    async def _fake_analyze_bundle(*args, **kwargs):
        return _FakeBundle()

    monkeypatch.setattr("cli.commands.run.run_pipeline_for_model", _fake_run_pipeline_for_model)
    monkeypatch.setattr("cli.commands.run.analyze_bundle", _fake_analyze_bundle)

    result = runner.invoke(
        run,
        [
            str(sample_input_file),
            "--manifest",
            str(manifest),
            "--lockfile",
            str(lockfile),
            "--deps-source",
            "both",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["dependency_manifest"] == manifest_data
    assert captured["dependency_lockfile"] == lockfile_data
    assert captured["dependency_source_mode"] == "both"


def test_run_manifest_sarif_export_uses_manifest_path(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    """`paranoid run --manifest apps/web/package.json --format sarif` must
    pass that real path to export_sarif() as dependency_manifest_path — not
    the "package.json" repo-root default, which would point at the wrong
    file for a monorepo package."""
    _patch_settings(monkeypatch, fake_settings)
    manifest = tmp_path / "apps" / "web" / "package.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"dependencies": {"lodash": "^4.17.21"}}))

    async def _fake_run_pipeline_for_model(*args, **kwargs):
        return
        yield  # pragma: no cover

    class _FakeBundleResult:
        is_sufficient = True
        gaps: list = []

    class _FakeBundle:
        description = _FakeBundleResult()
        assumptions = _FakeBundleResult()

    async def _fake_analyze_bundle(*args, **kwargs):
        return _FakeBundle()

    from backend.export.sarif import export_sarif as real_export_sarif

    captured_sarif_kwargs: dict = {}

    def _spy_export_sarif(*args, **kwargs):
        captured_sarif_kwargs.update(kwargs)
        return real_export_sarif(*args, **kwargs)

    monkeypatch.setattr("cli.commands.run.run_pipeline_for_model", _fake_run_pipeline_for_model)
    monkeypatch.setattr("cli.commands.run.analyze_bundle", _fake_analyze_bundle)
    monkeypatch.setattr("cli.commands.run.export_sarif", _spy_export_sarif)

    out = tmp_path / "out.sarif"
    result = runner.invoke(
        run,
        [
            str(sample_input_file),
            "--manifest",
            str(manifest),
            "--format",
            "sarif",
            "--output",
            str(out),
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured_sarif_kwargs["dependency_manifest_path"] == str(manifest).replace("\\", "/")
    assert captured_sarif_kwargs["dependency_manifest_path"].endswith("apps/web/package.json")


def test_run_manifest_too_many_resolvable_dependencies_is_rejected(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    _patch_settings(monkeypatch, fake_settings)
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {f"pkg-{i}": "1.0.0" for i in range(51)}}))

    result = runner.invoke(run, [str(sample_input_file), "--manifest", str(manifest)])
    assert result.exit_code != 0
    assert "resolves 51 direct dependencies" in result.output
    assert "limit is 50" in result.output


def test_run_manifest_dependency_count_ignores_unresolvable_ranges(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    """A git-spec entry doesn't count against the cap — the CLI's count check
    must mirror what analyze_manifest() will actually attempt, same as the
    API's identical check."""
    _patch_settings(monkeypatch, fake_settings)
    manifest_data = {
        "dependencies": {
            **{f"pkg-{i}": "1.0.0" for i in range(50)},
            "unresolvable-git-dep": "git+https://example.com/x.git",
        }
    }
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps(manifest_data))

    captured: dict = {}

    async def _fake_run_pipeline_for_model(*args, **kwargs):
        captured.update(kwargs)
        return
        yield  # pragma: no cover

    class _FakeBundleResult:
        is_sufficient = True
        gaps: list = []

    class _FakeBundle:
        description = _FakeBundleResult()
        assumptions = _FakeBundleResult()

    async def _fake_analyze_bundle(*args, **kwargs):
        return _FakeBundle()

    monkeypatch.setattr("cli.commands.run.run_pipeline_for_model", _fake_run_pipeline_for_model)
    monkeypatch.setattr("cli.commands.run.analyze_bundle", _fake_analyze_bundle)

    result = runner.invoke(run, [str(sample_input_file), "--manifest", str(manifest), "--quiet"])

    assert result.exit_code == 0, result.output
    assert captured["dependency_manifest"] == manifest_data
