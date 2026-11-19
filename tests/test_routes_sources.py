"""Route-level tests for /api/sources (Task 5)."""

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db import crud, crud_live_runs
from backend.pipeline import live_runs
from backend.security import source_key
from backend.sources import manager as mgr


# ---------------------------------------------------------------------------
# App fixture — isolated DB per test
# ---------------------------------------------------------------------------


def _clear_manager_state() -> None:
    mgr._locks.clear()
    mgr._cancel_events.clear()
    mgr._active_tasks.clear()
    mgr._queues.clear()


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.setattr(settings, "additional_git_hosts", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    source_key._reset_cache_for_tests()
    _clear_manager_state()
    yield
    source_key._reset_cache_for_tests()
    _clear_manager_state()


@pytest.fixture
async def client(_isolate, test_db):
    """Async HTTPX client wired to the FastAPI app with a live test DB."""
    from backend.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    # Index runs started by a test must not outlive its database.
    await live_runs.cancel_all_runs()


async def _no_schedule(source_id: str, **_kwargs) -> None:
    """Stands in for schedule_clone_and_index: no clone, no run."""


def _publishing_work(*events: tuple[str, str, str], release: asyncio.Event | None = None):
    """A stand-in for _do_clone_and_index that publishes ``events`` and returns.

    With ``release``, it waits for it after the first event.
    """

    async def work(source_id, cancel_event, start):
        for i, (status, phase, message) in enumerate(events):
            if status in ("ready", "failed"):
                await crud.update_code_source_status(source_id, status=status)
            mgr._publish(source_id, mgr.SourceEvent(source_id, status, phase, message))
            if i == 0 and release is not None:
                await release.wait()

    return work


def _data(body: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in body.splitlines()
        if line.startswith("data: ")
    ]


def _event_ids(body: str) -> list[int]:
    return [int(line.removeprefix("id: ")) for line in body.splitlines() if line.startswith("id: ")]


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
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client)
    assert resp.status_code == 202
    data = resp.json()
    assert data["git_url"] == "https://github.com/o/r.git"
    assert data["last_index_status"] == "queued"
    assert data["has_pat"] is False


@pytest.mark.asyncio
async def test_create_source_with_ref(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, ref="main")
    assert resp.status_code == 202
    assert resp.json()["ref"] == "main"


@pytest.mark.asyncio
@pytest.mark.parametrize("ref", ["--orphan", "-b", "--upload-pack=touch /tmp/x", "a..b"])
async def test_create_source_option_like_ref_returns_422_and_stores_nothing(
    client, monkeypatch, ref
):
    """A ref reaches git's argv, so anything git could parse as an option is refused (S1)."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, ref=ref)
    assert resp.status_code == 422
    assert "Invalid ref" in resp.json()["detail"]
    assert (await client.get("/api/sources")).json() == []


@pytest.mark.asyncio
async def test_create_source_with_pat_has_pat_true(client, monkeypatch):
    """POST with a PAT results in has_pat=True in the response."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, pat="ghp_test_token_12345")
    assert resp.status_code == 202
    assert resp.json()["has_pat"] is True


@pytest.mark.asyncio
async def test_create_source_invalid_url_returns_422(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, git_url="git@github.com:o/r.git")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_source_with_credentials_in_url_returns_422_and_stores_nothing(
    client, monkeypatch
):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, git_url="https://user:s3cret@github.com/o/r.git")
    assert resp.status_code == 422
    assert "s3cret" not in resp.text
    assert "PAT" in resp.json()["detail"]
    assert (await client.get("/api/sources")).json() == []


