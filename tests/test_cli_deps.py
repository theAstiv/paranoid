"""CLI tests for `paranoid deps` — resolver/fetcher/scanner are mocked, so
these never touch the network or run Semgrep."""

import json

import pytest
from click.testing import CliRunner

import cli.commands.deps as deps_cli
from backend.models.dependencies import CapabilityEvidence, CapabilityProfile, ResolvedPackage
from backend.models.enums import CapabilityCategory, PathClass, SourceKind


@pytest.fixture
def runner():
    return CliRunner()


def _resolved(name="pkg", version="1.0.0", github_status="not_attempted", **kwargs):
    return ResolvedPackage(
        name=name,
        version=version,
        tarball_url=f"https://registry.npmjs.org/{name}/-/{name}-{version}.tgz",
        integrity="sha512-AAAA",
        github_status=github_status,
        **kwargs,
    )


def _profile(name="pkg", version="1.0.0", categories=(), install_hooks=()):
    evidence = [
        CapabilityEvidence(
            category=c,
            rule_id="r",
            file="index.js",
            line=1,
            snippet="x",
            source_kind=SourceKind.NPM_TARBALL,
            path_class=PathClass.SHIPPED,
        )
        for c in categories
    ]
    return CapabilityProfile(
        name=name,
        version=version,
        source_kind=SourceKind.NPM_TARBALL,
        evidence=evidence,
        install_hooks=list(install_hooks),
        capability_vector=list(categories),
        status="ok",
    )


def test_scan_rejects_bare_name_without_version(runner):
    result = runner.invoke(deps_cli.deps, ["scan", "chalk"])
    assert result.exit_code == 2
    assert "NAME@VERSION" in result.output or "version" in result.output.lower()


def test_scan_json_round_trip(runner, monkeypatch, tmp_path):
    resolved = _resolved(github_status="resolved", github_ref="v1.0.0")
    profile = _profile(categories=[CapabilityCategory.NETWORK])

    async def fake_resolve_npm(name, version, client):
        return resolved

    async def fake_resolve_github_ref(r, client):
        return resolved

    async def fake_fetch_source(r, kind, client):
        source_dir = tmp_path / kind.value
        source_dir.mkdir(parents=True, exist_ok=True)
        (source_dir / "index.js").write_text("module.exports = {};")
        return source_dir

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "resolve_github_ref", fake_resolve_github_ref)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan", "pkg@1.0.0", "--format", "json"])
    assert result.exit_code == 0, result.output

    data = json.loads(result.output)
    assert data["name"] == "pkg"
    assert data["version"] == "1.0.0"
    assert data["github_status"] == "resolved"
    assert data["npm"]["capability_vector"] == ["network"]
    assert data["github"]["capability_vector"] == ["network"]
    # Both sources scanned into the same fake dirs -> drift compares identical
    # trees, so nothing is unexplained and there's no signal.
    assert data["drift"]["status"] == "compared"
    assert data["drift"]["signal"] is False


def test_scan_source_both_github_unavailable_warns_and_stays_npm_only(
    runner, monkeypatch, tmp_path
):
    resolved = _resolved(github_status="unavailable")
    profile = _profile(categories=[CapabilityCategory.FILESYSTEM])

    async def fake_resolve_npm(name, version, client):
        return resolved

    async def fake_resolve_github_ref(r, client):
        return resolved

    async def fake_fetch_source(r, kind, client):
        if kind == SourceKind.GITHUB:
            return None
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "resolve_github_ref", fake_resolve_github_ref)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan", "pkg@1.0.0", "--source", "both"])
    assert result.exit_code == 0, result.output
    assert "GitHub source unavailable — drift skipped." in result.output
    assert "(not scanned)" in result.output  # GitHub capability grid has nothing to show


def test_scan_warns_when_semgrep_missing(runner, monkeypatch, tmp_path):
    resolved = _resolved()
    profile = _profile(categories=())

    async def fake_resolve_npm(name, version, client):
        return resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: None)

    result = runner.invoke(deps_cli.deps, ["scan", "pkg@1.0.0", "--source", "npm"])
    assert result.exit_code == 0, result.output
    assert "Semgrep not found" in result.output


def test_diff_two_explicit_versions(runner, monkeypatch, tmp_path):
    prev_resolved = _resolved(version="1.0.0", publisher="alice")
    curr_resolved = _resolved(version="1.0.1", publisher="alice")
    prev_profile = _profile(version="1.0.0", categories=[])
    curr_profile = _profile(version="1.0.1", categories=[CapabilityCategory.NETWORK])

    async def fake_resolve_npm(name, version, client):
        return prev_resolved if version == "1.0.0" else curr_resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / kind.value / r.version

    async def fake_scan_source(path, kind, *, name, version):
        return prev_profile if version == "1.0.0" else curr_profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["diff", "pkg", "1.0.0", "1.0.1", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["delta"]["previous_version"] == "1.0.0"
    assert data["delta"]["current_version"] == "1.0.1"
    assert data["delta"]["categories_added"] == ["network"]
    assert data["drift"] is None  # --source defaults to npm-only for diff


def test_diff_defaults_previous_version_from_registry(runner, monkeypatch, tmp_path):
    prev_resolved = _resolved(version="1.0.0")
    curr_resolved = _resolved(version="1.0.1")
    profile = _profile(categories=[])

    async def fake_fetch_registry_doc(name, client):
        return {"time": {"1.0.0": "2024-01-01T00:00:00.000Z", "1.0.1": "2024-02-01T00:00:00.000Z"}}

    async def fake_resolve_npm(name, version, client):
        return prev_resolved if version == "1.0.0" else curr_resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm" / r.version

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "fetch_registry_doc", fake_fetch_registry_doc)
    monkeypatch.setattr(
        deps_cli, "previous_version", lambda doc, before: "1.0.0" if before == "1.0.1" else None
    )
    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["diff", "pkg", "1.0.1", "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["delta"]["previous_version"] == "1.0.0"
    assert data["delta"]["current_version"] == "1.0.1"


def test_diff_raises_when_no_previous_version_found(runner, monkeypatch):
    async def fake_fetch_registry_doc(name, client):
        return {"time": {}}

    monkeypatch.setattr(deps_cli, "fetch_registry_doc", fake_fetch_registry_doc)
    monkeypatch.setattr(deps_cli, "previous_version", lambda doc, before: None)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["diff", "pkg", "1.0.1"])
    assert result.exit_code != 0
    assert "No published version before" in result.output


