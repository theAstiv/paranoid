"""Safe fetch + extraction of npm tarball and GitHub source for the dependency engine.

Source is treated as hostile input: this module never executes package code
(no `npm install`, no lifecycle scripts) and never calls `tarfile.extractall()`
without per-member validation. Blocking filesystem work (extraction, move,
cleanup) runs off the event loop via `asyncio.to_thread` so a large tarball
never stalls other requests or SSE streams.
"""

import asyncio
import base64
import contextlib
import errno
import hashlib
import itertools
import json
import logging
import os
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import aiofiles
import httpx

from backend.config import settings
from backend.deps.resolver import github_tarball_url
from backend.models.dependencies import ResolvedPackage
from backend.models.enums import SourceKind
from backend.sources.manager import check_path_containment


logger = logging.getLogger(__name__)

_TIMEOUT_S = 60.0
_CHUNK_SIZE = 1024 * 1024  # 1 MiB
_MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
_MAX_EXTRACTED_FILES = 20_000

# Strongest-first: an SSRI string can carry several hashes ("sha512-... sha1-...");
# the strongest one present is what gets verified.
_INTEGRITY_STRENGTH = {"sha512": 4, "sha384": 3, "sha256": 2, "sha1": 1}

# Per-key locks, reference-counted so `_locks`/`_lock_refcounts` never grow
# unbounded across a long-running process scanning many packages. `_locks_guard`
# protects mutation of both dicts (the locks themselves guard the fetch/cache
# work, not their own bookkeeping).
_locks: dict[str, asyncio.Lock] = {}
_lock_refcounts: dict[str, int] = {}
_locks_guard = asyncio.Lock()


class FetchError(Exception):
    """Base class for fetch/extraction failures. Never leaves partial cache state."""


class IntegrityError(FetchError):
    """Downloaded tarball did not match the expected integrity hash, or it could
    not be parsed at all — this module fails closed rather than skipping
    verification silently."""


class TarballTooLargeError(FetchError):
    """Tarball (compressed or extracted) exceeded the configured size cap."""


class UnsafeTarMemberError(FetchError):
    """A tar member attempted path traversal, an absolute path, or a disallowed type."""


class CorruptTarballError(FetchError):
    """Tarball could not be parsed (truncated gzip, corrupt headers, etc.)."""


class PathTooLongError(FetchError):
    """A tar member's target path exceeded the OS path length limit (Windows
    MAX_PATH == 260, POSIX ENAMETOOLONG) even after scoped extraction narrowed
    the tree to the package's own subdirectory — a real large monorepo (e.g.
    Babel, Jest), not a corrupt tarball. Reported distinctly so the caller
    doesn't misreport it as `CorruptTarballError`."""


@dataclass(frozen=True)
class FetchResult:
    """Outcome of `fetch_source`. `path` is None exactly when `reason` is set,
    and never raises for an unavailable-but-not-hostile source (GitHub not
    resolved, a monorepo directory not found at this ref) — only a genuinely
    hostile/corrupt/oversized tarball raises a `FetchError` subclass.
    `skipped_long_paths` > 0 means the extraction is partial: those files
    exist in the source but couldn't be written because their path would
    exceed the platform's path-length limit."""

    path: Path | None
    skipped_links: int = 0
    skipped_long_paths: int = 0
    skipped_link_names: tuple[str, ...] = ()
    reason: str | None = None


@contextlib.asynccontextmanager
async def _locked(key: str) -> AsyncIterator[None]:
    """Hold the per-`key` lock, creating it on first use and dropping it when
    the last holder releases it."""
    async with _locks_guard:
        _lock_refcounts[key] = _lock_refcounts.get(key, 0) + 1
        lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            yield
    finally:
        async with _locks_guard:
            _lock_refcounts[key] -= 1
            if _lock_refcounts[key] <= 0:
                _lock_refcounts.pop(key, None)
                _locks.pop(key, None)


def _sanitize_name(name: str) -> str:
    """Scoped package names (`@scope/name`) can't be a single path segment."""
    return name.replace("/", "__")


def cache_key(kind: SourceKind, name: str, version: str) -> str:
    return f"{kind.value}:{name}@{version}"


def cache_dir_for(kind: SourceKind, name: str, version: str) -> Path:
    return Path(settings.deps_cache_dir) / kind.value / f"{_sanitize_name(name)}@{version}"


