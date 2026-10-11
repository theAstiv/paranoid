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


def test_run_sarif_output_uses_forward_slash_uris(
    runner, sample_input_file, tmp_path, monkeypatch, fake_settings
):
    """On Windows `str(Path)` has backslashes, which are not valid in a SARIF
    artifact URI and don't resolve on GitHub — for both the threat results and
    the description-completeness findings the CLI appends itself."""
    _patch_settings(monkeypatch, fake_settings)

    async def _fake_run_pipeline_for_model(*args, **kwargs):
        return
        yield  # pragma: no cover

    class _Gap:
        severity = "error"
        field = "authentication"
        message = "no described authentication"

    class _FakeBundleResult:
        is_sufficient = False
        gaps = [_Gap()]

    class _EmptyResult:
        is_sufficient = True
        gaps: list = []

    class _FakeBundle:
        description = _FakeBundleResult()
        assumptions = _EmptyResult()

    async def _fake_analyze_bundle(*args, **kwargs):
        return _FakeBundle()

    monkeypatch.setattr("cli.commands.run.run_pipeline_for_model", _fake_run_pipeline_for_model)
    monkeypatch.setattr("cli.commands.run.analyze_bundle", _fake_analyze_bundle)

    out = tmp_path / "out.sarif"
    result = runner.invoke(
        run,
        [str(sample_input_file), "--format", "sarif", "--output", str(out), "--quiet"],
    )
    assert result.exit_code == 0, result.output

    uris = [
        loc["physicalLocation"]["artifactLocation"]["uri"]
        for res in json.loads(out.read_text(encoding="utf-8"))["runs"][0]["results"]
        for loc in res["locations"]
        if "physicalLocation" in loc
    ]
    assert uris, "expected at least the description-completeness finding"
    assert all("\\" not in uri for uri in uris), uris


def test_run_sarif_source_file_is_cwd_relative_for_an_absolute_input_path(
    runner, tmp_path, monkeypatch, fake_settings
):
    """Regression test: moving PR D's default/validation logic into
    export_sarif() briefly made every absolute input path (what the GitHub
    Action always passes) fall back to the fixed 'threat-model.md' anchor
    instead of resolving to the real description file. The CLI's own
    source_file must never be sanitized/defaulted away — only made
    repo-relative — since it's a real filesystem path this process just
    read, not untrusted input."""
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    _patch_settings(monkeypatch, fake_settings)

    repo_dir = tmp_path / "repo"
    docs_dir = repo_dir / "docs"
    docs_dir.mkdir(parents=True)
    input_file = docs_dir / "system.md"
    input_file.write_text("A document sharing web application for threat modeling")

    async def _fake_run_pipeline_for_model(*args, **kwargs):
        return
        yield  # pragma: no cover

    class _EmptyResult:
        is_sufficient = True
        gaps: list = []

    class _FakeBundle:
        description = _EmptyResult()
        assumptions = _EmptyResult()

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
    monkeypatch.chdir(repo_dir)

    out = tmp_path / "out.sarif"
    result = runner.invoke(
        run,
        [str(input_file), "--format", "sarif", "--output", str(out), "--quiet"],
    )
    assert result.exit_code == 0, result.output
    assert captured_sarif_kwargs["source_file"] == "docs/system.md"


def test_repo_relative_source_file_resolves_against_cwd(tmp_path, monkeypatch):
    """Unit-level check of the helper itself: an absolute path under the
    current directory resolves relative to it."""
    from cli.commands.run import _repo_relative_source_file

    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    repo_dir = tmp_path / "repo"
    (repo_dir / "docs").mkdir(parents=True)
    input_file = repo_dir / "docs" / "system.md"
    input_file.write_text("x")
    monkeypatch.chdir(repo_dir)

    assert _repo_relative_source_file(input_file) == "docs/system.md"


def test_repo_relative_source_file_resolves_against_github_workspace(tmp_path, monkeypatch):
    """With GITHUB_WORKSPACE set (running as the Action), an absolute path
    under it resolves relative to the workspace root, not cwd."""
    from cli.commands.run import _repo_relative_source_file

    workspace = tmp_path / "workspace"
    (workspace / "docs").mkdir(parents=True)
    input_file = workspace / "docs" / "system.md"
    input_file.write_text("x")
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    monkeypatch.chdir(tmp_path)  # cwd is deliberately NOT the workspace

    assert _repo_relative_source_file(input_file) == "docs/system.md"


def test_repo_relative_source_file_falls_back_when_outside_both(tmp_path, monkeypatch):
    """A path under neither GITHUB_WORKSPACE nor cwd falls back to the path
    as given (forward-slashed), rather than raising."""
    from cli.commands.run import _repo_relative_source_file, to_sarif_uri

    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    input_file = elsewhere / "system.md"
    input_file.write_text("x")

    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)

    assert _repo_relative_source_file(input_file) == to_sarif_uri(input_file.resolve())
