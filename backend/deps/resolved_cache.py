"""Last-known npm registry resolution per `name@version`, for offline runs.

A warm source cache alone can't serve an offline run: `analyze_package()`
resolves against the live registry *before* `fetch_source()` ever looks at the
cache. Each successful online resolve is therefore saved here, and replayed
when the registry is unreachable.

Stored under `DEPS_CACHE_DIR/_resolved/`, never inside a source cache entry:
those directories are exactly what Semgrep scans and drift compares, so an
extra file there would read as a tarball-only file and raise false drift.
Cache eviction skips this directory (it only considers subdirectories that
carry a `.complete` marker), and entries are left alone when their source
entry is evicted — each is a few hundred bytes, and a stale one is harmless:
offline, the source fetch it leads to fails exactly as it would have without
it; online, it's never read.
"""

import asyncio
import contextlib
import logging
import os
import tempfile
from pathlib import Path

from pydantic import ValidationError

from backend.config import settings
from backend.deps.fetcher import cache_dir_for
from backend.models.dependencies import ResolvedPackage
from backend.models.enums import SourceKind


logger = logging.getLogger(__name__)

_RESOLVED_DIRNAME = "_resolved"


def resolved_path_for(name: str, version: str) -> Path:
    # cache_dir_for() validates name/version against path traversal and
    # supplies the same `<sanitized-name>@<version>` leaf the source cache uses.
    leaf = cache_dir_for(SourceKind.NPM_TARBALL, name, version).name
    return Path(settings.deps_cache_dir) / _RESOLVED_DIRNAME / f"{leaf}.json"


def _write_atomic(path: Path, text: str) -> None:
    """Temp file + rename in the same directory, so a concurrent reader (or a
    crash mid-write) sees either the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        tmp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


async def save_resolved(resolved: ResolvedPackage) -> None:
    """Record `resolved` for offline reuse. Never raises: failing to write this
    must not fail an analysis that has already resolved successfully."""
    try:
        path = resolved_path_for(resolved.name, resolved.version)
        await asyncio.to_thread(_write_atomic, path, resolved.model_dump_json())
    except (OSError, ValueError):
        logger.warning(
            "Could not cache registry metadata for %s@%s",
            resolved.name,
            resolved.version,
            exc_info=True,
        )


async def load_cached_resolved(name: str, version: str) -> ResolvedPackage | None:
    """The last metadata saved for `name@version`, or None if there is none or
    it's unreadable."""
    try:
        path = resolved_path_for(name, version)
        text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning("Could not read cached registry metadata for %s@%s", name, version)
        return None
    try:
        resolved = ResolvedPackage.model_validate_json(text)
    except ValidationError:
        logger.warning("Ignoring corrupt cached registry metadata for %s@%s", name, version)
        return None
    if resolved.name != name or resolved.version != version:
        logger.warning("Ignoring mismatched cached registry metadata for %s@%s", name, version)
        return None
    return resolved