@pytest.mark.asyncio
async def test_create_source_non_allowlisted_host_returns_422(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client, git_url="https://evil.com/repo.git")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_duplicate_url_ref_returns_409(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    await _create(client, ref="main")
    resp = await _create(client, ref="main")  # same url + ref
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_duplicate_null_ref_returns_409(client, monkeypatch):
    """Two sources with the same URL and ref=None conflict (normalised to '')."""
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    await _create(client, ref=None)
    resp = await _create(client, ref=None)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_source_with_pat_key_unavailable_returns_409(client, monkeypatch):
    """POST with a PAT returns 409 when no key material is available."""
    from backend.security.source_key import SourceKeyUnavailableError

    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)

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
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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
@pytest.mark.parametrize("bad_id", ["..%2f..%2fetc", "%2e%2e", "ABCDEF", "a" * 40])
async def test_malformed_source_id_is_404_not_500(client, bad_id):
    # The path helpers raise ValueError on a non-hex id; the row lookup must
    # reject it first so the client never sees a 500.
    assert (await client.delete(f"/api/sources/{bad_id}")).status_code == 404
    assert (await client.get(f"/api/sources/{bad_id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_source_returns_204(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
    resp = await _create(client)
    source_id = resp.json()["id"]

    del_resp = await client.delete(f"/api/sources/{source_id}")
    assert del_resp.status_code == 204

    # Row is gone.
    assert (await client.get(f"/api/sources/{source_id}")).status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_clone_dir(client, monkeypatch, tmp_path):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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
async def test_sse_terminal_source_replays_its_stored_run(client, monkeypatch):
    """A ready source: SSE replays the stored index run, with event ids, and closes."""
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(("cloning", "cloning", "Cloning repo…"), ("ready", "ready", "All done")),
    )
    source_id = (await _create(client)).json()["id"]
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)

    resp = await client.get(f"/api/sources/{source_id}/events")

    assert resp.status_code == 200
    assert [e["message"] for e in _data(resp.text)] == ["Cloning repo…", "All done"]
    assert _event_ids(resp.text) == [1, 2]
    run = await crud_live_runs.get_latest_run("code_source", source_id)
    assert run["kind"] == "index"
    assert run["status"] == "completed"


@pytest.mark.asyncio
async def test_sse_after_resumes_without_duplicates(client, monkeypatch):
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(
            ("cloning", "cloning", "one"), ("indexing", "indexing", "two"), ("ready", "ready", "3")
        ),
    )
    source_id = (await _create(client)).json()["id"]
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)

    by_query = await client.get(f"/api/sources/{source_id}/events?after=1")
    by_header = await client.get(f"/api/sources/{source_id}/events", headers={"Last-Event-ID": "2"})

    assert _event_ids(by_query.text) == [2, 3]
    assert _event_ids(by_header.text) == [3]


@pytest.mark.asyncio
async def test_a_follower_attached_mid_index_gets_the_history_then_the_live_events(
    client, monkeypatch
):
    release = asyncio.Event()
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(
            ("cloning", "cloning", "Cloning repo…"), ("ready", "ready", "Ready"), release=release
        ),
    )
    source_id = (await _create(client)).json()["id"]

    async def follow():
        return await client.get(f"/api/sources/{source_id}/events")

    follower = asyncio.create_task(follow())
    await asyncio.sleep(0.2)
    assert not follower.done()  # still waiting on the live run
    release.set()
    resp = await asyncio.wait_for(follower, timeout=5)

    assert [e["message"] for e in _data(resp.text)] == ["Cloning repo…", "Ready"]


@pytest.mark.asyncio
async def test_a_busy_source_does_not_replay_an_earlier_finished_index(client, monkeypatch):
    """Replaying the last index's 'ready' would end the page's wait for the next one."""
    monkeypatch.setattr(
        mgr, "_do_clone_and_index", _publishing_work(("ready", "ready", "Old index done"))
    )
    source_id = (await _create(client)).json()["id"]
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)
    await crud.update_code_source_status(source_id, status="queued")  # no run behind it

    resp = await client.get(f"/api/sources/{source_id}/events")

    events = _data(resp.text)
    assert len(events) == 1
    assert events[0]["status"] == "queued"
    assert "Old index done" not in resp.text


@pytest.mark.asyncio
async def test_deleting_a_source_deletes_its_stored_runs(client, monkeypatch):
    monkeypatch.setattr(mgr, "_do_clone_and_index", _publishing_work(("ready", "ready", "Ready")))
    source_id = (await _create(client)).json()["id"]
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)
    run_id = (await crud_live_runs.get_latest_run("code_source", source_id))["id"]

    assert (await client.delete(f"/api/sources/{source_id}")).status_code == 204

    assert await crud_live_runs.get_latest_run("code_source", source_id) is None
    assert await crud_live_runs.list_events(run_id) == []