def _write_marker(marker: Path, extract: "_ExtractResult") -> None:
    """Record the fetch's skip counts/names in the `.complete` marker itself
    — not just logged — so a cache hit (which never re-runs `_safe_extract`)
    still reports a prior partial extraction instead of silently coming back
    clean on every subsequent call."""
    marker.write_text(
        json.dumps(
            {
                "skipped_links": extract.skipped_links,
                "skipped_long_paths": extract.skipped_long_paths,
                "skipped_link_names": list(extract.skipped_link_names),
            }
        ),
        encoding="utf-8",
    )


def _read_marker(marker: Path, cache_dir: Path) -> "FetchResult":
    """Best-effort read of a `.complete` marker's recorded skip metadata. A
    marker from before this metadata existed (or any parse failure) falls
    back to zero/empty — the same as a clean fetch — rather than raising."""
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return FetchResult(
        path=cache_dir,
        skipped_links=int(data.get("skipped_links", 0)),
        skipped_long_paths=int(data.get("skipped_long_paths", 0)),
        skipped_link_names=tuple(data.get("skipped_link_names", ())),
    )


def _parse_integrity(integrity: str) -> tuple[str, bytes]:
    """Parse an SSRI-style integrity string into (hashlib algo name, expected digest).

    Handles the modern `"sha512-<base64>"` form (possibly several space-separated
    hashes, strongest wins) and the legacy `dist.shasum` fallback — a bare hex
    SHA-1 with no algo prefix. Raises ValueError if `integrity` is non-empty but
    nothing parseable was found: this module fails closed rather than silently
    treating an unrecognised value as "nothing to verify".
    """
    if "-" not in integrity:
        try:
            return "sha1", bytes.fromhex(integrity)
        except ValueError as exc:
            raise ValueError(f"Unparseable integrity value: {integrity!r}") from exc

    best: tuple[str, bytes] | None = None
    for entry in integrity.split():
        algo, _, b64 = entry.partition("-")
        if algo not in _INTEGRITY_STRENGTH:
            continue
        try:
            digest = base64.b64decode(b64, validate=True)
        except (ValueError, TypeError):
            continue
        if best is None or _INTEGRITY_STRENGTH[algo] > _INTEGRITY_STRENGTH[best[0]]:
            best = (algo, digest)

    if best is None:
        raise ValueError(f"Unparseable integrity value: {integrity!r}")
    return best


async def _download_tarball(
    url: str,
    dest: Path,
    expected_integrity: str | None,
    client: httpx.AsyncClient,
) -> None:
    """Stream `url` to `dest`, hashing as it downloads. Raises on cap breach or mismatch.

    The hash runs over the compressed bytes exactly as they arrive on the wire —
    matching what `dist.integrity` (or the legacy `dist.shasum`) on the npm
    registry actually certifies.
    """
    max_bytes = settings.deps_max_tarball_mb * 1024 * 1024
    parsed: tuple[str, bytes] | None = None
    if expected_integrity:
        try:
            parsed = _parse_integrity(expected_integrity)
        except ValueError as exc:
            raise IntegrityError(str(exc)) from exc
    hasher = hashlib.new(parsed[0]) if parsed else None

    total = 0
    async with client.stream("GET", url, follow_redirects=True) as resp:
        resp.raise_for_status()
        async with aiofiles.open(dest, "wb") as f:
            async for chunk in resp.aiter_bytes(_CHUNK_SIZE):
                total += len(chunk)
                if total > max_bytes:
                    raise TarballTooLargeError(
                        f"Tarball exceeded {settings.deps_max_tarball_mb}MB compressed cap: {url}"
                    )
                if hasher is not None:
                    hasher.update(chunk)
                await f.write(chunk)

    if parsed is not None:
        _, expected_digest = parsed
        if hasher.digest() != expected_digest:
            raise IntegrityError(f"Integrity check failed for {url}")


def _reject_unsafe_member(member: tarfile.TarInfo, kind: SourceKind) -> bool:
    """Validate `member`'s type. Returns True when it should be silently
    skipped rather than extracted — a symlink/hardlink in a
    `SourceKind.GITHUB` tarball, since legitimate repos carry these (e.g.
    zod's `.codex/skills`, esbuild) and codeload tarballs aren't
    npm-registry-certified the way `npm pack` output is. `npm pack` never
    emits a symlink, so one in an `NPM_TARBALL` source means tampering and
    is always rejected outright.

    Path containment is *not* checked here — only the member's actual
    post-strip write target reflects where it's really extracted (see the
    containment check next to `tar.extract` in `_safe_extract`); checking
    the raw, prefix-included name against `extract_root` validates a path
    that's never written.
    """
    if member.issym() or member.islnk():
        if kind == SourceKind.GITHUB:
            return True
        raise UnsafeTarMemberError(f"Refusing to extract symlink/hardlink member: {member.name!r}")
    if member.isdev() or member.isfifo():
        raise UnsafeTarMemberError(f"Refusing to extract device/FIFO member: {member.name!r}")
    if not (member.isfile() or member.isdir()):
        raise UnsafeTarMemberError(f"Refusing to extract unsupported member type: {member.name!r}")
    if member.name.startswith("/") or member.name.startswith("\\"):
        raise UnsafeTarMemberError(f"Refusing absolute-path member: {member.name!r}")
    return False


