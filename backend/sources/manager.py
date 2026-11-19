"""Clone + index lifecycle manager for code sources.

Background task orchestrates: queued → cloning → indexing → ready.
Any step can transition to failed.

Progress is recorded like a pipeline run (backend/pipeline/live_runs.py,
Phase 2 A2): each index is a ``live_runs`` row (subject ``code_source``, kind
``index``) and each ``SourceEvent`` a stored ``live_run_events`` chunk. So a
follower can attach at any time, from any process, and replay from a sequence
number; a second index of the same source is refused by the claim; a crashed
server's index is found by the stale-run sweep and its source failed.

Design constraints:
  - Background task must survive client disconnect — it is a live run's
    task, not tied to a request generator.
  - The live-run claim refuses a second index of a running source; the
    per-source ``asyncio.Lock`` stays as an in-process backstop.
  - ``asyncio.Event`` signals cancellation for the DELETE-during-indexing
    path; the task checks it between steps and kills any running subprocess.
  - context-link binary is optional: if absent the source reaches ``ready``
    without a code index (MCP features unavailable for that source).
"""

import asyncio
import base64
import contextlib
import dataclasses
import json
import logging
import os
import re
import shutil
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
from urllib.parse import urlparse

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
from backend.sources.paths import clone_dir_for, index_db_for


if TYPE_CHECKING:
    from backend.pipeline.live_runs import LiveRun

logger = logging.getLogger(__name__)


def _live_runs() -> ModuleType:
    # Imported on use: backend.pipeline's __init__ loads the runner, which
    # reaches backend.deps.fetcher, which imports this module.
    from backend.pipeline import live_runs

    return live_runs


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

