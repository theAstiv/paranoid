"""Tests for cli/async_runner.py and the CLI's exit behaviour.

The in-process tests check that run_async() closes the shared DB connection
on every exit path. The subprocess tests check the user-visible symptom it
fixes: `paranoid models ...` printing its result and then never exiting,
because aiosqlite's non-daemon threads kept the interpreter alive. Only a
real process can show that, so those tests spawn one (skipped where
sqlite-vec can't be loaded, since the CLI's DB init requires it).
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cli.async_runner import run_async
from cli.errors import CLIError


REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def close_spy(monkeypatch):
    from backend.db.connection import db

    spy = AsyncMock()
    monkeypatch.setattr(db, "close", spy)
    return spy


def test_run_async_returns_result_and_closes_db(close_spy):
    async def _ok():
        return 42

    assert run_async(_ok()) == 42
    close_spy.assert_awaited_once()


def test_run_async_closes_db_when_command_raises(close_spy):
    async def _fail():
        raise CLIError("boom")

    with pytest.raises(CLIError):
        run_async(_fail())
    close_spy.assert_awaited_once()


def test_run_async_closes_db_on_system_exit(close_spy):
    """`paranoid run --strict` exits with SystemExit(2) from inside the coroutine."""

    async def _exit():
        raise SystemExit(2)

    with pytest.raises(SystemExit):
        run_async(_exit())
    close_spy.assert_awaited_once()


def _sqlite_vec_loadable() -> bool:
    try:
        import sqlite_vec

        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        conn.load_extension(sqlite_vec.loadable_path())
        conn.close()
    except (ImportError, AttributeError, sqlite3.Error):
        return False
    return True


needs_sqlite_vec = pytest.mark.skipif(
    not _sqlite_vec_loadable(), reason="sqlite-vec can't be loaded by this Python"
)


def _run_cli(tmp_path: Path, *args: str, encoding: str | None = None):
    env = {**os.environ, "DB_PATH": str(tmp_path / "cli.db")}
    if encoding is not None:
        env["PYTHONIOENCODING"] = encoding
    else:
        env.pop("PYTHONIOENCODING", None)
    # A hang raises TimeoutExpired, which fails the test.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-m", "cli.main", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        timeout=40,
        check=False,
    )


@needs_sqlite_vec
@pytest.mark.timeout(60)
def test_models_list_process_exits(tmp_path):
    result = _run_cli(tmp_path, "models", "list")
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"No threat models found" in result.stdout


def _seed_model(tmp_path: Path, monkeypatch) -> str:
    """Create one model in the same DB file the subprocess will use, closing
    the connection afterwards (run_async does) so this process doesn't hang."""
    from backend.config import settings
    from backend.db import crud

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "cli.db"))

    async def _create() -> str:
        return await crud.create_threat_model(
            title="Encoding check",
            description="A system description",
            provider="anthropic",
            model="claude-sonnet-4",
            framework="STRIDE",
            iteration_count=1,
        )

    return run_async(_create())


@needs_sqlite_vec
@pytest.mark.timeout(60)
def test_success_line_survives_a_cp1252_stdout(tmp_path, monkeypatch):
    """Windows' redirected stdout is cp1252, which can't encode the CLI's
    "✓ Deleted model" line. The command's work is done by then, so it must
    still exit 0, not report an "Unexpected error". (stderr is already
    backslashreplace by default; stdout is the stream that crashed.)"""
    model_id = _seed_model(tmp_path, monkeypatch)
    result = _run_cli(tmp_path, "models", "delete", model_id, "--yes", encoding="cp1252")
    stdout = result.stdout.decode("cp1252", errors="replace")
    stderr = result.stderr.decode("cp1252", errors="replace")
    assert result.returncode == 0, stderr
    assert "? Deleted model" in stdout
    assert "Unexpected error" not in stderr
