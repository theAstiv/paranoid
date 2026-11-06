"""Startup checks in backend/main.py."""

import logging

import pytest

from backend import main
from backend.config import settings


@pytest.mark.parametrize(
    ("origins", "expected"),
    [
        (["http://localhost:8000", "http://127.0.0.1:8000"], []),
        (["http://[::1]:8000", "http://127.0.0.2", "http://app.localhost"], []),
        (["https://paranoid.example.com"], []),
        (["http://192.168.1.20:8000"], ["http://192.168.1.20:8000"]),
        (
            ["https://ok.example", "http://paranoid.internal"],
            ["http://paranoid.internal"],
        ),
    ],
)
def test_non_tls_origins(origins, expected):
    assert main._non_tls_origins(origins) == expected


def test_warns_about_a_lan_origin_when_auth_is_on(monkeypatch, caplog):
    """Review C2: the Secure refresh cookie is dropped on plain HTTP, so users
    are signed out every 15 minutes with no hint why."""
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main._warn_if_refresh_cookie_is_dropped(["http://192.168.1.20:8000"])
    assert "http://192.168.1.20:8000" in caplog.text
    assert "HTTPS" in caplog.text


@pytest.mark.parametrize(
    ("auth", "origins"),
    [
        (True, ["http://localhost:8000", "https://paranoid.example.com"]),
        (False, ["http://192.168.1.20:8000"]),
    ],
)
def test_silent_for_tls_localhost_or_auth_off(monkeypatch, caplog, auth, origins):
    monkeypatch.setattr(settings, "paranoid_require_auth", auth)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main._warn_if_refresh_cookie_is_dropped(origins)
    assert "refresh cookie" not in caplog.text


@pytest.mark.asyncio
async def test_an_unusable_db_directory_exits_1_without_a_traceback(monkeypatch):
    """BB-141: Docker printed the one-line fix, then Starlette's whole traceback."""
    from unittest.mock import AsyncMock

    from backend.db.connection import DatabaseDirectoryError

    class _ExitedError(Exception):
        pass

    codes: list[int] = []

    def fake_exit(code: int) -> None:
        codes.append(code)
        raise _ExitedError

    monkeypatch.setattr(main.os, "_exit", fake_exit)
    monkeypatch.setattr(
        main.db, "initialize", AsyncMock(side_effect=DatabaseDirectoryError("data/ not writable"))
    )

    with pytest.raises(_ExitedError):
        async with main.lifespan(main.app):
            pass

    assert codes == [1]