# Characters and sequences `git check-ref-format` refuses in a ref name.
_REF_FORBIDDEN_RE = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]|\.\.|@\{|//")
_MAX_REF_LENGTH = 255

HEARTBEAT_INTERVAL_S = 10.0
# How long a shutdown waits for an index to kill its subprocess and stop.
_STOP_GRACE_S = 5.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class HostNotAllowedError(ValueError):
    """Git URL host is not in the allowlist."""


class InvalidRefError(ValueError):
    """Ref is not a valid git branch, tag or commit name."""


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

    def to_sse_data(self) -> str:
        d = dataclasses.asdict(self)
        return json.dumps({k: v for k, v in d.items() if v is not None})


# ---------------------------------------------------------------------------
# Module-level state — execution only; events and run state are in the DB
# ---------------------------------------------------------------------------

_locks: dict[str, asyncio.Lock] = {}
# Set to stop an index: the running subprocess is killed (cancel_and_wait).
_cancel_events: dict[str, asyncio.Event] = {}
# The clone + index work of each running index.
_active_tasks: dict[str, asyncio.Task] = {}
# Hands the work's events to its live run, which stores them (see _index_events).
_queues: dict[str, asyncio.Queue] = {}


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
    Credentials in the URL are refused: they would be stored and returned in plain
    text, whereas the PAT field is encrypted at rest.
    """
    if not url.startswith("https://"):
        raise HostNotAllowedError(
            f"URL must use https:// scheme (http://, SSH, and file:// are not supported): {url!r}"
        )
    parsed = urlparse(url)
    if "@" in parsed.netloc:
        # Never echo the URL: it holds the secret being rejected.
        raise HostNotAllowedError(
            "The git URL must not contain a username or password. "
            "Put the token in the PAT field instead."
        )
    host = parsed.hostname or ""
    if host not in allowed_hosts():
        raise HostNotAllowedError(
            f"Git host {host!r} is not in the allowlist. "
            f"Allowed: {sorted(allowed_hosts())}. "
            "Add additional hosts via ADDITIONAL_GIT_HOSTS env var."
        )


def scrub_pat(text: str, *secrets: str) -> str:
    """Replace PAT tokens in ``text`` with ``***``.

    Catches the ``x-access-token:<pat>@`` URL form (clones made before the PAT
    moved to an HTTP header still have it in .git/config) and any of
    ``secrets`` verbatim (the PAT itself and its Basic-auth encoding).
    """
    text = _PAT_SCRUB_RE.sub("x-access-token:***@", text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


# Environment variables git and context-link need to run, find a proxy or CA
# bundle, and on Windows start at all (TLS breaks without SYSTEMROOT).
# Everything else, including ANTHROPIC_API_KEY, OPENAI_API_KEY, AWS_*,
# CONFIG_SECRET and JWT_SECRET, stays out of their environment (review S8): a
# git hook or a compromised indexer could otherwise read it.
_SUBPROCESS_ENV_KEYS = (
    "PATH",
    "PATHEXT",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "GIT_SSL_CAINFO",
)


def subprocess_env(**extra: str) -> dict[str, str]:
    """A minimal environment for git and context-link, plus ``extra``."""
    env = {k: v for k in _SUBPROCESS_ENV_KEYS if (v := os.environ.get(k)) is not None}
    env.update({"GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"})
    env.update(extra)
    return env


def pat_header_env(git_url: str, pat: str) -> dict[str, str]:
    """Git config, as environment variables, that sends ``pat`` to the URL's host.

    The PAT used to go in the clone URL, so it was on git's command line (the
    process list) and in clear text in the clone's .git/config (BB-74). An
    ``http.<url>.extraHeader`` scoped to scheme://host[:port]/ is sent only to
    that host, not on a redirect elsewhere. GIT_CONFIG_COUNT needs git 2.31+;
    an older git ignores it and the clone fails as unauthenticated.
    """
    parsed = urlparse(git_url)
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    basic = base64.b64encode(f"x-access-token:{pat}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{parsed.scheme}://{host}/.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
    }


def _find_escaping_path(clone_dir: Path) -> Path | None:
    """The first entry under ``clone_dir`` whose resolved path is outside it.

    followlinks=False so the walk never *descends* into a symlinked directory
    (no loops from circular links); each entry is still resolved, which catches
    a file or directory link pointing outside. Blocking: run it in a thread.
    """
    base = clone_dir.resolve()
    for dirpath, dirs, fnames in os.walk(clone_dir, followlinks=False):
        for name in [*dirs, *fnames]:
            candidate = Path(dirpath) / name
            try:
                candidate.resolve().relative_to(base)
            except (ValueError, OSError):
                return candidate
    return None


def is_sha_ref(ref: str | None) -> bool:
    """Return True when ``ref`` looks like a hex commit SHA (needs full clone).

    Note: short branch names that are also valid hex strings (e.g. ``deadbeef``)
    will match and trigger a full clone rather than ``--depth 1``. This is
    conservatively correct — slower but never wrong — because a shallow clone
    cannot satisfy an arbitrary commit SHA lookup.
    """
    return bool(ref and _SHA_REF_RE.match(ref))


def validate_git_ref(ref: str) -> None:
    """Raise ``InvalidRefError`` unless ``ref`` is a valid branch, tag or commit name.

    The ref ends up on git's argv, so a value like ``--orphan`` would be parsed
    as an option. Applies the `git check-ref-format` rules without spawning git;
    a leading ``-`` is never a valid ref name.
    """
    components = ref.split("/")
    if (
        not ref
        or len(ref) > _MAX_REF_LENGTH
        or ref.startswith(("-", "/"))
        or ref.endswith(("/", "."))
        or ref == "@"
        or _REF_FORBIDDEN_RE.search(ref)
        or any(c.startswith(".") or c.endswith(".lock") for c in components)
    ):
        raise InvalidRefError(
            f"Invalid ref {ref[:100]!r}: expected a branch, tag or commit SHA "
            "(git check-ref-format rules; must not start with '-')."
        )


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


def is_task_active(source_id: str) -> bool:
    """True while this process is indexing the source (its work or its live run)."""
    task = _active_tasks.get(source_id)
    if task is not None and not task.done():
        return True
    run = _live_runs().get_run(source_id)
    return run is not None and run.task is not None and not run.task.done()


def forget(source_id: str) -> None:
    """Purge all module state for a deleted source.

    Call after cancel_and_wait + DB delete so there is no unbounded accumulation
    of per-UUID entries across create→delete cycles. The source's stored runs
    and events are deleted with its row (migration 0021's trigger).
    """
    _locks.pop(source_id, None)
    _cancel_events.pop(source_id, None)
    _active_tasks.pop(source_id, None)
    _queues.pop(source_id, None)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _publish(source_id: str, event: SourceEvent) -> None:
    """Hand ``event`` to the source's live run, which stores it for followers.

    Synchronous on purpose: the clone/index steps call it between awaits, and
    the queue keeps their order. Without a live run (``run_clone_and_index``
    called directly) there is nobody to store it for, and it is dropped.
    """
    queue = _queues.get(source_id)
    if queue is None:
        logger.debug("No live run for source %s; dropped event %r", source_id, event.message)
        return
    queue.put_nowait(event)


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
    # Rows stored before the route validated refs could still hold an option-like value.
    if ref:
        try:
            validate_git_ref(ref)
        except InvalidRefError as exc:
            err = str(exc)
            await update_code_source_status(source_id, status="failed", error=err)
            _publish(
                source_id, SourceEvent(source_id, "failed", "validate", "Ref rejected", error=err)
            )
            return

    # ── Step 1: clone ────────────────────────────────────────────────────
    if cancel_event.is_set():
        return

    await update_code_source_status(source_id, status="cloning")
    _publish(source_id, SourceEvent(source_id, "cloning", "cloning", f"Cloning {git_url}…"))

    clone_dir = clone_dir_for(source_id)
    if clone_dir.exists():
        await asyncio.to_thread(shutil.rmtree, clone_dir, True)
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    # The PAT travels as an HTTP header in git's environment, never in the URL.
    auth_env: dict[str, str] = {}
    secrets: tuple[str, ...] = ()
    if source.get("has_pat"):
        try:
            pat = await get_code_source_pat(source_id)
            if pat:
                auth_env = pat_header_env(git_url, pat)
                secrets = (pat, auth_env["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: "))
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

    git_env = subprocess_env(**auth_env)
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
    # A shallow clone only fetches one branch, so a named branch or tag must be
    # cloned with --branch (a later checkout of it would not find it). A SHA
    # needs full history and is checked out after the clone.
    if not is_sha_ref(ref):
        clone_args += ["--depth", "1"]
        if ref:
            clone_args.append(f"--branch={ref}")
    clone_args += ["--", git_url, str(clone_dir)]

    rc, _, stderr = await _run_subprocess(clone_args, cancel_event, env=git_env)
    if cancel_event.is_set():
        return

    if rc != 0:
        scrubbed = scrub_pat(stderr, *secrets)
        if rc == 128 and _AUTH_FAILURE_RE.search(scrubbed):
            err = "Token rejected by git host — rotate the PAT in Settings."
        else:
            err = scrubbed or f"git clone exited with code {rc}"
        await update_code_source_status(source_id, status="failed", error=err)
        _publish(source_id, SourceEvent(source_id, "failed", "cloning", "Clone failed", error=err))
        return

    # Post-clone path-containment check: reject any entry whose resolved path
    # escapes the clone root. core.symlinks=false is the first line of
    # defence; this walk is belt-and-suspenders. Off the event loop (review
    # A3): on a large monorepo it took seconds and stalled every request.
    escaping = await asyncio.to_thread(_find_escaping_path, clone_dir)
    if escaping is not None:
        err = f"Clone rejected: path escapes clone directory: {escaping}"
        logger.warning("Source %s: %s", source_id, err)
        await asyncio.to_thread(shutil.rmtree, clone_dir, True)
        await update_code_source_status(source_id, status="failed", error=err)
        _publish(
            source_id,
            SourceEvent(source_id, "failed", "cloning", "Path containment check failed", error=err),
        )
        return

    # A SHA ref: check it out from the full clone. The trailing "--" stops git
    # reading the ref as a path; it still resolves a remote branch that only
    # looks like a SHA (e.g. "deadbeef").
    if is_sha_ref(ref):
        co_rc, _, co_err = await _run_subprocess(
            ["git", "-C", str(clone_dir), "checkout", ref, "--"],
            cancel_event,
            env=git_env,
        )
        if cancel_event.is_set():
            return
        if co_rc != 0:
            err = scrub_pat(co_err, *secrets) or f"git checkout {ref!r} exited with code {co_rc}"
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
    _raw_sha = sha_out.strip()
    resolved_sha: str | None = (
        _raw_sha[:40]
        if sha_rc == 0
        and len(_raw_sha) >= 40
        and all(c in "0123456789abcdef" for c in _raw_sha[:40])
        else None
    )

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

    # Index DB is stored on the container's native filesystem (not the
    # bind-mounted volume) to avoid SQLite mmap failures on Windows Docker.
    cl_db = index_db_for(source_id)
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
            files, nbytes = await asyncio.to_thread(_walk_stats, clone_dir)
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
        # Its own minimal environment: no PAT, no server secrets (review S8).
        idx_rc, _, idx_err = await _run_subprocess(
            [cl_binary, "index", str(clone_dir), "--db-path", str(cl_db)],
            cancel_event,
            env=subprocess_env(),
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
        err = scrub_pat(idx_err, *secrets) or f"context-link index exited with code {idx_rc}"
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
            # Clear the cancel event so a future re-index starts clean.
            cancel_event.clear()


async def _index_events(source_id: str) -> AsyncIterator[str]:
    """The live run's event stream: runs the clone + index, yields its events.

    The work runs as its own task and hands events over through a queue, so
    the steps stay plain awaits calling ``_publish``. If the live run is
    cancelled (server shutdown), the work is first asked to stop through its
    cancel event, which kills a running git or context-link subprocess, and
    only cancelled outright if it doesn't stop in time.
    """
    queue: asyncio.Queue = asyncio.Queue()
    _queues[source_id] = queue
    cancel_event = _cancel_events.setdefault(source_id, asyncio.Event())
    cancel_event.clear()
    work = asyncio.create_task(run_clone_and_index(source_id), name=f"clone-{source_id}")
    _active_tasks[source_id] = work
    work.add_done_callback(lambda _task: queue.put_nowait(None))
    try:
        while (event := await queue.get()) is not None:
            yield f"data: {event.to_sse_data()}\n\n"
    finally:
        if not work.done():
            cancel_event.set()
            try:
                await asyncio.wait_for(asyncio.shield(work), _STOP_GRACE_S)
            except TimeoutError:
                work.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await work
        if _queues.get(source_id) is queue:
            del _queues[source_id]
        if _active_tasks.get(source_id) is work:
            del _active_tasks[source_id]


async def schedule_clone_and_index(source_id: str, *, requeue: bool = False) -> "LiveRun":
    """Claim the source and start a background clone + index; return its live run.

    Raises ``backend.pipeline.live_runs.RunAlreadyActiveError`` if the source
    is already being indexed (by this process or another on the same
    database). ``requeue`` resets the status to 'queued' once the claim is
    held, for a re-index; a new source starts 'queued' already.
    """

    async def set_queued() -> None:
        await update_code_source_status(source_id, status="queued")

    async def mark_interrupted() -> str:
        message = "Indexing interrupted: the server shut down before it finished."
        await update_code_source_status(source_id, status="failed", error=message)
        event = SourceEvent(source_id, "failed", "interrupted", message, error=message)
        return f"data: {event.to_sse_data()}\n\n"

    return await _live_runs().start_run(
        source_id,
        _index_events(source_id),
        mark_interrupted,
        kind="index",
        subject_type="code_source",
        on_claimed=set_queued if requeue else None,
    )


async def cancel_and_wait(source_id: str, timeout: float = 5.0) -> bool:  # noqa: ASYNC109
    """Signal cancellation for ``source_id`` and wait up to ``timeout`` seconds.

    Waits for the clone/index work and for its live run (which records the
    end). Returns True if both stopped within the timeout, False otherwise.
    """
    ev = _cancel_events.get(source_id)
    if ev:
        ev.set()
    run = _live_runs().get_run(source_id)
    tasks = {
        t
        for t in (_active_tasks.get(source_id), run.task if run is not None else None)
        if t is not None and not t.done()
    }
    if not tasks:
        return True
    # asyncio.wait never cancels what it waits for, so a timeout leaves the
    # work running (the caller answers 409 and the client retries).
    _, pending = await asyncio.wait(tasks, timeout=timeout)
    return not pending
