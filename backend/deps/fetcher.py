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
import hashlib
import logging
import shutil
import tarfile
import tempfile
from collections.abc import AsyncIterator
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


def _reject_unsafe_member(member: tarfile.TarInfo, extract_root: Path) -> None:
    """Raise UnsafeTarMemberError for anything that isn't a plain file or directory."""
    if member.issym() or member.islnk():
        raise UnsafeTarMemberError(f"Refusing to extract symlink/hardlink member: {member.name!r}")
    if member.isdev() or member.isfifo():
        raise UnsafeTarMemberError(f"Refusing to extract device/FIFO member: {member.name!r}")
    if not (member.isfile() or member.isdir()):
        raise UnsafeTarMemberError(f"Refusing to extract unsupported member type: {member.name!r}")

    name = member.name
    if name.startswith("/") or name.startswith("\\"):
        raise UnsafeTarMemberError(f"Refusing absolute-path member: {name!r}")

    target = extract_root / name
    if not check_path_containment(target, extract_root):
        raise UnsafeTarMemberError(f"Refusing path-traversal member: {name!r}")


def _safe_extract(tar_path: Path, extract_root: Path) -> None:
    """Extract `tar_path` into `extract_root`, rejecting hostile members before any write.

    Synchronous — always run through `asyncio.to_thread` by the caller. Uses
    tarfile's own "data" filter (PEP 706) as a backstop, plus explicit
    member-by-member validation (absolute paths, traversal, symlinks, hardlinks,
    device/FIFO nodes) and enforced size/file-count caps — checked before each
    member is written, not after.
    """
    extract_root.mkdir(parents=True, exist_ok=True)
    file_count = 0
    extracted_bytes = 0

    try:
        with tarfile.open(tar_path, mode="r:gz") as tar:
            for member in tar:
                _reject_unsafe_member(member, extract_root)

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

                tar.extract(member, path=extract_root, filter="data")
    except tarfile.FilterError as exc:
        # tarfile's own "data" filter rejecting a member we didn't already
        # catch (e.g. a mode/ownership anomaly) is still an unsafe-member
        # finding, not a parse failure.
        raise UnsafeTarMemberError(f"Rejected by extraction filter: {exc}") from exc
    except (tarfile.TarError, EOFError, OSError) as exc:
        raise CorruptTarballError(f"Could not parse tarball {tar_path}: {exc}") from exc


def _scope_to_directory(extract_root: Path, repo_directory: str | None) -> Path | None:
    """For GitHub monorepos, narrow to `repo_directory` inside the extracted tree.

    GitHub tarballs extract under a single top-level `{repo}-{ref}/` directory;
    that layer is transparently skipped when locating `repo_directory`. Returns
    None (not the unscoped root) when the directory isn't found — e.g. it was
    renamed or moved at this ref — so the caller never silently attributes an
    entire monorepo's capabilities to one package.
    """
    if not repo_directory:
        return extract_root

    top_level = [p for p in extract_root.iterdir() if p.is_dir()]
    base = top_level[0] if len(top_level) == 1 else extract_root
    candidate = base / repo_directory
    if not check_path_containment(candidate, extract_root):
        raise UnsafeTarMemberError(f"repo_directory escapes extraction root: {repo_directory!r}")
    return candidate if candidate.is_dir() else None


async def fetch_source(
    resolved: ResolvedPackage,
    kind: SourceKind,
    client: httpx.AsyncClient | None = None,
) -> Path | None:
    """Fetch and safely extract `resolved`'s source for `kind`, using a per-version cache.

    Returns the extraction directory, or None when the source is unavailable —
    GitHub not resolved, or (for a monorepo) `repo_directory` not found at this
    ref — never raises for either case. Raises a `FetchError` subclass for a
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
        return None

    cache_dir = cache_dir_for(kind, resolved.name, resolved.version)
    marker = cache_dir / ".complete"
    if marker.is_file():
        return cache_dir

    key = cache_key(kind, resolved.name, resolved.version)
    async with _locked(key):
        # Re-check after acquiring the lock: a concurrent fetch may have finished.
        if marker.is_file():
            return cache_dir

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
            await asyncio.to_thread(_safe_extract, tar_path, extract_root)
            tar_path.unlink(missing_ok=True)

            if kind == SourceKind.GITHUB:
                scoped_root = _scope_to_directory(extract_root, resolved.repo_directory)
                if scoped_root is None:
                    logger.warning(
                        "repo_directory %r not found in %s/%s@%s — treating GitHub source as unavailable",
                        resolved.repo_directory,
                        resolved.repo_owner,
                        resolved.repo_name,
                        resolved.github_ref,
                    )
                    return None
            else:
                scoped_root = extract_root

            if cache_dir.exists():
                await asyncio.to_thread(shutil.rmtree, cache_dir, ignore_errors=True)
            await asyncio.to_thread(shutil.move, str(scoped_root), str(cache_dir))
            (cache_dir / ".complete").touch()
            logger.info(
                "Fetched %s %s@%s -> %s", kind.value, resolved.name, resolved.version, cache_dir
            )
            return cache_dir
        finally:
            await asyncio.to_thread(shutil.rmtree, tmp_dir, ignore_errors=True)
            if owns_client:
                await client.aclose()
