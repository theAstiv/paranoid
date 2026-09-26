"""Obfuscation/evasion regression suite for the Semgrep-backed capability scanner.

Real Semgrep, one package per row. Each row is a one-line obfuscation shape
found during the 2026-09-26 robustness check (see the PR F plan): a naive
scanner looking only for `require("literal")`, `eval(...)`, `new Function(...)`
and similarly-named globals misses all of them. The fix isn't to resolve what
the obfuscated code loads (that's not statically possible in general) — it's
to flag that the code is *deliberately hiding* what it loads, by treating the
evasion shape itself as `dynamic_code`/`native_ffi` evidence.

Two kinds of table live here, and they are NOT interchangeable:

- `_DETECTION_ROWS` (`test_evasion_shape`): evasion shapes that should be
  flagged. A row with an `accepted_miss_reason` is a shape we deliberately
  don't catch, with the reason recorded; if the scanner starts detecting it,
  that's an improvement — move the row out of the accepted-miss state.
- `_PRECISION_ROWS` (`test_known_benign_pattern_is_not_flagged`): ordinary,
  legitimate code that must never be flagged. If one of these starts firing,
  that is a REGRESSION — a rule became too broad — and the fix is to narrow
  the rule, never to "accept" the new detection. Keeping these in the same
  table/test as the evasion rows would make a regression here look like a
  successful catch; that mix-up is exactly what this split avoids.
"""

from pathlib import Path

import pytest

from backend.deps import scanner
from backend.models.enums import CapabilityCategory, SourceKind


_semgrep_missing = scanner.resolve_semgrep_binary() is None

pytestmark = [
    pytest.mark.skipif(_semgrep_missing, reason="semgrep binary not installed"),
    pytest.mark.timeout(120),
]

# Categories that count as "the scanner noticed something suspicious here" —
# a row passes if at least one of these shows up in the SHIPPED category set.
_SIGNAL_CATEGORIES = frozenset(
    {
        CapabilityCategory.DYNAMIC_CODE,
        CapabilityCategory.PROCESS,
        CapabilityCategory.NETWORK,
        CapabilityCategory.NATIVE_FFI,
    }
)

