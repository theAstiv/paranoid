"""Obfuscation/evasion regression suite for the Semgrep-backed capability scanner.

Real Semgrep, one package per row. Each row is a one-line obfuscation shape
found during the 2026-09-26 robustness check (see the PR F plan): a naive
scanner looking only for `require("literal")`, `eval(...)`, `new Function(...)`
and similarly-named globals misses all of them. The fix isn't to resolve what
the obfuscated code loads (that's not statically possible in general) — it's
to flag that the code is *deliberately hiding* what it loads, by treating the
evasion shape itself as `dynamic_code`/`native_ffi` evidence.

A row that stays an accepted miss says so explicitly, with a reason, rather
than silently passing — see the third element of each `_ROWS` entry below.
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
_ROWS: list[tuple[str, str, str | None]] = [
    (
        "concatenated-require",
        "require('child_' + 'process');\n",
        None,
    ),
    (
        "aliased-require",
        "const r = require;\nr('child_process');\n",
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
        "a bare-identifier computed key (`obj[k]`, no concatenation/template) is "
        "indistinguishable from ordinary, common computed-property access — "
        "flagging every such call would swamp real findings with noise on "
        "normal code (config[key](), handlers[eventName](), ...). Only the "
        "concatenation/template-literal shape (deliberately built to dodge a "
        "plain-string match) is targeted.",
    ),
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
        "getEvalledConstructor shim — real, live benchmark false positive "
        "(see the PR F description): a `Function` alias called with a fixed "
        "template string, guarded by try/catch, purely to feature-detect a "
        "working strict-mode Function constructor. This exact shape is "
        "bundled by a large fraction of the npm dependency graph.",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "body", "accepted_miss_reason"), _ROWS, ids=[r[0] for r in _ROWS]
)
async def test_evasion_shape(tmp_path, label, body, accepted_miss_reason):
    pkg_dir = _write_package(tmp_path, label, body)
    profile = await scanner.scan_source(
        pkg_dir, SourceKind.NPM_TARBALL, name=label, version="1.0.0"
    )

    assert profile.status == "ok", f"{label}: scan did not complete cleanly ({profile.status})"
    categories = profile.category_set()
    detected = bool(categories & _SIGNAL_CATEGORIES)

    if accepted_miss_reason is not None:
        assert not detected, (
            f"{label} was expected to be an accepted miss ({accepted_miss_reason}) "
            f"but the scanner now detects it as {sorted(c.value for c in categories)} "
            "— update this test to move it out of the accepted-misses list."
        )
        return

    assert detected, (
        f"{label}: expected at least one of "
        f"{sorted(c.value for c in _SIGNAL_CATEGORIES)}, got "
        f"{sorted(c.value for c in categories)}"
    )
