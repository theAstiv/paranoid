"""Route-level tests for /api/sources (Task 5)."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.security import source_key
from backend.sources import manager as mgr


# ---------------------------------------------------------------------------
# App fixture — isolated DB per test
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.setattr(settings, "additional_git_hosts", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    mgr._locks.clear()
    mgr._cancel_events.clear()
    mgr._active_tasks.clear()
    mgr._subscribers.clear()
    mgr._ring_buffers.clear()
    mgr._ring_expiry.clear()
    mgr._source_seqs.clear()
    yield
    source_key._reset_cache_for_tests()
    mgr._locks.clear()
    mgr._cancel_events.clear()
    mgr._active_tasks.clear()
    mgr._subscribers.clear()
    mgr._ring_buffers.clear()
    mgr._ring_expiry.clear()
    mgr._source_seqs.clear()


@pytest.fixture
async def client(_isolate, test_db):
    """Async HTTPX client wired to the FastAPI app with a live test DB."""
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create(client, *, name="repo", git_url="https://github.com/o/r.git", ref=None, pat=None):
    payload = {"name": name, "git_url": git_url, "ref": ref}
    if pat:
        payload["pat"] = pat
    resp = await client.post("/api/sources", json=payload)
    return resp


# ---------------------------------------------------------------------------
# GET /api/sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sources_empty(client):
    resp = await client.get("/api/sources")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/sources
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_source_returns_202(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    assert resp.status_code == 202
    data = resp.json()
    assert data["git_url"] == "https://github.com/o/r.git"
    assert data["last_index_status"] == "queued"
    assert data["has_pat"] is False


@pytest.mark.asyncio
async def test_create_source_with_ref(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client, ref="main")
    assert resp.status_code == 202
    assert resp.json()["ref"] == "main"


@pytest.mark.asyncio
async def test_create_source_with_pat_has_pat_true(client, monkeypatch):
    """POST with a PAT results in has_pat=True in the response."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client, pat="ghp_test_token_12345")
    assert resp.status_code == 202
    assert resp.json()["has_pat"] is True