# (label, source snippet, reason if this is an accepted, documented miss)
_DETECTION_ROWS: list[tuple[str, str, str | None]] = [
    (
        "concatenated-require",
        "require('child_' + 'process');\n",
        None,
    ),
    (
        "concatenated-require-chained-call",
        # The existing process-child-process-call rule requires an exact
        # literal match on the module name and does NOT fire here — Semgrep
        # folds 'child_' + 'process' for metavariable-regex on that rule's
        # $MOD, but the fold doesn't make the regex match in this position
        # (confirmed directly: this call produces zero process-category
        # findings). Nothing is silently lost overall, though: the require()
        # sub-expression itself is still matched by
        # dynamic-code-concatenated-require regardless of what wraps it, so
        # this is caught as dynamic_code rather than process.
        "require('child_' + 'process').execSync('ls');\n",
        None,
    ),
    (
        "aliased-require",
        "const r = require;\nr('child_process');\n",
        None,
    ),
    (
        "bundler-wrapper-non-numeric-require",
        # A prior version of dynamic-code-nonliteral-require excluded any
        # require() call from inside a function whose parameters shadow the
        # name `require` (meant to fix the qs.js browserify-bundle false
        # positive). That exclusion was itself a bypass: it hid a real,
        # non-numeric require() smuggled in through a parameter named
        # `require`. The numeric-id exclusion alone is what actually fixes
        # qs.js (dist/qs.js's local require() only ever takes numeric ids);
        # there is no wrapper-shape exclusion any more, so this must fire.
        "(function (require) { require(moduleName); })(require);\n",
        None,
    ),
    (
        "computed-global-call-bracket-key",
        "module['req' + 'uire']('child_process');\n",
        None,
    ),
    (
        "aliased-function-indirect-call",
        "(0, Function)('return require')();\n",
        None,
    ),
    (
        "aliased-function-bare-call",
        # `Function(...)` called directly (no `new`, no `(0, ...)`
        # misdirection) constructs and can invoke a function from a string
        # exactly like `new Function(...)` does.
        "const payload = 'return process.env';\nFunction(payload)();\n",
        None,
    ),
    (
        "concatenated-require-three-part",
        # The left side ('chi' + 'ld_') is itself a concatenation, not a
        # plain literal — pins that Semgrep's own constant folding still
        # lets the both-literal-only pattern (require("..." + "...")) match
        # a nested fold, so this isn't a one-step bypass.
        "require('chi' + 'ld_' + 'process');\n",
        None,
    ),
    (
        "computed-global-call-three-part",
        "globalThis['f' + 'et' + 'ch']('http://example.com');\n",
        None,
    ),
    (
        "aliased-function-try-catch-bypass",
        # Regression case: an earlier version of dynamic-code-aliased-
        # function excluded any aliased-Function call wrapped in try/catch,
        # to match the get-intrinsic shim's shape (see the precision table
        # below). That was itself a bypass: wrapping a real payload call in
        # the same try/catch silenced it too. The exclusion now matches the
        # shim's exact argument shape instead, so this must fire.
        "const F = Function;\ntry {\n  F(payload)();\n} catch (e) {}\n",
        None,
    ),
    (
        "computed-global-fetch",
        "globalThis['fe' + 'tch']('http://example.com');\n",
        None,
    ),
    (
        "process-binding",
        "process.binding('fs');\n",
        None,
    ),
    (
        "eval-base64",
        "eval(Buffer.from('cHJvY2Vzcy5leGl0KCk7', 'base64').toString());\n",
        None,
    ),
    (
        "variable-key-indirection",
        "const k = 'fetch';\nglobalThis[k]('http://example.com');\n",
        "a bare-identifier computed key (`obj[k]`, no concatenation) is "
        "indistinguishable from ordinary, common computed-property access — "
        "flagging every such call would swamp real findings with noise on "
        "normal code (config[key](), handlers[eventName](), ...). Only the "
        "literal-plus-literal concatenation shape (deliberately built to "
        "dodge a plain-string match, and not achievable by accident) is "
        "targeted.",
    ),
    (
        "chained-computed-global-access",
        "const m = global['proc' + 'ess'].mainModule;\nm.require('child_process');\n",
        "dynamic-code-computed-global-call only fires when the built "
        "property is called directly (`$O[$A + $B](...)`) — it doesn't "
        "follow a computed property into a further chain of accesses "
        "before the eventual call. Handling every possible chain shape "
        "(and knowing where the chain ends) is unbounded; the direct-call "
        "shape covers the common obfuscation pattern.",
    ),
    (
        "destructured-require-alias",
        "const { r: myRequire } = { r: require };\nmyRequire('child_process');\n",
        "destructuring an object literal built specifically to alias "
        "`require` under a different key (`{ r: require }`) is not matched "
        "by dynamic-code-aliased-require, which only recognizes a direct "
        "`$R = require` assignment/declaration. Listed here per the PR F "
        "plan's 'if cheap' scope for this specific shape — not implemented.",
    ),
]

