"""Unit tests for backend.deps.references — deterministic require()/import
reachability, no Semgrep involved."""

from pathlib import Path

from backend.deps.references import find_reachable_files, find_reachable_unscanned_files
from backend.deps.scanner import classify_path


def _write(root: Path, rel_path: str, text: str) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_require_promotes_test_file(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./test/payload');")
    _write(tmp_path, "test/payload.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "test/payload.js" in promoted
    assert promoted["test/payload.js"] == "index.js"


def test_esm_import_promotes_file(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "import payload from './examples/payload.js';")
    _write(tmp_path, "examples/payload.js", "export default {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "examples/payload.js" in promoted


def test_export_from_promotes_file(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "export * from './docs/helpers.js';")
    _write(tmp_path, "docs/helpers.js", "export function f() {}")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "docs/helpers.js" in promoted


def test_side_effect_import_promotes_file(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "import './test/setup.js';")
    _write(tmp_path, "test/setup.js", "console.log('side effect');")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "test/setup.js" in promoted


def test_index_resolution_without_extension(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./test/helpers');")
    _write(tmp_path, "test/helpers/index.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "test/helpers/index.js" in promoted


def test_cycle_terminates(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./test/a.js');")
    _write(tmp_path, "test/a.js", "require('./b.js');")
    _write(tmp_path, "test/b.js", "require('./a.js');")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert set(promoted) == {"test/a.js", "test/b.js"}


def test_nonliteral_require_stays_unresolved(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require(pluginPath);")
    _write(tmp_path, "test/payload.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert promoted == {}


def test_unreferenced_test_file_not_promoted(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "module.exports = {};")
    _write(tmp_path, "test/unused.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert promoted == {}


def test_entry_point_itself_is_promoted_when_not_shipped_classified(tmp_path):
    """A declared entry point that lives under a TEST/EXAMPLE/BUILD-classified
    path is itself promoted, with via="package.json" — not just files it
    goes on to require()."""
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "examples/cli.js"}')
    _write(tmp_path, "examples/cli.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert promoted.get("examples/cli.js") == "package.json"


def test_relative_root_does_not_crash(tmp_path, monkeypatch):
    """`find_reachable_files` must not raise when given a relative root —
    `_resolve()` always resolves candidates to an absolute path, so `root`
    itself has to be resolved too or every relative_to() comparison raises."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path, "rel_pkg/package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "rel_pkg/index.js", "require('./lib/a.js');")
    _write(tmp_path, "rel_pkg/lib/a.js", "module.exports = {};")

    promoted = find_reachable_files(Path("rel_pkg"), classify_path)

    # lib/a.js is SHIPPED-classified so it isn't "promoted" — the point of
    # this test is that scanning a relative root doesn't raise at all.
    assert promoted == {}


def test_entry_point_from_exports_field(tmp_path):
    """The declared entry point ("exports") is itself outside the SHIPPED
    file list that `find_reachable_files` seeds from — it can only be found
    by resolving package.json, isolating that code path from the "every
    SHIPPED file is already an entry" behavior exercised by the other tests."""
    _write(
        tmp_path,
        "package.json",
        '{"name": "pkg", "exports": {".": {"require": "./test/entry.js"}}}',
    )
    _write(tmp_path, "test/entry.js", "require('../examples/x.js');")
    _write(tmp_path, "examples/x.js", "module.exports = {};")

    promoted = find_reachable_files(tmp_path, classify_path)

    assert "examples/x.js" in promoted


def test_find_reachable_unscanned_files_finds_non_js_extension(tmp_path):
    """`require('./lib/data.map')` is real, executable code from Node's point
    of view regardless of the `.map` extension — this is what lets the
    scanner pass it to Semgrep as an explicit extra target even though a
    directory scan would otherwise skip it entirely."""
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./lib/data.map');")
    _write(tmp_path, "lib/data.map", "require('child_process').exec('evil');")

    unscanned = find_reachable_unscanned_files(tmp_path, classify_path)

    assert unscanned == {"lib/data.map"}


def test_find_reachable_unscanned_files_ignores_standard_extensions(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./lib/util.js'); require('./data.json');")
    _write(tmp_path, "lib/util.js", "module.exports = {};")
    _write(tmp_path, "data.json", "{}")

    unscanned = find_reachable_unscanned_files(tmp_path, classify_path)

    assert unscanned == set()


def test_find_reachable_unscanned_files_unreferenced_file_not_included(tmp_path):
    """A `.map` file that's just an ordinary sourcemap sibling — never
    `require()`'d as code — must not show up here at all."""
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "console.log(1);\n//# sourceMappingURL=index.js.map")
    _write(tmp_path, "index.js.map", '{"sources": ["index.ts"]}')

    unscanned = find_reachable_unscanned_files(tmp_path, classify_path)

    assert unscanned == set()


def test_find_reachable_unscanned_files_extensionless_file(tmp_path):
    _write(tmp_path, "package.json", '{"name": "pkg", "main": "index.js"}')
    _write(tmp_path, "index.js", "require('./bin/cli');")
    _write(tmp_path, "bin/cli", "require('child_process').exec('evil');")

    unscanned = find_reachable_unscanned_files(tmp_path, classify_path)

    assert unscanned == {"bin/cli"}
