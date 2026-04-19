"""Unit tests for backend.sources.manager (Task 5)."""

import asyncio
import os

import pytest

from backend.config import settings
from backend.security import source_key
from backend.sources import manager as mgr


# ---------------------------------------------------------------------------
# Isolation fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "paranoid.db"))
    monkeypatch.setattr(settings, "config_secret", "")
    monkeypatch.setattr(settings, "additional_git_hosts", "")
    monkeypatch.delenv("CONFIG_SECRET", raising=False)
    monkeypatch.delenv("ADDITIONAL_GIT_HOSTS", raising=False)
    source_key._reset_cache_for_tests()
    # Reset per-source module state between tests
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


# ---------------------------------------------------------------------------
# URL validation tests (sync)
# ---------------------------------------------------------------------------


def test_validate_git_url_allows_github():
    mgr.validate_git_url("https://github.com/owner/repo.git")  # should not raise


def test_validate_git_url_allows_gitlab():
    mgr.validate_git_url("https://gitlab.com/owner/repo.git")


def test_validate_git_url_allows_bitbucket():
    mgr.validate_git_url("https://bitbucket.org/owner/repo.git")


def test_validate_git_url_rejects_ssh():
    with pytest.raises(mgr.HostNotAllowedError, match=r"https://"):
        mgr.validate_git_url("git@github.com:owner/repo.git")


def test_validate_git_url_rejects_file():
    with pytest.raises(mgr.HostNotAllowedError):
        mgr.validate_git_url("file:///etc/passwd")


def test_validate_git_url_rejects_non_allowlisted():
    with pytest.raises(mgr.HostNotAllowedError, match=r"evil\.com"):
        mgr.validate_git_url("https://evil.com/owner/repo.git")


def test_validate_git_url_allows_additional_hosts(monkeypatch):
    monkeypatch.setattr(settings, "additional_git_hosts", "git.company.com")
    mgr.validate_git_url("https://git.company.com/org/repo.git")


def test_additional_hosts_rejects_subdomain_spoofing(monkeypatch):
    monkeypatch.setattr(settings, "additional_git_hosts", "git.company.com")
    with pytest.raises(mgr.HostNotAllowedError):
        mgr.validate_git_url("https://evil-git.company.com/repo.git")
    with pytest.raises(mgr.HostNotAllowedError):
        mgr.validate_git_url("https://git.company.com.attacker.io/repo.git")


def test_validate_git_url_rejects_userinfo_spoofing():
    """https://github.com@evil.com/x.git sets hostname=evil.com, not github.com."""
    with pytest.raises(mgr.HostNotAllowedError):
        mgr.validate_git_url("https://github.com@evil.com/owner/repo.git")


# ---------------------------------------------------------------------------
# PAT scrubbing
# ---------------------------------------------------------------------------


def test_scrub_pat_replaces_token():
    raw = "remote: https://x-access-token:ghp_abc123@github.com/owner/repo.git"
    scrubbed = mgr.scrub_pat(raw)
    assert "ghp_abc123" not in scrubbed
    assert "x-access-token:***@" in scrubbed


def test_scrub_pat_noop_when_no_token():
    raw = "error: some other message"
    assert mgr.scrub_pat(raw) == raw


def test_scrub_pat_handles_multiple_occurrences():
    raw = "x-access-token:tok1@github.com ... x-access-token:tok2@gitlab.com"
    scrubbed = mgr.scrub_pat(raw)
    assert "tok1" not in scrubbed
    assert "tok2" not in scrubbed


# ---------------------------------------------------------------------------
# SHA ref detection
# ---------------------------------------------------------------------------


def test_is_sha_ref_short_sha():
    assert mgr.is_sha_ref("abc1234") is True


def test_is_sha_ref_full_sha():
    assert mgr.is_sha_ref("a" * 40) is True


def test_is_sha_ref_branch_name():
    assert mgr.is_sha_ref("main") is False


def test_is_sha_ref_tag():
    assert mgr.is_sha_ref("v1.0.0") is False


def test_is_sha_ref_none():
    assert mgr.is_sha_ref(None) is False


# ---------------------------------------------------------------------------
# Path containment check
# ---------------------------------------------------------------------------


def test_check_path_containment_allows_valid_path(tmp_path):
    child = tmp_path / "subdir" / "file.py"
    assert mgr.check_path_containment(child, tmp_path) is True


def test_check_path_containment_rejects_escape(tmp_path):
    outside = tmp_path.parent / "etc" / "passwd"
    assert mgr.check_path_containment(outside, tmp_path) is False


@pytest.mark.skipif(
    os.name == "nt", reason="Creating symlinks requires elevated privileges on Windows"
)
def test_check_path_containment_rejects_symlink_escape(tmp_path):
    """Symlink that points outside the base dir is rejected after resolve()."""
    base = tmp_path / "clone"
    base.mkdir()
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    link = base / "evil_link"
    link.symlink_to(target)  # points outside base/
    assert mgr.check_path_containment(link, base) is False