def _normalize_repo_directory(repo_directory: str) -> str:
    """Collapse `./`, doubled slashes, and leading/trailing slashes out of a
    package.json `repository.directory` value (e.g. "./packages/core/") so
    it actually matches the tarball's real member paths instead of silently
    missing and being reported as `repo_directory_missing`."""
    return "/".join(part for part in repo_directory.split("/") if part not in ("", "."))


def _npm_rel_name(name: str) -> str:
    """Strip the first path segment of `name`, independently per member —
    matching what `npm install <tarball>` actually does: it strips one
    leading path component from *each entry separately*, not a single
    wrapper name assumed from the first entry seen. A crafted tarball can
    carry entries under different top-level names (`package/index.js` and
    `evil/backdoor.js`); real npm installs both (as `index.js` and
    `backdoor.js`). Assuming one global wrapper — as this module used to —
    would silently drop the second file from the scan while npm still
    installs it. A bare top-level entry (no "/") strips to nothing and
    npm installs it nowhere.
    """
    return name.partition("/")[2]


def _github_rel_name(name: str, wrapper: str, scoped: str | None) -> str | None:
    """Return `name`'s path relative to `wrapper` (and, for a monorepo, the
    normalized `scoped` `repo_directory`), or None if it falls outside the
    current `repo_directory` scope — a legitimate sibling package, silently
    skipped, not hostile.

    Raises `UnsafeTarMemberError` if `name` doesn't share the tarball's
    established top-level wrapper at all: unlike an npm tarball, a GitHub
    codeload archive always uses one consistent `{repo}-{ref}/` prefix for
    every entry, so a divergent one is a hostile/corrupt shape rather than
    something to quietly ignore.
    """
    if name != wrapper and not name.startswith(wrapper + "/"):
        raise UnsafeTarMemberError(
            f"GitHub tarball has an inconsistent top-level directory: {name!r} "
            f"does not match the established wrapper {wrapper!r}"
        )
    within_wrapper = name[len(wrapper) + 1 :] if name != wrapper else ""
    if scoped is None:
        return within_wrapper
    if within_wrapper == scoped:
        return ""
    if within_wrapper.startswith(scoped + "/"):
        return within_wrapper[len(scoped) + 1 :]
    return None


