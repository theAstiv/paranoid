"""CLI edge cases from the day 3 exploratory pass (BB-117, BB-119, BB-120)."""

import json
import sqlite3

from click.testing import CliRunner

from cli.main import cli
from tests.test_cli_run_output import _invoke


def _saved_model_id(tmp_path, monkeypatch) -> str:
    result = _invoke(tmp_path, monkeypatch, [])
    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "p.db") as conn:
        (model_id,) = conn.execute("SELECT id FROM threat_models").fetchone()
    return model_id


def test_scan_manifest_on_a_json_array_is_a_clean_error(tmp_path):
    """BB-117: a JSON-array package.json tracebacked in direct_dependencies_from_manifest."""
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps([{"dependencies": {"chalk": "5.3.0"}}]))

    result = CliRunner().invoke(cli, ["deps", "scan-manifest", str(manifest)])

    assert result.exit_code == 1
    assert "expected a JSON object, got list" in result.output
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_export_creates_missing_output_directories(tmp_path, monkeypatch):
    """BB-119: `models export -o out/new/dir/f.sarif` failed on the missing dirs."""
    model_id = _saved_model_id(tmp_path, monkeypatch)
    target = tmp_path / "out" / "new" / "dir" / "f.sarif"

    result = CliRunner().invoke(
        cli, ["models", "export", model_id, "--format", "sarif", "-o", str(target)]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(target.read_text())["version"] == "2.1.0"


def test_answering_no_to_review_cancels_cleanly(tmp_path, monkeypatch):
    """BB-120: "n" printed "Unexpected error:" and exited 1."""
    model_id = _saved_model_id(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli, ["models", "review", model_id, "--status", "approved"], input="n\n"
    )

    assert result.exit_code == 0, result.output
    assert "Cancelled." in result.output
    assert "Unexpected error" not in result.output
    with sqlite3.connect(tmp_path / "p.db") as conn:
        statuses = {s for (s,) in conn.execute("SELECT status FROM threats")}
    assert "approved" not in statuses


def test_answering_yes_to_review_applies_it(tmp_path, monkeypatch):
    model_id = _saved_model_id(tmp_path, monkeypatch)

    result = CliRunner().invoke(
        cli, ["models", "review", model_id, "--status", "approved"], input="y\n"
    )

    assert result.exit_code == 0, result.output
    with sqlite3.connect(tmp_path / "p.db") as conn:
        statuses = {s for (s,) in conn.execute("SELECT status FROM threats")}
    assert statuses == {"approved"}