async def _ready_source() -> str:
    source_id = await crud.create_code_source(
        name="r", git_url="https://github.com/o/r.git", ref=None, pat=None
    )
    await crud.update_code_source_status(source_id, status="ready")
    return source_id


@pytest.mark.asyncio
async def test_two_reindexes_at_once_claim_one_run(client, monkeypatch):
    release = asyncio.Event()
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(
            ("cloning", "cloning", "Cloning"), ("ready", "ready", "Ready"), release=release
        ),
    )
    source_id = await _ready_source()

    first, second = await asyncio.gather(
        client.post(f"/api/sources/{source_id}/reindex"),
        client.post(f"/api/sources/{source_id}/reindex"),
    )

    assert sorted([first.status_code, second.status_code]) == [202, 409]
    winner = first if first.status_code == 202 else second
    assert winner.json()["last_index_status"] == "queued"
    release.set()
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)
    assert (await crud.get_code_source(source_id))["last_index_status"] == "ready"


@pytest.mark.asyncio
async def test_a_refused_reindex_leaves_the_running_status_alone(client, monkeypatch):
    """Another server on the database is indexing it: nothing in this process
    looks busy, so the 409 comes from the claim, before the status is reset."""
    scheduled_work: list[str] = []

    async def must_not_run(source_id, cancel_event, start):
        scheduled_work.append(source_id)

    monkeypatch.setattr(mgr, "_do_clone_and_index", must_not_run)
    source_id = await _ready_source()
    await crud.update_code_source_status(source_id, status="cloning")
    other = await crud_live_runs.claim_run("code_source", source_id, "index")

    r = await client.post(f"/api/sources/{source_id}/reindex")

    assert r.status_code == 409
    assert (await crud.get_code_source(source_id))["last_index_status"] == "cloning"
    assert scheduled_work == []
    await crud_live_runs.finish_run(other, "completed")


@pytest.mark.asyncio
async def test_list_after_delete_does_not_include_deleted(client, monkeypatch):
    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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

    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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

    monkeypatch.setattr(mgr, "schedule_clone_and_index", _no_schedule)
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
async def test_sse_reconnect_replays_the_history(client, monkeypatch):
    """Events published before any client connected are replayed to every later one.

    The old ring buffer forgot them 60 s after the index finished; stored
    events last as long as the run row.
    """
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(
            ("cloning", "cloning", "Cloning repo…"),
            ("indexing", "indexing", "Running index…"),
            ("ready", "ready", "Ready"),
        ),
    )
    source_id = (await _create(client)).json()["id"]
    await asyncio.wait_for(live_runs.get_run(source_id).task, timeout=5)

    for _ in range(2):
        resp = await client.get(f"/api/sources/{source_id}/events")
        assert resp.status_code == 200
        assert "Cloning repo" in resp.text
        assert "Running index" in resp.text


@pytest.mark.asyncio
async def test_the_stream_pings_while_the_index_is_silent(client, monkeypatch):
    """A long clone emits nothing; a ping keeps proxies from closing the stream."""
    from backend.routes import sources as sources_route

    monkeypatch.setattr(sources_route, "_KEEPALIVE_SECONDS", 0.05)
    release = asyncio.Event()
    monkeypatch.setattr(
        mgr,
        "_do_clone_and_index",
        _publishing_work(
            ("cloning", "cloning", "Cloning"), ("ready", "ready", "Ready"), release=release
        ),
    )
    source_id = (await _create(client)).json()["id"]

    follower = asyncio.create_task(client.get(f"/api/sources/{source_id}/events"))
    await asyncio.sleep(0.3)
    release.set()
    resp = await asyncio.wait_for(follower, timeout=5)

    assert "event: ping" in resp.text
    assert [e["message"] for e in _data(resp.text) if e] == ["Cloning", "Ready"]
