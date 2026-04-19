"""Clone + index lifecycle manager for code sources.

Background task orchestrates: queued → cloning → indexing → ready.
Any step can transition to failed.

The manager publishes ``SourceEvent`` objects to:
  - A per-source ring buffer (last ``RING_BUFFER_SIZE`` events, kept
    ``RING_BUFFER_TTL_S`` seconds after task completion for reconnecting
    SSE clients).
  - Each registered SSE subscriber queue (fan-out; max ``MAX_SUBSCRIBERS``
    per source; 9th subscriber gets ``TooManySubscribersError``).

Design constraints:
  - Background task must survive client disconnect — started via
    ``asyncio.create_task``, not tied to a request generator.
  - Per-source ``asyncio.Lock`` prevents concurrent clone/re-index of
    the same source.
  - ``asyncio.Event`` signals cancellation for the DELETE-during-indexing
    path; the task checks it between steps and kills any running subprocess.
  - context-link binary is optional: if absent the source reaches ``ready``
    without a code index (MCP features unavailable for that source).
"""

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import re
import shutil
import time
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from backend.config import settings
from backend.db.crud import (
    get_code_source,
    get_code_source_pat,
    mark_code_source_pat_used,
    update_code_source_status,
)
from backend.security.source_key import (
    KeySourceChangedError,
    PATDecryptionError,
    SourceKeyUnavailableError,
)
from backend.sources.paths import clone_dir_for


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUILTIN_GIT_HOSTS: frozenset[str] = frozenset({"github.com", "gitlab.com", "bitbucket.org"})

# Replace x-access-token:<token>@ with x-access-token:***@ in any string.
_PAT_SCRUB_RE = re.compile(r"x-access-token:[^@\s]+@")

# Auth failure on git clone: exit 128 + one of these patterns in stderr.
_AUTH_FAILURE_RE = re.compile(
    r"HTTP\s+40[13]|authentication\s+failed|access\s+denied|bad\s+credentials",
    re.IGNORECASE,
)

# Hex SHA ref (7-40 hex chars) -> full clone required (no --depth 1).
_SHA_REF_RE = re.compile(r"^[0-9a-f]{7,40}$")

MAX_SUBSCRIBERS = 8
RING_BUFFER_SIZE = 20
RING_BUFFER_TTL_S = 60.0
HEARTBEAT_INTERVAL_S = 10.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HostNotAllowedError(ValueError):
    """Git URL host is not in the allowlist."""


class TooManySubscribersError(RuntimeError):
    """SSE subscriber cap reached for this source."""


# ---------------------------------------------------------------------------
# SourceEvent — SSE payload
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SourceEvent:
    source_id: str
    status: str  # queued|cloning|indexing|ready|failed
    phase: str
    message: str
    error: str | None = None
    elapsed_s: float | None = None
    files_scanned: int | None = None
    bytes_scanned: int | None = None
    timestamp: str = dataclasses.field(default_factory=lambda: datetime.now(UTC).isoformat())
    seq: int = 0  # monotonically increasing per source; set by _publish

    def to_sse_data(self) -> str:
        d = dataclasses.asdict(self)
        return json.dumps({k: v for k, v in d.items() if v is not None})


# ---------------------------------------------------------------------------
# Module-level state (single-process FastAPI)
# ---------------------------------------------------------------------------

_locks: dict[str, asyncio.Lock] = {}
_cancel_events: dict[str, asyncio.Event] = {}
_active_tasks: dict[str, asyncio.Task] = {}

# Fan-out: source_id → list of per-subscriber queues
_subscribers: dict[str, list[asyncio.Queue]] = {}

# Ring buffers: source_id → deque of SourceEvent
_ring_buffers: dict[str, deque] = {}
# Monotonic expiry time; set when task completes (TTL starts from completion)
_ring_expiry: dict[str, float] = {}

# Per-source event sequence counters for SSE deduplication.
_source_seqs: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def allowed_hosts() -> frozenset[str]:
    """Return the effective git host allowlist (builtin + ADDITIONAL_GIT_HOSTS)."""
    extra = settings.additional_git_hosts.strip()
    if not extra:
        return _BUILTIN_GIT_HOSTS
    extras = frozenset(h.strip() for h in extra.split(",") if h.strip())
    return _BUILTIN_GIT_HOSTS | extras