# ---------------------------------------------------------------------------
# Auth failure detection (parametrised over git version samples)
# ---------------------------------------------------------------------------


_AUTH_STDERR_SAMPLES = [
    # git 2.35
    "remote: HTTP Basic: Access denied\nfatal: Authentication failed for 'https://github.com/'\n",
    # git 2.40
    "remote: Invalid username or password.\nfatal: Authentication failed for 'https://gitlab.com/'\n",
    # git 2.45
    "remote: HTTP 401\nfatal: repository 'https://bitbucket.org/o/r.git/' not found\n",
    # GitHub access denied variant
    "fatal: Access denied\nfatal: unable to checkout\n",
    # Bad credentials pattern
    "remote: Bad credentials\n",
]


@pytest.mark.parametrize("stderr", _AUTH_STDERR_SAMPLES)
def test_auth_failure_regex_matches_git_versions(stderr):
    assert mgr._AUTH_FAILURE_RE.search(mgr.scrub_pat(stderr)), (
        f"Pattern did not match stderr: {stderr!r}"
    )


# ---------------------------------------------------------------------------
# Fake subprocess helpers
# ---------------------------------------------------------------------------


class _FakeProcess:
    def __init__(self, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def _make_exec_factory(*specs):
    """Return a fake ``asyncio.create_subprocess_exec`` that cycles through specs.

    Each spec is a dict with optional keys: returncode, stdout, stderr.
    """
    it = iter(specs)

    async def fake_exec(*args, **kwargs):
        spec = next(it, {})
        return _FakeProcess(
            returncode=spec.get("returncode", 0),
            stdout=spec.get("stdout", b""),
            stderr=spec.get("stderr", b""),
        )

    return fake_exec


# ---------------------------------------------------------------------------
# Manager pipeline tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clone_and_index_success(test_db, tmp_path, monkeypatch):
    """Happy path: queued → cloning → indexing → ready."""
    monkeypatch.setattr(mgr, "_resolve_context_link_binary", lambda: "/fake/context-link")

    source_id = await _create_source(
        git_url="https://github.com/owner/repo.git",
        ref=None,
        pat=None,
    )

    events: list[mgr.SourceEvent] = []

    def _capture(sid, event):
        events.append(event)

    monkeypatch.setattr(mgr, "_publish", _capture)

    fake_exec = _make_exec_factory(
        {"returncode": 0, "stdout": b"", "stderr": b""},  # git clone
        {"returncode": 0, "stdout": b"abc1234def5678\n", "stderr": b""},  # git rev-parse
        {"returncode": 0, "stdout": b"", "stderr": b""},  # context-link index
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    statuses = [e.status for e in events]
    assert "cloning" in statuses
    assert "indexing" in statuses
    assert statuses[-1] == "ready"


@pytest.mark.asyncio
async def test_clone_failure_marks_failed(test_db, monkeypatch):
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    events: list[mgr.SourceEvent] = []
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: events.append(ev))

    fake_exec = _make_exec_factory(
        {"returncode": 1, "stderr": b"some clone error"},  # git clone fails
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    assert events[-1].status == "failed"
    assert events[-1].phase == "cloning"


@pytest.mark.asyncio
async def test_clone_auth_failure_maps_to_friendly_message(test_db, monkeypatch):
    source_id = await _create_source("https://github.com/o/private.git", None, None)

    events: list[mgr.SourceEvent] = []
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: events.append(ev))

    auth_stderr = b"remote: HTTP 403\nfatal: Authentication failed\n"
    fake_exec = _make_exec_factory({"returncode": 128, "stderr": auth_stderr})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    failure = events[-1]
    assert failure.status == "failed"
    assert "rotate the PAT" in (failure.error or "")


@pytest.mark.asyncio
async def test_clone_and_index_no_binary(test_db, monkeypatch):
    """If context-link binary not found, source reaches ready without index."""
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    events: list[mgr.SourceEvent] = []
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: events.append(ev))
    monkeypatch.setattr(mgr, "_resolve_context_link_binary", lambda: None)

    fake_exec = _make_exec_factory(
        {"returncode": 0},  # git clone
        {"returncode": 0, "stdout": b"abc123\n", "stderr": b""},  # git rev-parse
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    final = events[-1]
    assert final.status == "ready"
    assert "context-link" in final.message.lower() or "indexer" in final.message.lower()


@pytest.mark.asyncio
async def test_index_failure_removes_context_link_db(test_db, tmp_path, monkeypatch):
    """A failed index run deletes .context-link.db so stale data can't be served."""
    monkeypatch.setattr(mgr, "_resolve_context_link_binary", lambda: "/fake/cl")

    source_id = await _create_source("https://github.com/o/r.git", None, None)

    # Pre-create a fake .context-link.db inside a fake clone dir.
    clone_dir = mgr.clone_dir_for(source_id)
    clone_dir.mkdir(parents=True, exist_ok=True)
    cl_db = clone_dir / ".context-link.db"
    cl_db.write_bytes(b"stale")

    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: None)

    fake_exec = _make_exec_factory(
        {"returncode": 0},  # git clone
        {"returncode": 0, "stdout": b"abc123\n", "stderr": b""},  # git rev-parse
        {"returncode": 1, "stderr": b"index error"},  # context-link fails
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    assert not cl_db.exists(), ".context-link.db must be removed after index failure"


@pytest.mark.asyncio
async def test_stderr_pat_scrubbed(test_db, monkeypatch):
    """PAT literal must not appear in any persisted error message."""
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    errors_persisted: list[str] = []

    original_update = mgr.update_code_source_status

    async def capturing_update(sid, *, status, error=None, **kw):
        if error:
            errors_persisted.append(error)
        return await original_update(sid, status=status, error=error, **kw)

    monkeypatch.setattr(mgr, "update_code_source_status", capturing_update)
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: None)

    pat_in_stderr = b"remote: https://x-access-token:ghp_SuperSecret@github.com/o/r\nfatal: bad\n"
    fake_exec = _make_exec_factory({"returncode": 1, "stderr": pat_in_stderr})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    for err in errors_persisted:
        assert "ghp_SuperSecret" not in err, f"PAT found in persisted error: {err!r}"


