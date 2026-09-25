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
    (github_dir / "package.json").write_text(json.dumps({"dependencies": {}}))

    tarball_profile = _profile([_evidence("evil.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.signal is True
    assert "evil.js" in report.signal_files


def test_case_2_fake_map_to_unrelated_real_file_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "evil.js.map").write_text(json.dumps({"sources": ["totally-unrelated.ts"]}))
    github_dir = _fetched_dir(tmp_path, "github")
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
    (github_dir / "index.js").write_text("module.exports = {};")

    tarball_profile = _profile([_evidence("index.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert report.matched == ["index.js"]
    assert report.signal is True
    assert report.signal_files == {"index.js": [CapabilityCategory.PROCESS]}


def test_case_4_payload_appended_to_matched_file_category_already_elsewhere_is_weak(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "index.js").write_text("require('child_process').exec('a');")
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "index.js").write_text("module.exports = {};")
    (github_dir / "build.js").write_text("require('child_process').exec('elsewhere');")

    tarball_profile = _profile([_evidence("index.js", CapabilityCategory.PROCESS)])
    github_profile = _profile([_evidence("build.js", CapabilityCategory.PROCESS)])
    report = compare_sources(
        "pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, github_profile
    )
    assert report.matched == ["index.js"]
    assert report.signal is False
    assert report.relocated == [{"file": "index.js", "categories": [CapabilityCategory.PROCESS]}]


def test_case_5_novel_capability_in_declared_build_dir_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "dist").mkdir()
    (tarball_dir / "dist" / "evil.js").write_text("require('child_process').exec('evil')")
    (tarball_dir / "package.json").write_text(
        json.dumps({"main": "dist/index.js", "scripts": {"build": "tsc"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src.ts").write_text("export {};")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

    tarball_profile = _profile([_evidence("dist/evil.js", CapabilityCategory.PROCESS)])
    report = compare_sources("pkg", "1.0.0", tarball_dir, tarball_profile, github_dir, _profile())
    assert "dist/evil.js" in report.explained_by_build
    assert report.signal is True
    assert "dist/evil.js" in report.signal_files


def test_case_6_tarball_only_postinstall_is_strong_signal(tmp_path):
    tarball_dir = _fetched_dir(tmp_path, "tarball")
    (tarball_dir / "package.json").write_text(
        json.dumps({"scripts": {"postinstall": "node scripts/setup.js"}})
    )
    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "package.json").write_text(json.dumps({"scripts": {}}))

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
    (tarball_dir / "package.json").write_text(json.dumps({"main": "dist/index.js"}))

    github_dir = _fetched_dir(tmp_path, "github")
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
    (tarball_dir / "package.json").write_text(json.dumps({"main": "bundle.js"}))

    github_dir = _fetched_dir(tmp_path, "github")
    (github_dir / "src").mkdir()
    (github_dir / "src" / "index.js").write_text("module.exports = require('left-pad');")
    (github_dir / "package.json").write_text(json.dumps({"dependencies": {"left-pad": "^1.0.0"}}))

    report = compare_sources("pkg", "1.0.0", tarball_dir, _profile(), github_dir, _profile())
    assert report.bundled_dependency == ["bundle.js"]
    assert report.signal is False