def test_scan_manifest_v3_lockfile(runner, monkeypatch, tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"chalk": "^5.3.0"}}))
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(json.dumps({"packages": {"node_modules/chalk": {"version": "5.3.0"}}}))

    resolved = _resolved(name="chalk", version="5.3.0")
    profile = _profile(name="chalk", version="5.3.0", categories=[CapabilityCategory.PROCESS])

    async def fake_resolve_npm(name, version, client):
        assert version == "5.3.0"  # confirms the lockfile pin was used, not the ^ range
        return resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan-manifest", str(manifest), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["scanned"]["chalk"]["version"] == "5.3.0"
    assert data["scanned"]["chalk"]["npm"]["capability_vector"] == ["process"]
    assert data["skipped"] == []


def test_scan_manifest_v1_lockfile(runner, monkeypatch, tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"chalk": "^5.3.0"}}))
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(json.dumps({"dependencies": {"chalk": {"version": "5.3.0"}}}))

    resolved = _resolved(name="chalk", version="5.3.0")
    profile = _profile(name="chalk", version="5.3.0")

    async def fake_resolve_npm(name, version, client):
        assert version == "5.3.0"
        return resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan-manifest", str(manifest), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["scanned"]["chalk"]["version"] == "5.3.0"


def test_scan_manifest_falls_back_to_range_pin_without_lockfile(runner, monkeypatch, tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"chalk": "^5.3.0", "weird": "git+https://x"}}))

    resolved = _resolved(name="chalk", version="5.3.0")
    profile = _profile(name="chalk", version="5.3.0")

    async def fake_resolve_npm(name, version, client):
        assert version == "5.3.0"
        return resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan-manifest", str(manifest), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "chalk" in data["scanned"]
    assert data["skipped"] == ["weird"]


def test_scan_manifest_no_dependencies_errors(runner, tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"name": "pkg"}))

    result = runner.invoke(deps_cli.deps, ["scan-manifest", str(manifest)])
    assert result.exit_code != 0
    assert "No dependencies found" in result.output


@pytest.mark.parametrize(
    ("range_str", "expected"),
    [
        ("^5.3.0", "5.3.0"),
        ("~5.3.0", "5.3.0"),
        ("5.3.0", "5.3.0"),
        ("1.2.3-beta.1", "1.2.3-beta.1"),
        # Ranges with no single resolvable version must be skipped, not
        # truncated into a version-shaped prefix (the un-anchored regex bug).
        ("1.2.3 - 2.0.0", None),
        ("1.2.3 || 2.0.0", None),
        (">=1.2.3 <2.0.0", None),
        ("*", None),
        ("git+https://example.com/pkg.git", None),
        ("workspace:*", None),
    ],
)
def test_pin_from_range(range_str, expected):
    assert deps_cli._pin_from_range(range_str) == expected


def test_scan_manifest_isolates_one_dependency_failure(runner, monkeypatch, tmp_path):
    """One dependency raising an unexpected error must not abort the whole sweep."""
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"good": "1.0.0", "bad": "1.0.0"}}))

    good_resolved = _resolved(name="good", version="1.0.0")
    good_profile = _profile(name="good", version="1.0.0")

    async def fake_resolve_npm(name, version, client):
        if name == "bad":
            raise OSError("simulated cache move failure")
        return good_resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm"

    async def fake_scan_source(path, kind, *, name, version):
        return good_profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["scan-manifest", str(manifest), "--format", "json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["scanned"]["good"]["version"] == "1.0.0"
    assert "OSError" in data["scanned"]["bad"]["error"]


def test_diff_refuses_when_previous_scan_incomplete(runner, monkeypatch, tmp_path):
    prev_resolved = _resolved(version="1.0.0")
    curr_resolved = _resolved(version="1.0.1")
    prev_profile = _profile(version="1.0.0")
    prev_profile = prev_profile.model_copy(update={"status": "semgrep_timeout"})
    curr_profile = _profile(version="1.0.1", categories=[CapabilityCategory.NETWORK])

    async def fake_resolve_npm(name, version, client):
        return prev_resolved if version == "1.0.0" else curr_resolved

    async def fake_fetch_source(r, kind, client):
        return tmp_path / "npm" / r.version

    async def fake_scan_source(path, kind, *, name, version):
        return prev_profile if version == "1.0.0" else curr_profile

    monkeypatch.setattr(deps_cli, "resolve_npm", fake_resolve_npm)
    monkeypatch.setattr(deps_cli, "fetch_source", fake_fetch_source)
    monkeypatch.setattr(deps_cli, "scan_source", fake_scan_source)
    monkeypatch.setattr(deps_cli, "resolve_semgrep_binary", lambda: "/usr/bin/semgrep")

    result = runner.invoke(deps_cli.deps, ["diff", "pkg", "1.0.0", "1.0.1"])
    assert result.exit_code != 0
    assert "refusing to diff" in result.output.lower()