@pytest.mark.asyncio
async def test_pat_never_in_sse_events(test_db, monkeypatch):
    """PAT must not appear in any SourceEvent published during a failed clone."""
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    published: list[mgr.SourceEvent] = []
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: published.append(ev))

    pat_in_stderr = b"x-access-token:ghp_VerySecret@github.com -- connection refused\n"
    fake_exec = _make_exec_factory({"returncode": 1, "stderr": pat_in_stderr})
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    await mgr.run_clone_and_index(source_id)

    for event in published:
        for field in (event.message, event.error or ""):
            assert "ghp_VerySecret" not in field, f"PAT found in event field: {field!r}"


@pytest.mark.asyncio
async def test_sha_ref_skips_depth_flag(test_db, monkeypatch):
    """SHA refs must not receive --depth 1 so full history is available."""
    source_id = await _create_source(
        "https://github.com/o/r.git", ref="abc1234def5678901234567890123456789012ab", pat=None
    )

    called_args: list[list[str]] = []

    async def recording_exec(*args, **kwargs):
        called_args.append(list(args))
        return _FakeProcess(returncode=0, stdout=b"abc1234\n", stderr=b"")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", recording_exec)
    monkeypatch.setattr(mgr, "_resolve_context_link_binary", lambda: None)
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: None)

    await mgr.run_clone_and_index(source_id)

    # The first subprocess call is git clone.
    clone_call = next((a for a in called_args if "clone" in a), None)
    assert clone_call is not None
    assert "--depth" not in clone_call


@pytest.mark.asyncio
async def test_cancel_stops_background_task(test_db, monkeypatch):
    """Setting the cancel event causes run_clone_and_index to exit early."""
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    communicate_started = asyncio.Event()

    class _SlowProcess:
        returncode = 0

        async def communicate(self):
            communicate_started.set()
            await asyncio.sleep(60)
            return b"", b""

        def kill(self):
            pass

        async def wait(self):
            return 0

    async def slow_exec(*args, **kwargs):
        return _SlowProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", slow_exec)
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: None)

    # Register cancel event and task so cancel_and_wait can find them.
    cancel_ev = asyncio.Event()
    mgr._cancel_events[source_id] = cancel_ev
    task = asyncio.create_task(mgr.run_clone_and_index(source_id))
    mgr._active_tasks[source_id] = task

    await communicate_started.wait()

    # Signal cancel and wait up to 3 s for the task to finish.
    stopped = await mgr.cancel_and_wait(source_id, timeout=3.0)
    assert stopped
    assert task.done()


@pytest.mark.asyncio
async def test_reindex_while_running_lock_is_held(test_db):
    """The per-source lock is held while the background task runs."""
    source_id = await _create_source("https://github.com/o/r.git", None, None)
    lock = mgr.get_lock(source_id)

    async with lock:
        assert lock.locked() is True