def _is_path_too_long(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 206 or exc.errno == errno.ENAMETOOLONG


# Windows' classic MAX_PATH (260, including the null terminator) still
# applies to plain (non `\\?\`-prefixed) paths on any machine without the
# LongPathsEnabled registry key set — which is the common case. Extracting
# via the `\\?\` escape would let the write itself succeed, but the file
# then becomes invisible to ordinary directory walks (`Path.rglob`, the
# Semgrep scan, `content_root()`) on that same machine: a silent partial
# scan is worse than a loud, counted skip. So this is checked proactively
# before ever attempting the write, on Windows only — POSIX's much higher
# path-length ceiling still relies on the reactive `_is_path_too_long` catch.
# The *directory* creation limit is shorter than the file-path limit (248,
# not 260 — historically MAX_PATH minus room for an 8.3 filename), so a
# short filename inside a long directory chain can still fail even though
# the full file path is under 260; both are checked.
_WINDOWS_MAX_PATH = 260
_WINDOWS_MAX_DIR_PATH = 248


def _exceeds_windows_path_limits(target: Path) -> bool:
    if os.name != "nt":
        return False
    if len(str(target)) >= _WINDOWS_MAX_PATH:
        return True
    return len(str(target.parent)) >= _WINDOWS_MAX_DIR_PATH


@dataclass(frozen=True)
class _ExtractResult:
    found: bool
    skipped_links: int = 0
    skipped_long_paths: int = 0
    skipped_link_names: tuple[str, ...] = ()


def _safe_extract(
    tar_path: Path, extract_root: Path, repo_directory: str | None, kind: SourceKind
) -> _ExtractResult:
    """Extract `tar_path`'s package subtree straight into `extract_root`.

    For `SourceKind.NPM_TARBALL`, each member's first path segment is
    stripped independently (matching `npm install`'s real behavior — see
    `_npm_rel_name`); a collision between two members' stripped paths is
    treated as tampering. For `SourceKind.GITHUB`, every member must share
    one consistent top-level wrapper (established from the first member);
    members outside a configured `repo_directory` are silently skipped as
    legitimate sibling-package content, and the size/file caps count only
    extracted members.

    Synchronous — always run through `asyncio.to_thread` by the caller. Uses
    tarfile's own "data" filter (PEP 706) as a backstop, plus explicit
    member-by-member validation (absolute paths, traversal, device/FIFO
    nodes, and — source-dependent — symlinks/hardlinks; see
    `_reject_unsafe_member`) checked before each member is written, not
    after.

    `found` is False when nothing matched the configured scope —
    `repo_directory` doesn't exist at this ref (renamed, moved), or the
    tarball is empty — so the caller can report the source as unavailable
    rather than silently returning an empty or unscoped tree. When
    `repo_directory` is None (the whole tarball is in scope), `found` starts
    True: an empty package is still "found", just empty.
    """
    extract_root.mkdir(parents=True, exist_ok=True)
    file_count = 0
    extracted_bytes = 0
    skipped_links = 0
    skipped_long_paths = 0
    skipped_link_names: list[str] = []
    found = repo_directory is None
    scoped = _normalize_repo_directory(repo_directory) if repo_directory else None
    seen_npm_rel_names: set[str] = set()

    try:
        with tarfile.open(tar_path, mode="r:gz") as tar:
            it = iter(tar)
            try:
                first = next(it)
            except StopIteration:
                # A genuinely empty tarball. Whole-package scope (no
                # repo_directory) still "finds" it — an empty package is a
                # valid (if unusual) result, not an unavailable source.
                return _ExtractResult(found=repo_directory is None)

            wrapper = first.name.split("/", 1)[0]
            if kind == SourceKind.GITHUB and (not wrapper or wrapper.startswith(("/", "\\"))):
                raise UnsafeTarMemberError(f"Refusing absolute/empty wrapper: {first.name!r}")

            for member in itertools.chain([first], it):
                name = member.name

                if kind == SourceKind.GITHUB:
                    rel_name = _github_rel_name(name, wrapper, scoped)
                    if rel_name is None:
                        continue  # sibling package outside repo_directory scope
                else:
                    rel_name = _npm_rel_name(name)

                if not rel_name:
                    continue  # the wrapper/scope directory entry itself
                found = True

                if kind == SourceKind.NPM_TARBALL:
                    if rel_name in seen_npm_rel_names:
                        raise UnsafeTarMemberError(
                            f"Duplicate install path after stripping the leading "
                            f"segment independently per npm's own convention: {rel_name!r}"
                        )
                    seen_npm_rel_names.add(rel_name)

                if _reject_unsafe_member(member, kind):
                    skipped_links += 1
                    skipped_link_names.append(rel_name)
                    continue

                target = extract_root / rel_name
                if not check_path_containment(target, extract_root):
                    raise UnsafeTarMemberError(f"Refusing path-traversal member: {name!r}")

                if _exceeds_windows_path_limits(target):
                    skipped_long_paths += 1
                    continue

                if member.isfile():
                    file_count += 1
                    if file_count > _MAX_EXTRACTED_FILES:
                        raise TarballTooLargeError(
                            f"Tarball has more than {_MAX_EXTRACTED_FILES} files"
                        )
                    extracted_bytes += member.size
                    if extracted_bytes > _MAX_EXTRACTED_BYTES:
                        raise TarballTooLargeError(
                            f"Tarball extracted size exceeded {_MAX_EXTRACTED_BYTES} bytes"
                        )

                member.name = rel_name
                tar.extract(member, path=extract_root, filter="data")
    except tarfile.FilterError as exc:
        # tarfile's own "data" filter rejecting a member we didn't already
        # catch (e.g. a mode/ownership anomaly) is still an unsafe-member
        # finding, not a parse failure.
        raise UnsafeTarMemberError(f"Rejected by extraction filter: {exc}") from exc
    except OSError as exc:
        if _is_path_too_long(exc):
            raise PathTooLongError(f"Path too long extracting {tar_path}: {exc}") from exc
        raise CorruptTarballError(f"Could not parse tarball {tar_path}: {exc}") from exc
    except (tarfile.TarError, EOFError) as exc:
        raise CorruptTarballError(f"Could not parse tarball {tar_path}: {exc}") from exc

    return _ExtractResult(
        found=found,
        skipped_links=skipped_links,
        skipped_long_paths=skipped_long_paths,
        skipped_link_names=tuple(skipped_link_names),
    )


async def fetch_source(
    resolved: ResolvedPackage,
    kind: SourceKind,
    client: httpx.AsyncClient | None = None,
) -> FetchResult:
    """Fetch and safely extract `resolved`'s source for `kind`, using a per-version cache.

    Returns a `FetchResult` with `path=None` and a `reason` when the source is
    unavailable — GitHub not resolved (`"github_unresolved"`), or (for a
    monorepo) `repo_directory` not found at this ref (`"repo_directory_missing"`)
    — never raises for either case. Raises a `FetchError` subclass for a
    hostile/corrupt/oversized tarball; the caller sees a typed error and no
    partial cache directory is ever left behind. Source is immutable per
    version, so a directory carrying the `.complete` marker is never re-fetched.

    An npm tarball with no integrity value at all (neither `dist.integrity` nor
    the legacy `dist.shasum` — vanishingly rare on the real registry) is
    rejected rather than fetched unverified: this module fails closed. GitHub
    source has no npm-registry-certified checksum to begin with, so that case
    is unaffected.
    """
    if kind == SourceKind.GITHUB and resolved.github_status != "resolved":
        return FetchResult(path=None, reason="github_unresolved")

    cache_dir = cache_dir_for(kind, resolved.name, resolved.version)
    marker = cache_dir / ".complete"
    if marker.is_file():
        return _read_marker(marker, cache_dir)

    key = cache_key(kind, resolved.name, resolved.version)
    async with _locked(key):
        # Re-check after acquiring the lock: a concurrent fetch may have finished.
        if marker.is_file():
            return _read_marker(marker, cache_dir)

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=_TIMEOUT_S)
        cache_dir.parent.mkdir(parents=True, exist_ok=True)
        # A random suffix avoids two worker processes colliding on the same
        # temp path — locks are per-process, so this is the only cross-process
        # guard. Fine for the single-worker Docker setup this project ships.
        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{cache_dir.name}.", dir=str(cache_dir.parent)))
        try:
            if kind == SourceKind.NPM_TARBALL:
                # Fail closed: an npm tarball with no integrity value at all
                # (neither dist.integrity nor the legacy dist.shasum —
                # vanishingly rare on the real registry) is never fetched
                # unverified. GitHub source has no npm-registry-certified
                # checksum to begin with, so that case is unaffected.
                if not resolved.integrity:
                    raise IntegrityError(
                        f"{resolved.name}@{resolved.version} has no integrity value to verify"
                    )
                url = resolved.tarball_url
                expected_integrity: str | None = resolved.integrity
            else:
                url = github_tarball_url(
                    resolved.repo_owner, resolved.repo_name, resolved.github_ref
                )
                expected_integrity = None  # no trusted checksum available from GitHub

            tar_path = tmp_dir / "source.tar.gz"
            await _download_tarball(url, tar_path, expected_integrity, client)

            extract_root = tmp_dir / "extracted"
            repo_directory = resolved.repo_directory if kind == SourceKind.GITHUB else None
            extract = await asyncio.to_thread(
                _safe_extract, tar_path, extract_root, repo_directory, kind
            )
            tar_path.unlink(missing_ok=True)

            if not extract.found:
                logger.warning(
                    "repo_directory %r not found in %s/%s@%s — treating GitHub source as unavailable",
                    resolved.repo_directory,
                    resolved.repo_owner,
                    resolved.repo_name,
                    resolved.github_ref,
                )
                return FetchResult(
                    path=None, skipped_links=extract.skipped_links, reason="repo_directory_missing"
                )

            if extract.skipped_long_paths:
                logger.warning(
                    "%d file(s) skipped for %s %s@%s: path would exceed the Windows "
                    "path-length limit — scan is partial",
                    extract.skipped_long_paths,
                    kind.value,
                    resolved.name,
                    resolved.version,
                )

            if cache_dir.exists():
                await asyncio.to_thread(shutil.rmtree, cache_dir, ignore_errors=True)
            await asyncio.to_thread(shutil.move, str(extract_root), str(cache_dir))
            await asyncio.to_thread(_write_marker, marker, extract)
            logger.info(
                "Fetched %s %s@%s -> %s (skipped_links=%d, skipped_long_paths=%d)",
                kind.value,
                resolved.name,
                resolved.version,
                cache_dir,
                extract.skipped_links,
                extract.skipped_long_paths,
            )
            return FetchResult(
                path=cache_dir,
                skipped_links=extract.skipped_links,
                skipped_long_paths=extract.skipped_long_paths,
                skipped_link_names=extract.skipped_link_names,
            )
        finally:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
            if owns_client:
                await client.aclose()
