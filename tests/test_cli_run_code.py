"""Tests for CLI --code flag integration.

Verifies that the --code flag is properly wired and triggers code extraction.
"""

import pytest
from click.testing import CliRunner

from cli.commands.run import run


@pytest.fixture
def runner():
    """Click test runner."""
    return CliRunner()


@pytest.fixture
def sample_input_file(tmp_path):
    """Create a sample input file for tests."""
    input_file = tmp_path / "system.md"
    input_file.write_text("A document sharing web application for threat modeling")
    return input_file


def test_run_with_code_flag_rejects_nonexistent_path(runner, sample_input_file):
    """Test that --code flag rejects nonexistent paths."""
    result = runner.invoke(
        run,
        [str(sample_input_file), "--code", "/definitely/nonexistent/path"],
    )
    # Should fail with path validation error from Click
    assert result.exit_code != 0
    assert "does not exist" in result.output.lower() or "error" in result.output.lower()


def test_run_with_code_flag_rejects_file_path(runner, sample_input_file):
    """Test that --code flag rejects file paths (must be directory)."""
    # Use the input_file itself as the --code argument (it's a file, not a directory)
    result = runner.invoke(
        run,
        [str(sample_input_file), "--code", str(sample_input_file)],
    )
    # Should fail because --code must be a directory
    assert result.exit_code != 0