@pytest.mark.asyncio
async def test_create_source_invalid_url_returns_422(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client, git_url="git@github.com:o/r.git")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_non_allowlisted_host_returns_422(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client, git_url="https://evil.com/repo.git")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_url_ref_returns_409(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    await _create(client, ref="main")
    resp = await _create(client, ref="main")  # same url + ref
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_null_ref_returns_409(client, monkeypatch):
    """Two sources with the same URL and ref=None conflict (normalised to '')."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    await _create(client, ref=None)
    resp = await _create(client, ref=None)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_source_with_pat_key_unavailable_returns_409(client, monkeypatch):
    """POST with a PAT returns 409 when no key material is available."""
    from backend.security.source_key import SourceKeyUnavailableError

    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)

    import backend.db.crud as crud_mod

    async def _patched(*a, **kw):
        raise SourceKeyUnavailableError("no key")

    monkeypatch.setattr(crud_mod, "create_code_source", _patched)

    resp = await _create(client, pat="ghp_x")
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /api/sources/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_source_not_found(client):
    resp = await client.get("/api/sources/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_source_found(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    create_resp = await _create(client)
    source_id = create_resp.json()["id"]

    resp = await client.get(f"/api/sources/{source_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == source_id


# ---------------------------------------------------------------------------
# POST /api/sources/{id}/reindex
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reindex_source_not_found(client):
    resp = await client.post("/api/sources/ghost/reindex")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_reindex_while_indexing_returns_409(client, monkeypatch):
    """When the per-source lock is held, re-index returns 409."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    lock = mgr.get_lock(source_id)

    async def _attempt():
        async with lock:
            r = await client.post(f"/api/sources/{source_id}/reindex")
            return r

    result = await _attempt()
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_reindex_returns_202_when_idle(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    r = await client.post(f"/api/sources/{source_id}/reindex")
    assert r.status_code == 202


# ---------------------------------------------------------------------------
# DELETE /api/sources/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_source_not_found(client):
    resp = await client.delete("/api/sources/ghost")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_source_returns_204(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    del_resp = await client.delete(f"/api/sources/{source_id}")
    assert del_resp.status_code == 204

    # Row is gone.
    assert (await client.get(f"/api/sources/{source_id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_clone_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    # Create a fake clone dir.
    from backend.sources.paths import clone_dir_for

    clone_dir = clone_dir_for(source_id)
    clone_dir.mkdir(parents=True, exist_ok=True)
    (clone_dir / "file.py").write_text("x")

    await client.delete(f"/api/sources/{source_id}")
    assert not clone_dir.exists()


# ---------------------------------------------------------------------------
# GET /api/sources/{id}/events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sse_source_not_found(client):
    resp = await client.get("/api/sources/ghost/events")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sse_terminal_source_replays_ring_buffer(client, monkeypatch):
    """A source in 'ready' state: SSE replays the ring buffer and closes."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    # Manually mark ready and push a ring buffer event.
    from backend.db import crud

    await crud.update_code_source_status(source_id, status="ready")

    from collections import deque

    from backend.sources.manager import SourceEvent, _ring_buffers

    ev = SourceEvent(source_id, "ready", "ready", "All done")
    _ring_buffers[source_id] = deque([ev], maxlen=20)

    resp = await client.get(f"/api/sources/{source_id}/events")
    assert resp.status_code == 200
    body = resp.text
    assert "All done" in body


@pytest.mark.asyncio
async def test_list_after_delete_does_not_include_deleted(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    await _create(client, name="r1")
    resp = await _create(client, git_url="https://gitlab.com/o/r.git", name="r2")
    source_id = resp.json()["id"]

    await client.delete(f"/api/sources/{source_id}")
    listed = (await client.get("/api/sources")).json()
    assert all(s["id"] != source_id for s in listed)


@pytest.mark.asyncio
async def test_delete_during_indexing_cancels(client, monkeypatch):
    """DELETE while a background task is running signals cancel via the real
    cancel_and_wait and returns 204 once the task exits.

    Uses a real asyncio.Task that watches the cancel event (same pattern
    used by the actual run_clone_and_index), so the test exercises the real
    cancel-and-wait path rather than a stub.
    """
    import asyncio

    from backend.db import crud

    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    # Register a cancel event and a task that exits when the event is set.
    cancel_ev = asyncio.Event()
    mgr._cancel_events[source_id] = cancel_ev

    async def _cancellable_task():
        await cancel_ev.wait()

    task = asyncio.create_task(_cancellable_task())
    mgr._active_tasks[source_id] = task

    # Mark source as cloning so the DELETE route sees it as in-progress.
    await crud.update_code_source_status(source_id, status="cloning")

    del_resp = await client.delete(f"/api/sources/{source_id}")
    assert del_resp.status_code == 204

    # Row is gone and task completed (cancel event was set by cancel_and_wait).
    assert (await client.get(f"/api/sources/{source_id}")).status_code == 404
    assert task.done()


@pytest.mark.asyncio
async def test_sse_terminal_source_replays_empty_ring_with_synthetic(client, monkeypatch):
    """When ring buffer has expired, a synthetic terminal event is emitted."""
    from backend.db import crud

    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    # Mark failed so the synthetic event has status=failed.
    await crud.update_code_source_status(source_id, status="failed", error="connection timeout")

    # Ring buffer is empty (never populated or TTL expired).
    resp = await client.get(f"/api/sources/{source_id}/events")
    assert resp.status_code == 200
    # Synthetic event has error text, not in message field.
    assert "connection timeout" in resp.text


@pytest.mark.asyncio
async def test_sse_reconnect_replays_ring_buffer(client, monkeypatch):
    """Events published during the clone phase are visible to reconnecting clients.

    Simulates: source is cloning, events are buffered (e.g. client A was
    connected then disconnected), source completes, client B connects and
    receives the full history from the ring buffer.
    """
    from backend.db import crud
    from backend.sources.manager import SourceEvent, _publish

    monkeypatch.setattr(mgr, "schedule_clone_and_index", lambda sid: None)
    resp = await _create(client)
    source_id = resp.json()["id"]

    # Simulate events published during cloning (before any HTTP client connected).
    _publish(source_id, SourceEvent(source_id, "cloning", "cloning", "Cloning repo…"))
    _publish(source_id, SourceEvent(source_id, "indexing", "indexing", "Running index…"))

    # Source completes.
    await crud.update_code_source_status(source_id, status="ready")

    # First reconnect after completion: ring buffer replayed.
    resp1 = await client.get(f"/api/sources/{source_id}/events")
    assert resp1.status_code == 200
    assert "Cloning repo" in resp1.text
    assert "Running index" in resp1.text

    # Second reconnect (TTL not expired): same ring buffer replayed again.
    resp2 = await client.get(f"/api/sources/{source_id}/events")
    assert resp2.status_code == 200
    assert "Cloning repo" in resp2.text
