"""scripts/build_test.py run_command() (BB-93).

It used to pass `check` twice to subprocess.run (TypeError for any caller that
set it) and ignore it otherwise, so a failing step passed silently.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_test.py"
_spec = importlib.util.spec_from_file_location("build_test_script", _SCRIPT)
build_test = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_test)


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_a_passing_command_returns_its_result():
    result = build_test.run_command(_python("print('ok')"), capture=True)
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"


def test_a_failing_command_raises_by_default():
    with pytest.raises(subprocess.CalledProcessError) as info:
        build_test.run_command(_python("import sys; sys.exit(3)"))
    assert info.value.returncode == 3


def test_check_false_returns_the_failure_instead_of_raising():
    result = build_test.run_command(_python("import sys; sys.exit(3)"), check=False)
    assert result.returncode == 3


def test_check_true_passed_explicitly_raises():
    with pytest.raises(subprocess.CalledProcessError):
        build_test.run_command(_python("import sys; sys.exit(1)"), check=True, capture=True)


def test_output_that_is_not_valid_in_the_locale_is_decoded():
    """The binary's output (✓, ✗, box drawing) broke a cp1252 decode on Windows."""
    code = "import sys; sys.stdout.buffer.write('\\u2713 done \\u2500'.encode('utf-8'))"
    result = build_test.run_command(_python(code), capture=True)
    assert "✓ done ─" in result.stdout