def validate_git_url(url: str) -> None:
    """Raise ``HostNotAllowedError`` if URL scheme or host is not allowed.

    Only https:// is accepted — http:// would transmit PAT credentials in
    cleartext and is never appropriate for authenticated remote access.
    """
    if not url.startswith("https://"):
        raise HostNotAllowedError(
            f"URL must use https:// scheme (http://, SSH, and file:// are not supported): {url!r}"
        )
    host = urlparse(url).hostname or ""
    if host not in allowed_hosts():
        raise HostNotAllowedError(
            f"Git host {host!r} is not in the allowlist. "
            f"Allowed: {sorted(allowed_hosts())}. "
            "Add additional hosts via ADDITIONAL_GIT_HOSTS env var."
        )


def scrub_pat(text: str) -> str:
    """Replace PAT tokens in ``text`` with ``***``."""
    return _PAT_SCRUB_RE.sub("x-access-token:***@", text)


def is_sha_ref(ref: str | None) -> bool:
    """Return True when ``ref`` looks like a hex commit SHA (needs full clone).

    Note: short branch names that are also valid hex strings (e.g. ``deadbeef``)
    will match and trigger a full clone rather than ``--depth 1``. This is
    conservatively correct — slower but never wrong — because a shallow clone
    cannot satisfy an arbitrary commit SHA lookup.
    """
    return bool(ref and _SHA_REF_RE.match(ref))


def check_path_containment(path: Path, base_dir: Path) -> bool:
    """Return True iff ``path.resolve()`` is inside ``base_dir.resolve()``.

    Primary defence against symlink-escape: a clone tree containing a
    symlink that resolves outside the clone dir is rejected before any
    file-read. ``core.symlinks=false`` prevents git from materialising
    symlinks as real filesystem symlinks, but belt-and-suspenders here.
    """
    try:
        resolved = path.resolve()
        base = base_dir.resolve()
        resolved.relative_to(base)
        return True
    except ValueError:
        return False


def get_lock(source_id: str) -> asyncio.Lock:
    if source_id not in _locks:
        _locks[source_id] = asyncio.Lock()
    return _locks[source_id]


def get_ring_buffer(source_id: str) -> list[SourceEvent]:
    """Return the ring buffer for ``source_id``, purging if TTL has expired."""
    expiry = _ring_expiry.get(source_id)
    if expiry is not None and time.monotonic() > expiry:
        _ring_buffers.pop(source_id, None)
        _ring_expiry.pop(source_id, None)
        return []
    return list(_ring_buffers.get(source_id, []))


def is_task_active(source_id: str) -> bool:
    task = _active_tasks.get(source_id)
    return task is not None and not task.done()


def subscriber_count(source_id: str) -> int:
    """Return the number of active SSE subscribers for ``source_id``."""
    return len(_subscribers.get(source_id, []))


def forget(source_id: str) -> None:
    """Purge all module state for a deleted source.

    Call after cancel_and_wait + DB delete so there is no unbounded accumulation
    of per-UUID entries across create→delete cycles.
    """
    _locks.pop(source_id, None)
    _cancel_events.pop(source_id, None)
    _active_tasks.pop(source_id, None)
    _subscribers.pop(source_id, None)
    _ring_buffers.pop(source_id, None)
    _ring_expiry.pop(source_id, None)
    _source_seqs.pop(source_id, None)


# ---------------------------------------------------------------------------
# SSE subscription context manager
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def subscribe_to_source(source_id: str) -> AsyncIterator[asyncio.Queue]:
    """Register an SSE subscriber for ``source_id``.

    Raises ``TooManySubscribersError`` if the cap is reached.
    Automatically deregisters on exit.
    """
    subs = _subscribers.setdefault(source_id, [])
    if len(subs) >= MAX_SUBSCRIBERS:
        raise TooManySubscribersError(
            f"Max {MAX_SUBSCRIBERS} simultaneous SSE subscribers reached for source {source_id}"
        )
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    subs.append(q)
    try:
        yield q
    finally:
        with contextlib.suppress(ValueError):
            subs.remove(q)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _publish(source_id: str, event: SourceEvent) -> None:
    """Push ``event`` to the ring buffer and all live subscriber queues.

    Assigns a monotonically increasing sequence number so SSE clients can
    deduplicate ring-buffer replay against live queue events.
    """
    seq = _source_seqs.get(source_id, 0) + 1
    _source_seqs[source_id] = seq
    event.seq = seq
    buf = _ring_buffers.setdefault(source_id, deque(maxlen=RING_BUFFER_SIZE))
    buf.append(event)
    for q in list(_subscribers.get(source_id, [])):
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(event)


