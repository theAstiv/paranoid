"""Offline tests for backend.deps.drift — npm-tarball vs GitHub source comparison.

Builds small on-disk trees per test (no fetch/network involved) and checks that
each drift classification bucket, plus the signal computation, behaves as
documented in backend/deps/drift.py.

Every fetched directory here mirrors what `fetch_source()` actually returns:
a single wrapper directory (npm's `package/`, GitHub's `{repo}-{ref}/`)
*plus* a sibling `.complete` marker file — never just the wrapper alone.
Building fixtures without that marker was the bug this suite originally
missed: `_content_root`'s "exactly one entry" check saw two entries (the
wrapper and the marker) on every real fetch and never collapsed, so nothing
ever matched by path.
"""

import json

from backend.deps.drift import compare_sources
from backend.models.dependencies import CapabilityEvidence, CapabilityProfile
from backend.models.enums import CapabilityCategory, PathClass, SourceKind


def _profile(evidence=(), status="ok"):
    return CapabilityProfile(
        name="pkg",
        version="1.0.0",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=list(evidence),
        status=status,
    )


def _evidence(file, category, path_class=PathClass.SHIPPED):
    return CapabilityEvidence(
        category=category,
        rule_id="r",
        file=file,
        line=1,
        snippet="x",
        source_kind=SourceKind.NPM_TARBALL,
        path_class=path_class,
    )


def _fetched_dir(tmp_path, label, wrapper):
    """A fetch_source()-shaped directory: wrapper/ + a sibling .complete marker."""
    fetch_dir = tmp_path / label
    content_dir = fetch_dir / wrapper
    content_dir.mkdir(parents=True)
    (fetch_dir / ".complete").touch()
    return fetch_dir, content_dir


def test_github_unavailable_skips_comparison(tmp_path):
    tarball_dir, _ = _fetched_dir(tmp_path, "tarball", "package")
    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), None, None)
    assert report.status == "skipped_github_unavailable"
    assert report.signal is False
    assert report.matched == []


def test_scan_incomplete_skips_comparison(tmp_path):
    tarball_dir, _ = _fetched_dir(tmp_path, "tarball", "package")
    github_dir, _ = _fetched_dir(tmp_path, "github", "pkg-abc123")
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, _profile(status="semgrep_timeout"), github_dir, _profile()
    )
    assert report.status == "skipped_scan_incomplete"
    assert report.signal is False


def test_scan_incomplete_on_github_side_also_skips(tmp_path):
    tarball_dir, _ = _fetched_dir(tmp_path, "tarball", "package")
    github_dir, _ = _fetched_dir(tmp_path, "github", "pkg-abc123")
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile(status="semgrep_error")
    )
    assert report.status == "skipped_scan_incomplete"