# (label, source snippet, reason this must never fire)
_PRECISION_ROWS: list[tuple[str, str, str]] = [
    (
        "aliased-function-benign-shim",
        (
            "var $Function = Function;\n"
            "var getEvalledConstructor = function (expressionSyntax) {\n"
            "  try {\n"
            "    return $Function('\"use strict\"; return (' + expressionSyntax "
            "+ ').constructor;')();\n"
            "  } catch (e) {}\n"
            "};\n"
        ),
        "the get-intrinsic/es-abstract/has-property-descriptors "
        "getEvalledConstructor shim — a real, live-benchmark false positive "
        "this rule was narrowed to fix. A `Function` alias called with this "
        "exact fixed template-string shape, purely to feature-detect a "
        "working strict-mode Function constructor. Bundled by a large "
        "fraction of the npm dependency graph.",
    ),
    (
        "computed-global-ternary-event-listener",
        "window[(on ? 'add' : 'remove') + 'EventListener'](type, handler);\n",
        "ordinary, common browser code (feature-toggled add/removeEvent"
        "Listener). Constant-foldable to a string (both ternary branches "
        "are literals), which is exactly why dynamic-code-computed-global-"
        "call checks each operand's raw syntax for a real string literal "
        "instead of relying on Semgrep's string-literal pattern or "
        "metavariable-pattern, both of which treat a foldable ternary as "
        "equivalent to a literal.",
    ),
    (
        "function-return-this-shim",
        "const globalObj = Function('return this')();\n",
        "the single most common benign use of a bare Function(...) call — "
        "lodash, core-js and many other packages use this exact shape to "
        "reach the global object across environments.",
    ),
    (
        "regenerator-runtime-shim",
        'Function("r", "regeneratorRuntime = r")(runtime);\n',
        "regenerator-runtime's global-assignment shim, shipped in nearly "
        "every Babel-transpiled bundle that uses async/generator functions "
        "— a real, live-benchmark false positive this rule was narrowed to "
        "fix.",
    ),
    (
        "function-bind-polyfill-shim",
        'r = Function("binder", "return function (" + joiny(i, ",") '
        '+ "){ return binder.apply(this,arguments); }");\n',
        "the function-bind polyfill's arity-matching trampoline — a fixed "
        "prefix/suffix template with only a generated, safe argument-name "
        "list in the middle. Found live in qs's bundled dependency (a "
        "real, live-benchmark false positive this rule was narrowed to "
        "fix).",
    ),
]


def _write_package(tmp_path: Path, label: str, body: str) -> Path:
    pkg_dir = tmp_path / label
    pkg_dir.mkdir()
    (pkg_dir / "package.json").write_text(
        f'{{"name": "{label}", "version": "1.0.0", "main": "index.js"}}\n',
        encoding="utf-8",
    )
    (pkg_dir / "index.js").write_text(body, encoding="utf-8")
    return pkg_dir


async def _scan_snippet(tmp_path: Path, label: str, body: str):
    pkg_dir = _write_package(tmp_path, label, body)
    return await scanner.scan_source(pkg_dir, SourceKind.NPM_TARBALL, name=label, version="1.0.0")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "body", "accepted_miss_reason"),
    _DETECTION_ROWS,
    ids=[r[0] for r in _DETECTION_ROWS],
)
async def test_evasion_shape(tmp_path, label, body, accepted_miss_reason):
    profile = await _scan_snippet(tmp_path, label, body)

    assert profile.status == "ok", f"{label}: scan did not complete cleanly ({profile.status})"
    categories = profile.category_set()
    detected = bool(categories & _SIGNAL_CATEGORIES)

    if accepted_miss_reason is not None:
        assert not detected, (
            f"{label} was expected to be an accepted miss ({accepted_miss_reason}) "
            f"but the scanner now detects it as {sorted(c.value for c in categories)} "
            "— this is an improvement: move this row out of the accepted-misses "
            "list (drop the reason) rather than treating it as a failure."
        )
        return

    assert detected, (
        f"{label}: expected at least one of "
        f"{sorted(c.value for c in _SIGNAL_CATEGORIES)}, got "
        f"{sorted(c.value for c in categories)}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "body", "must_not_fire_reason"),
    _PRECISION_ROWS,
    ids=[r[0] for r in _PRECISION_ROWS],
)
async def test_known_benign_pattern_is_not_flagged(tmp_path, label, body, must_not_fire_reason):
    profile = await _scan_snippet(tmp_path, label, body)

    assert profile.status == "ok", f"{label}: scan did not complete cleanly ({profile.status})"
    categories = profile.category_set()
    detected = bool(categories & _SIGNAL_CATEGORIES)

    assert not detected, (
        f"REGRESSION: {label} is now flagged as {sorted(c.value for c in categories)}, but "
        f"this is known-benign code that must never fire ({must_not_fire_reason}). "
        "The fix is to narrow the rule that fired, not to accept this detection."
    )