def _signal_done(source_id: str) -> None:
    """Send the done sentinel (None) to all subscriber queues."""
    for q in list(_subscribers.get(source_id, [])):
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(None)
    _ring_expiry[source_id] = time.monotonic() + RING_BUFFER_TTL_S


def _resolve_context_link_binary() -> str | None:
    """Find the context-link binary: explicit setting → ./bin/ → PATH."""
    explicit = settings.context_link_binary.strip()
    if explicit and Path(explicit).is_file():
        return explicit
    repo_bin = Path(__file__).resolve().parent.parent.parent / "bin" / "context-link"
    if repo_bin.is_file():
        return str(repo_bin)
    found = shutil.which("context-link")
    return found


def _walk_stats(path: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) under ``path``. Best-effort."""
    file_count = 0
    total_bytes = 0
    try:
        for dirpath, _, fnames in os.walk(path):
            for fname in fnames:
                file_count += 1
                try:
                    total_bytes += (Path(dirpath) / fname).stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return file_count, total_bytes


async def _run_subprocess(
    args: list[str],
    cancel_event: asyncio.Event,
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess. Returns ``(returncode, stdout, stderr)``.

    If ``cancel_event`` fires before the process finishes, the process is
    killed and ``(-1, "", "")`` is returned.
    """
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )

    communicate_task: asyncio.Task = asyncio.create_task(proc.communicate())
    cancel_task: asyncio.Task = asyncio.create_task(cancel_event.wait())

    done, pending = await asyncio.wait(
        {communicate_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
    )

    for t in pending:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t

    if cancel_task in done and communicate_task not in done:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        return -1, "", ""

    stdout_b, stderr_b = communicate_task.result()
    stdout = (stdout_b or b"").decode("utf-8", errors="replace")
    stderr = (stderr_b or b"").decode("utf-8", errors="replace")
    rc = proc.returncode if proc.returncode is not None else -1
    return rc, stdout, stderr


# ---------------------------------------------------------------------------
# Core clone + index pipeline
# ---------------------------------------------------------------------------


async def _do_clone_and_index(  # noqa: PLR0911
    source_id: str,
    cancel_event: asyncio.Event,
    start: float,
) -> None:
    """Execute clone → index → ready. Called inside the per-source lock."""
    source = await get_code_source(source_id)
    if source is None:
        logger.warning("Source %s vanished before clone started — aborting", source_id)
        return

    git_url: str = source["git_url"]
    ref: str | None = source["ref"]  # None for default-branch tracking

    try:
        validate_git_url(git_url)
    except HostNotAllowedError as exc:
        err = str(exc)
        await update_code_source_status(source_id, status="failed", error=err)
        _publish(source_id, SourceEvent(source_id, "failed", "validate", "URL rejected", error=err))
        return

    # ── Step 1: clone ────────────────────────────────────────────────────
    if cancel_event.is_set():
        return

    await update_code_source_status(source_id, status="cloning")
    _publish(source_id, SourceEvent(source_id, "cloning", "cloning", f"Cloning {git_url}…"))

    clone_dir = clone_dir_for(source_id)
    if clone_dir.exists():
        shutil.rmtree(clone_dir, ignore_errors=True)
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    # Build clone URL, injecting PAT when available.
    clone_url = git_url
    if source.get("has_pat"):
        try:
            pat = await get_code_source_pat(source_id)
            if pat:
                parsed = urlparse(git_url)
                netloc = f"x-access-token:{pat}@{parsed.hostname}"
                if parsed.port:
                    netloc += f":{parsed.port}"
                clone_url = urlunparse(parsed._replace(netloc=netloc))
                # Record that the PAT was used in this attempt, regardless of
                # whether the clone succeeds — the column tracks "last used",
                # not "last succeeded", so a 403 still advances the timestamp.
                await mark_code_source_pat_used(source_id)
        except (PATDecryptionError, KeySourceChangedError, SourceKeyUnavailableError) as exc:
            err = str(exc)
            await update_code_source_status(source_id, status="failed", error=err)
            _publish(
                source_id,
                SourceEvent(
                    source_id,
                    "failed",
                    "cloning",
                    "PAT decryption failed — re-enter credentials in Settings",
                    error=err,
                ),
            )
            return

    git_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    clone_args = [
        "git",
        # CVE-2022-39253 class: block submodule file:// transport
        "-c",
        "protocol.file.allow=never",
        # Belt-and-suspenders: prevent symlinks from materialising in the
        # working tree. The path-containment check is the primary defence.
        "-c",
        "core.symlinks=false",
        "clone",
    ]
    if not is_sha_ref(ref):
        clone_args += ["--depth", "1"]
    clone_args += [clone_url, str(clone_dir)]

    rc, _, stderr = await _run_subprocess(clone_args, cancel_event, env=git_env)
    if cancel_event.is_set():
        return

    if rc != 0:
        scrubbed = scrub_pat(stderr)
        if rc == 128 and _AUTH_FAILURE_RE.search(scrubbed):
            err = "Token rejected by git host — rotate the PAT in Settings."
        else:
            err = scrubbed or f"git clone exited with code {rc}"
        await update_code_source_status(source_id, status="failed", error=err)
        _publish(source_id, SourceEvent(source_id, "failed", "cloning", "Clone failed", error=err))
        return

    # Post-clone path-containment check: walk the clone dir and reject any
    # entry whose resolved path escapes the clone root. followlinks=False so
    # we never *descend* into a symlinked directory (avoids DoS / infinite-loop
    # from circular symlinks); check_path_containment(candidate) still calls
    # resolve() on each individual entry, which dereferences symlinks and
    # catches file/dir links pointing outside. core.symlinks=false is the
    # first line of defence; this walk is belt-and-suspenders.
    for dirpath, dirs, fnames in os.walk(clone_dir, followlinks=False):
        for name in [*dirs, *fnames]:
            candidate = Path(dirpath) / name
            if not check_path_containment(candidate, clone_dir):
                err = f"Clone rejected: path escapes clone directory: {candidate}"
                logger.warning("Source %s: %s", source_id, err)
                shutil.rmtree(clone_dir, ignore_errors=True)
                await update_code_source_status(source_id, status="failed", error=err)
                _publish(
                    source_id,
                    SourceEvent(
                        source_id, "failed", "cloning", "Path containment check failed", error=err
                    ),
                )
                return

    # Optional: checkout an explicit ref.
    if ref:
        co_rc, _, co_err = await _run_subprocess(
            ["git", "-C", str(clone_dir), "checkout", ref],
            cancel_event,
            env=git_env,
        )
        if cancel_event.is_set():
            return
        if co_rc != 0:
            err = scrub_pat(co_err) or f"git checkout {ref!r} exited with code {co_rc}"
            await update_code_source_status(source_id, status="failed", error=err)
            _publish(
                source_id,
                SourceEvent(
                    source_id, "failed", "cloning", f"Checkout of {ref!r} failed", error=err
                ),
            )
            return

    # Resolve HEAD SHA for the resolved_sha column.
    sha_rc, sha_out, _ = await _run_subprocess(
        ["git", "-C", str(clone_dir), "rev-parse", "HEAD"],
        cancel_event,
        env=git_env,
    )
    resolved_sha: str | None = sha_out.strip()[:40] if sha_rc == 0 and sha_out.strip() else None

    # ── Step 2: index ────────────────────────────────────────────────────
    if cancel_event.is_set():
        return

    cl_binary = _resolve_context_link_binary()
    await update_code_source_status(source_id, status="indexing")
    _publish(
        source_id,
        SourceEvent(
            source_id,
            "indexing",
            "indexing",
            "Running context-link index…" if cl_binary else "Indexer unavailable — skipping index",
            elapsed_s=round(time.monotonic() - start, 1),
        ),
    )

    if cl_binary is None:
        logger.warning(
            "context-link binary not found — marking source %s ready without index", source_id
        )
        now = datetime.now(UTC).isoformat()
        await update_code_source_status(
            source_id, status="ready", resolved_sha=resolved_sha, indexed_at=now
        )
        _publish(
            source_id,
            SourceEvent(
                source_id,
                "ready",
                "ready",
                "Ready (no code index — context-link binary not found)",
                elapsed_s=round(time.monotonic() - start, 1),
            ),
        )
        return

    # Always remove stale .context-link.db before indexing.
    cl_db = clone_dir / ".context-link.db"
    if cl_db.exists():
        cl_db.unlink()

    # Heartbeat task: emit progress events every 10 s while indexing runs.
    heartbeat_stop = asyncio.Event()

    async def _heartbeat() -> None:
        while not heartbeat_stop.is_set():
            try:
                await asyncio.wait_for(heartbeat_stop.wait(), timeout=HEARTBEAT_INTERVAL_S)
            except TimeoutError:
                pass
            if heartbeat_stop.is_set():
                break
            files, nbytes = _walk_stats(clone_dir)
            _publish(
                source_id,
                SourceEvent(
                    source_id,
                    "indexing",
                    "indexing",
                    "Indexing…",
                    elapsed_s=round(time.monotonic() - start, 1),
                    files_scanned=files,
                    bytes_scanned=nbytes,
                ),
            )

    heartbeat_task = asyncio.create_task(_heartbeat())

    try:
        idx_rc, _, idx_err = await _run_subprocess(
            [cl_binary, "index", str(clone_dir)], cancel_event
        )
    finally:
        heartbeat_stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

    if cancel_event.is_set():
        return

    if idx_rc != 0:
        if cl_db.exists():
            cl_db.unlink()
        err = scrub_pat(idx_err) or f"context-link index exited with code {idx_rc}"
        await update_code_source_status(source_id, status="failed", error=err)
        _publish(
            source_id, SourceEvent(source_id, "failed", "indexing", "Indexing failed", error=err)
        )
        return

    # ── Step 3: ready ────────────────────────────────────────────────────
    now = datetime.now(UTC).isoformat()
    await update_code_source_status(
        source_id, status="ready", resolved_sha=resolved_sha, indexed_at=now
    )
    _publish(
        source_id,
        SourceEvent(
            source_id,
            "ready",
            "ready",
            "Ready",
            elapsed_s=round(time.monotonic() - start, 1),
        ),
    )


async def run_clone_and_index(source_id: str) -> None:
    """Background task: clone + index ``source_id``. Acquires per-source lock."""
    lock = get_lock(source_id)
    cancel_event = _cancel_events.setdefault(source_id, asyncio.Event())
    start = time.monotonic()

    async with lock:
        try:
            await _do_clone_and_index(source_id, cancel_event, start)
        except Exception as exc:
            err = scrub_pat(str(exc))
            # Use logger.error (not logger.exception) so the full traceback —
            # which may contain a clone URL with embedded PAT — is not written
            # to the log stream.
            logger.error("Unexpected error in clone_and_index(%s): %s", source_id, err)
            await update_code_source_status(source_id, status="failed", error=err)
            _publish(
                source_id, SourceEvent(source_id, "failed", "error", "Internal error", error=err)
            )
        finally:
            _signal_done(source_id)
            _active_tasks.pop(source_id, None)
            # Clear the cancel event so a future re-index starts clean.
            cancel_event.clear()


def schedule_clone_and_index(source_id: str) -> asyncio.Task:
    """Schedule a background clone+index task and register it in _active_tasks."""
    # Reset cancel event for this run.
    ev = _cancel_events.setdefault(source_id, asyncio.Event())
    ev.clear()
    task = asyncio.create_task(run_clone_and_index(source_id), name=f"clone-{source_id}")
    _active_tasks[source_id] = task
    return task


async def cancel_and_wait(source_id: str, timeout: float = 5.0) -> bool:  # noqa: ASYNC109
    """Signal cancellation for ``source_id`` and wait up to ``timeout`` seconds.

    Returns True if the task stopped within the timeout, False otherwise.
    """
    ev = _cancel_events.get(source_id)
    if ev:
        ev.set()
    task = _active_tasks.get(source_id)
    if task is None or task.done():
        return True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return True
    except TimeoutError:
        return False
