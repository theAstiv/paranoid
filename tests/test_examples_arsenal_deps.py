"""Static checks on the Arsenal demo fixtures under examples/arsenal-deps/.

No network, no Semgrep, no LLM — just validates that the manifest/lockfile
are well-formed and stay within the limits `analyze_manifest()` and the API
route enforce, so the demo fixture can't silently drift out of bounds as
dependencies are bumped.
"""

import json
from pathlib import Path

from backend.deps.analyze import (
    DEFAULT_MAX_DIRECT_DEPENDENCIES,
    count_resolvable_direct_dependencies,
    direct_dependencies_from_manifest,
    parse_lockfile_versions,
)
from backend.deps.fetcher import _SAFE_NAME_RE, _SAFE_VERSION_RE


FIXTURE_DIR = Path(__file__).parent.parent / "examples" / "arsenal-deps"


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_fixture_files_exist():
    for name in ("description.md", "package.json", "package-lock.json", "inject_incident.py"):
        assert (FIXTURE_DIR / name).exists(), f"missing {name}"


def test_manifest_and_lockfile_parse():
    manifest = _load("package.json")
    lockfile = _load("package-lock.json")
    direct = direct_dependencies_from_manifest(manifest)
    assert direct, "manifest must declare at least one direct dependency"

    versions = parse_lockfile_versions(lockfile)
    assert set(direct) <= set(versions), "every manifest dependency must be pinned in the lockfile"


def test_resolvable_dependency_count_within_cap():
    manifest = _load("package.json")
    lockfile = _load("package-lock.json")
    resolvable = count_resolvable_direct_dependencies(manifest, lockfile)
    assert 0 < resolvable <= DEFAULT_MAX_DIRECT_DEPENDENCIES


def test_lockfile_versions_pass_safe_identifier_regexes():
    manifest = _load("package.json")
    lockfile = _load("package-lock.json")
    versions = parse_lockfile_versions(lockfile)
    for name in direct_dependencies_from_manifest(manifest):
        version = versions[name]
        assert _SAFE_NAME_RE.match(name), f"{name!r} fails the npm-shaped name regex"
        assert _SAFE_VERSION_RE.match(version), f"{version!r} fails the safe version regex"


def test_reconstructed_incident_version_passes_safe_version_regex():
    # The harness always labels the fixture 3.3.6-reconstructed — confirm it
    # would pass cache_dir_for()'s validation if it ever reached that path.
    assert _SAFE_VERSION_RE.match("3.3.6-reconstructed")