def test_matched_file(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_text("module.exports = 1;\n")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = 1;\n")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.unexplained == []
    assert report.status == "compared"


def test_marker_file_is_not_classified_as_matched(tmp_path):
    """The sibling `.complete` marker must never leak into the comparison."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_text("module.exports = 1;\n")
    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = 1;\n")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert ".complete" not in report.matched
    assert ".complete" not in report.unexplained


def test_explained_by_sourcemap(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_text("console.log('compiled')")
    (tarball_content / "index.js.map").write_text(
        json.dumps({"sources": ["index.ts"], "sourcesContent": []})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["index.js"]
    assert report.unexplained == []


def test_explained_by_sourcemap_standard_tsc_outdir_layout(tmp_path):
    """tsc's usual `outDir: dist` / `rootDir: src` setup emits sources like
    `../src/index.ts` relative to `dist/index.js.map` — the shape the earlier
    `.lstrip("./")` bug destroyed before the ".." resolver ever saw it."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("console.log('compiled')")
    (tarball_content / "dist" / "index.js.map").write_text(
        json.dumps({"sources": ["../src/index.ts"]})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "src").mkdir()
    (github_content / "src" / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["dist/index.js"]
    assert report.unexplained == []


def test_explained_by_inline_sourcemap_comment(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_bytes(
        b"console.log('compiled')\n//# sourceMappingURL=index.js.map\n"
    )
    (tarball_content / "index.js.map").write_text(json.dumps({"sources": ["index.ts"]}))

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["index.js"]


def test_inline_sourcemap_data_uri_is_not_resolved(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_bytes(
        b"console.log('x')\n//# sourceMappingURL=data:application/json;base64,eyJ9\n"
    )
    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "other.ts").write_text("console.log('x')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.unexplained == ["index.js"]


def test_bundled_dependency_via_sourcemap(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "bundle.js").write_text("console.log('bundled')")
    (tarball_content / "bundle.js.map").write_text(
        json.dumps({"sources": ["../node_modules/left-pad/index.js"]})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("// unrelated")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.bundled_dependency == ["bundle.js"]
    assert report.unexplained == []


def test_explained_by_build_dts(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.d.ts").write_text("export {};")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.ts").write_text("export {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_build == ["index.d.ts"]
    assert report.unexplained == []


def test_explained_by_build_ts_compiled_pair(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_text("//compiled")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.ts").write_text("//source")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_build == ["index.js"]


def test_explained_by_build_declared_dist_dir_with_build_script(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("//compiled bundle, no ts pair")
    (tarball_content / "package.json").write_text(
        json.dumps({"main": "dist/index.js", "scripts": {"build": "tsc"}})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "src.js").write_text("// unrelated, no dist here")
    (github_content / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.explained_by_build


def test_explained_by_build_leading_dot_slash_main_and_bare_files_entry(tmp_path):
    """The common real-world TypeScript package shape: "main": "./dist/index.js"
    (leading "./") and "files": ["dist"] (no slash at all) — both forms must
    still resolve to "dist" as a declared build directory, or a normal
    package with no source maps gets every dist/ file marked unexplained."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("//compiled bundle, no ts pair, no map")
    (tarball_content / "package.json").write_text(
        json.dumps(
            {
                "main": "./dist/index.js",
                "files": ["dist"],
                "scripts": {"build": "tsc"},
            }
        )
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "src.ts").write_text("// unrelated, no dist here")
    (github_content / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.explained_by_build
    assert "dist/index.js" not in report.unexplained


def test_explained_by_build_via_exports_field(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.mjs").write_text("//compiled esm bundle")
    (tarball_content / "package.json").write_text(
        json.dumps(
            {
                "exports": {".": {"import": "./dist/index.mjs", "require": "./dist/index.cjs"}},
                "scripts": {"prepare": "tsc"},
            }
        )
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "src.ts").write_text("// unrelated, no dist here")
    (github_content / "package.json").write_text(json.dumps({"scripts": {"prepare": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.mjs" in report.explained_by_build


def test_build_dir_not_declared_stays_unexplained(tmp_path):
    """A conventionally-named directory (lib/) that package.json never
    declares as its build output (main/module/types/files) must not be
    explained away just because *some* build script exists — otherwise an
    injected file dropped into a source-carrying lib/ directory is hidden."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "lib").mkdir()
    (tarball_content / "lib" / "evil.js").write_text("require('child_process').exec('x')")
    (tarball_content / "package.json").write_text(
        json.dumps({"main": "index.js", "scripts": {"build": "webpack --config docs.config.js"}})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "lib/evil.js" in report.unexplained
    assert "lib/evil.js" not in report.explained_by_build


def test_unexplained_without_build_script(tmp_path):
    """The same dist/ layout, but no build script declared — no longer explained."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("//mystery file")
    (tarball_content / "package.json").write_text(json.dumps({"main": "dist/index.js"}))

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "readme.md").write_text("nothing relevant")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.unexplained


def test_signal_true_for_unexplained_file_with_novel_category(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "payload.js").write_text("require('child_process').exec('evil')")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("package/payload.js", CapabilityCategory.PROCESS)])
    github_profile = _profile()  # no process capability anywhere in the GitHub scan

    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unexplained == ["payload.js"]
    assert report.signal is True
    assert report.unexplained_categories == [CapabilityCategory.PROCESS]


def test_signal_false_when_category_also_present_on_github(tmp_path):
    """A benign refactor: the tarball has an unexplained file, but its capability
    category is already present in the GitHub-scanned source elsewhere — no signal."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "generated.js").write_text("require('child_process').exec('build step')")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "build.js").write_text("require('child_process').exec('build step')")

    tarball_profile = _profile([_evidence("package/generated.js", CapabilityCategory.PROCESS)])
    github_profile = _profile([_evidence("build.js", CapabilityCategory.PROCESS)])

    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unexplained == ["generated.js"]
    assert report.signal is False
    assert report.unexplained_categories == []


def test_signal_false_when_unexplained_file_has_no_evidence(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "notes.txt").write_text("just some notes, no capability")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.unexplained == ["notes.txt"]
    assert report.signal is False


def test_node_modules_excluded_from_both_trees(tmp_path):
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "node_modules" / "left-pad").mkdir(parents=True)
    (tarball_content / "node_modules" / "left-pad" / "index.js").write_text("vendored")
    (tarball_content / "index.js").write_text("module.exports = {};")

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.unexplained == []


def test_package_json_build_script_detected_despite_wrapper(tmp_path):
    """package.json lookup must find the file inside the wrapper directory on
    *both* sides — not at the fetch dir's top level (where fetch_source never
    puts it) — since declared build dirs come from the tarball's package.json
    and the build-script check comes from the GitHub repo's."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("//compiled, no ts pair")
    (tarball_content / "package.json").write_text(json.dumps({"main": "dist/index.js"}))
    # Sanity: no package.json at the fetch dir's top level.
    assert not (tarball_dir / "package.json").exists()

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "readme.md").write_text("n/a")
    (github_content / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))
    assert not (github_dir / "package.json").exists()

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.explained_by_build


def test_build_script_read_from_github_not_tarball(tmp_path):
    """The attacker controls the published tarball's package.json — a build
    script declared only there must not make anything self-certify."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "dist").mkdir()
    (tarball_content / "dist" / "index.js").write_text("//compiled, no ts pair")
    (tarball_content / "package.json").write_text(
        json.dumps({"main": "dist/index.js", "scripts": {"build": "tsc"}})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "readme.md").write_text("n/a")
    # No package.json / build script in the actual repo.

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.unexplained
    assert "dist/index.js" not in report.explained_by_build


def test_root_level_file_not_explained_by_bare_files_entry(tmp_path):
    """A root-level injected file must not be waved through just because its
    bare name matches a "files" entry or "main" — the build-folder rule only
    covers files *inside* a declared directory (the event-stream shape)."""
    tarball_dir, tarball_content = _fetched_dir(tmp_path, "tarball", "package")
    (tarball_content / "index.js").write_text("module.exports = {};")
    (tarball_content / "payload.js").write_text("require('child_process').exec('evil')")
    (tarball_content / "package.json").write_text(
        json.dumps({"files": ["index.js", "payload.js"], "scripts": {"build": "tsc"}})
    )

    github_dir, github_content = _fetched_dir(tmp_path, "github", "pkg-abc123")
    (github_content / "index.js").write_text("module.exports = {};")
    (github_content / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "payload.js" in report.unexplained
    assert "payload.js" not in report.explained_by_build
