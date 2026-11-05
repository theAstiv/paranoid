"""Phase 1 PR 11: small hardening fixes from the 2026-11-02 review.

S6 key file created 0600 and binary, S7 constant-time PAT hash compare, C5
one re-index at a time, C6 bounded model list, A4 rate-limit proxy warning.
"""

import asyncio
import logging
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from backend import main
from backend.config import settings
from backend.db import crud
from backend.main import app
from backend.security import source_key
from backend.sources import manager as mgr


# ---------------------------------------------------------------------------
# S6: the Fernet file key
# ---------------------------------------------------------------------------


def test_a_key_with_newline_bytes_reads_back_intact(tmp_path, monkeypatch):
    """Without O_BINARY, Windows writes LF as CRLF and the next start fails."""
    monkeypatch.setattr(source_key.secrets, "token_bytes", lambda n: b"\n" * n)

    first = source_key._load_or_create_file_key(tmp_path)
    again = source_key._load_or_create_file_key(tmp_path)

    assert first == again
    assert (tmp_path / source_key._KEY_FILENAME).stat().st_size == source_key._KEY_BYTES


def test_a_key_file_created_by_another_process_first_is_used(tmp_path, monkeypatch):
    """Two processes starting at once: the one that loses O_EXCL reads the winner's key."""
    theirs = b"k" * source_key._KEY_BYTES
    real_open = source_key.os.open

    def racing_open(path, flags, mode=0o777):
        # The other process creates the file between our exists() check and open().
        with open(path, "wb") as f:
            f.write(theirs)
        return real_open(path, flags, mode)

    monkeypatch.setattr(source_key.os, "open", racing_open)

    key = source_key._load_or_create_file_key(tmp_path)

    assert key == source_key.base64.urlsafe_b64encode(theirs)


# ---------------------------------------------------------------------------
# S7: PAT hashes compared in constant time
# ---------------------------------------------------------------------------


def test_pat_hashes_are_compared_with_compare_digest():
    import inspect

    from backend.auth import dependencies

    source = inspect.getsource(dependencies)
    assert 'compare_digest(pat["token_hash"], hash_pat(token))' in source
    assert 'pat["token_hash"] != hash_pat(token)' not in source


# ---------------------------------------------------------------------------
# C5: two re-index requests at once schedule one run
# ---------------------------------------------------------------------------


@pytest.fixture
async def client(test_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_two_reindex_requests_at_once_schedule_one_run(client, monkeypatch):
    scheduled: list[str] = []
    monkeypatch.setattr(mgr, "schedule_clone_and_index", scheduled.append)
    source_id = await crud.create_code_source(
        name="r", git_url="https://github.com/o/r.git", ref=None, pat=None
    )
    real_update = crud.update_code_source_status

    async def slow_update(*args, **kwargs):
        await asyncio.sleep(0.05)  # both requests are past the check before either schedules
        return await real_update(*args, **kwargs)

    with patch("backend.routes.sources.crud.update_code_source_status", slow_update):
        first, second = await asyncio.gather(
            client.post(f"/api/sources/{source_id}/reindex"),
            client.post(f"/api/sources/{source_id}/reindex"),
        )

    assert sorted([first.status_code, second.status_code]) == [202, 409]
    assert scheduled == [source_id]


@pytest.mark.asyncio
async def test_a_reindex_is_refused_while_the_task_runs(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    monkeypatch.setattr(mgr, "is_task_active", lambda sid: True)
    source_id = await crud.create_code_source(
        name="r", git_url="https://github.com/o/r.git", ref=None, pat=None
    )

    r = await client.post(f"/api/sources/{source_id}/reindex")

    assert r.status_code == 409


# ---------------------------------------------------------------------------
# C6: list_models' limit is bounded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("limit", "status"), [(-1, 422), (0, 422), (1, 200), (500, 200), (501, 422)]
)
@pytest.mark.asyncio
async def test_the_model_list_limit_is_bounded(client, limit, status):
    """A negative LIMIT is unlimited in SQLite: limit=-1 returned every row."""
    r = await client.get(f"/api/models/?limit={limit}")
    assert r.status_code == status


# ---------------------------------------------------------------------------
# A4: warn when every user would share one rate-limit bucket
# ---------------------------------------------------------------------------


def test_warns_when_auth_is_on_and_no_trusted_proxies(monkeypatch, caplog):
    monkeypatch.setattr(settings, "paranoid_require_auth", True)
    monkeypatch.setattr(settings, "trusted_proxies", "")
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main._warn_if_rate_limits_share_one_ip()
    assert "TRUSTED_PROXIES" in caplog.text


@pytest.mark.parametrize(("auth", "proxies"), [(True, "10.0.0.5"), (False, "")])
def test_silent_with_trusted_proxies_or_auth_off(monkeypatch, caplog, auth, proxies):
    monkeypatch.setattr(settings, "paranoid_require_auth", auth)
    monkeypatch.setattr(settings, "trusted_proxies", proxies)
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        main._warn_if_rate_limits_share_one_ip()
    assert "TRUSTED_PROXIES" not in caplog.text
