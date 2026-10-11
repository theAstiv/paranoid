"""The application version has one source (backend/__init__.py), pinned to
pyproject.toml so a release bump can't leave the CLI, API or SARIF behind."""

import tomllib
from pathlib import Path

from click.testing import CliRunner

from backend import __version__
from backend.config import VERSION
from backend.export.sarif import export_sarif
from backend.models.state import ThreatsList
from cli.main import cli


PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_matches_pyproject():
    with PYPROJECT.open("rb") as f:
        assert __version__ == tomllib.load(f)["project"]["version"]


def test_config_version_is_the_same_value():
    assert __version__ == VERSION


def test_cli_version_option_reports_package_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"paranoid, version {__version__}"


def test_sarif_tool_version_is_package_version():
    sarif = export_sarif(threats=ThreatsList(threats=[]), model_id="m", framework="STRIDE")
    assert sarif["runs"][0]["tool"]["driver"]["version"] == __version__
