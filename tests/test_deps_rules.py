"""Runs `semgrep --test` against every rule file in the dependency-scanner pack.

Each rule file (backend/deps/rules/js/<name>.yaml) has a same-named fixture
(<name>.js) next to it with ruleid:/ok:/todoruleid: annotations — Semgrep pairs
rule and fixture by basename in the same directory.

Each pair is tested in its own temporary directory rather than pointing
`semgrep --test` at the whole rules directory: with several pairs in one run,
Semgrep's concurrent test runner races on ~/.semgrep/settings.yml and crashes
with PermissionError on Windows. One pair per run avoids that, so this test
runs on every platform instead of being skipped on Windows.
"""

import shutil
import subprocess

import pytest

from backend.deps.scanner import RULES_DIR, resolve_semgrep_binary


_RULE_FILES = sorted(RULES_DIR.glob("*.yaml"))


def test_every_rule_file_has_a_fixture():
    missing = [p.name for p in _RULE_FILES if not p.with_suffix(".js").is_file()]
    assert not missing, f"Rule files without a same-named .js fixture: {missing}"


@pytest.mark.skipif(resolve_semgrep_binary() is None, reason="semgrep binary not installed")
@pytest.mark.timeout(120)
@pytest.mark.parametrize("rule_file", _RULE_FILES, ids=lambda p: p.stem)
def test_semgrep_rule_fixtures_pass(rule_file, tmp_path):
    shutil.copy(rule_file, tmp_path / rule_file.name)
    shutil.copy(rule_file.with_suffix(".js"), tmp_path / rule_file.with_suffix(".js").name)

    result = subprocess.run(  # noqa: S603
        [resolve_semgrep_binary(), "--test", "--metrics=off", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=110,
        check=False,
    )
    assert result.returncode == 0, (
        f"semgrep --test failed for {rule_file.name}:\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