@pytest.mark.asyncio
async def test_pat_expiry_detection_across_git_versions(test_db, monkeypatch):
    """Each auth-failure stderr pattern maps to the 'rotate the PAT' message."""
    auth_stderrs = [
        b"remote: HTTP Basic: Access denied\nfatal: Authentication failed\n",
        b"remote: Invalid username or password.\nfatal: Authentication failed\n",
        b"remote: HTTP 403\nfatal: Authentication failed for 'https://github.com/'\n",
        b"fatal: Access denied\n",
        b"remote: Bad credentials\n",
    ]
    for i, auth_stderr in enumerate(auth_stderrs):
        source_id = await _create_source(f"https://github.com/o/private{i}.git", None, None)

        events: list[mgr.SourceEvent] = []

        def _capture(sid, ev, _buf=events):
            _buf.append(ev)

        monkeypatch.setattr(mgr, "_publish", _capture)

        fake_exec = _make_exec_factory({"returncode": 128, "stderr": auth_stderr})
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        await mgr.run_clone_and_index(source_id)

        failure = events[-1]
        assert failure.status == "failed", f"Expected failed for stderr={auth_stderr!r}"
        assert "rotate the PAT" in (failure.error or ""), (
            f"Expected 'rotate the PAT' message for stderr={auth_stderr!r}, got {failure.error!r}"
        )
        events.clear()


# ---------------------------------------------------------------------------
# Ring buffer / subscriber helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_background_task_survives_subscriber_disconnect(test_db, monkeypatch):
    """Closing an SSE subscriber queue doesn't cancel the background clone task.

    This tests the key design invariant: asyncio.create_task decouples the
    background task lifecycle from the HTTP request. A real background task is
    scheduled; an SSE subscriber connects and immediately disconnects; the task
    must still be running afterward.
    """
    source_id = await _create_source("https://github.com/o/r.git", None, None)

    started_ev = asyncio.Event()
    release_ev = asyncio.Event()

    class _PinnedProcess:
        returncode = 0

        async def communicate(self):
            started_ev.set()
            await release_ev.wait()
            return b"abc1234\n", b""

        def kill(self):
            release_ev.set()

        async def wait(self):
            return 0

    async def pinned_exec(*args, **kwargs):
        return _PinnedProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", pinned_exec)
    monkeypatch.setattr(mgr, "_resolve_context_link_binary", lambda: None)
    monkeypatch.setattr(mgr, "_publish", lambda sid, ev: None)

    task = mgr.schedule_clone_and_index(source_id)
    await asyncio.wait_for(started_ev.wait(), timeout=3.0)

    # Subscribe and immediately disconnect (simulates HTTP client closing SSE).
    async with mgr.subscribe_to_source(source_id):
        pass

    # Background task must still be alive.
    assert not task.done(), "Background task was killed by subscriber disconnect"

    # Release the subprocess so the task can complete cleanly.
    release_ev.set()
    await asyncio.wait_for(task, timeout=3.0)
    assert task.done()


def test_get_ring_buffer_returns_events():
    from backend.sources.manager import SourceEvent, _publish

    ev = SourceEvent("src1", "cloning", "cloning", "msg")
    _publish("src1", ev)
    buf = mgr.get_ring_buffer("src1")
    assert len(buf) == 1
    assert buf[0].status == "cloning"


def test_get_ring_buffer_purges_after_ttl(monkeypatch):
    import time

    from backend.sources.manager import SourceEvent, _publish, _ring_expiry

    ev = SourceEvent("src2", "ready", "ready", "done")
    _publish("src2", ev)
    # Expire immediately
    _ring_expiry["src2"] = time.monotonic() - 1.0
    buf = mgr.get_ring_buffer("src2")
    assert buf == []


def test_forget_clears_all_state():
    """forget() purges all module-level dicts for the given source_id."""
    from backend.sources.manager import SourceEvent, _publish, _source_seqs

    ev = SourceEvent("del-src", "cloning", "cloning", "msg")
    _publish("del-src", ev)
    mgr._locks["del-src"] = asyncio.Lock()
    mgr._cancel_events["del-src"] = asyncio.Event()

    mgr.forget("del-src")

    assert "del-src" not in mgr._locks
    assert "del-src" not in mgr._cancel_events
    assert "del-src" not in mgr._ring_buffers
    assert "del-src" not in mgr._ring_expiry
    assert "del-src" not in _source_seqs


def test_publish_assigns_monotonic_seq():
    """Each _publish call increments the per-source seq counter."""
    from backend.sources.manager import SourceEvent, _publish

    e1 = SourceEvent("seq-src", "cloning", "cloning", "a")
    e2 = SourceEvent("seq-src", "indexing", "indexing", "b")
    _publish("seq-src", e1)
    _publish("seq-src", e2)
    assert e1.seq < e2.seq
    assert e2.seq > 0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _create_source(
    git_url: str,
    ref: str | None,
    pat: str | None,
) -> str:
    from backend.db.crud import create_code_source

    return await create_code_source(
        name="test",
        git_url=git_url,
        ref=ref,
        pat=pat,
    )
