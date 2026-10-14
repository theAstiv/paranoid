"""Filesystem layout helpers for persisted code sources.

Derived from ``settings.db_path`` rather than stored on the row so that
volume remounts (Docker bind-mount change, a different host path during
dev vs CI) don't leave rows pointing at stale absolute paths.
"""

import re
import tempfile
from pathlib import Path

from backend.config import settings


# A source id is always uuid4().hex from crud.create_code_source. Enforcing it here
# means a URL-supplied id can never walk out of the sources directory.
_SOURCE_ID_RE = re.compile(r"[0-9a-f]{32}")


def _check_source_id(source_id: str) -> str:
    if not _SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError("source id must be 32 lowercase hex characters")
    return source_id


def data_dir() -> Path:
    """Directory that holds the SQLite DB, source-key file, and clones."""
    return Path(settings.db_path).parent


def clone_dir_for(source_id: str) -> Path:
    """The directory a source's ``git clone`` lives in.

    The caller is responsible for creating / rmtreeing. Raises ``ValueError``
    unless ``source_id`` is exactly 32 lowercase hex characters.
    """
    return data_dir() / "sources" / _check_source_id(source_id)


def index_db_for(source_id: str) -> Path:
    """Path for the context-link index database.

    Stored on the container's native filesystem (system temp dir) rather
    than in the clone directory, which sits on a bind-mounted volume.
    Windows Docker bind mounts don't support SQLite's memory-mapped I/O,
    causing ``SQLITE_CANTOPEN (14)`` on ``open()``.

    The index is cheap to regenerate (~20 s for a 350-file repo), so
    loss on container restart is acceptable.

    Raises ``ValueError`` unless ``source_id`` is exactly 32 lowercase hex characters.
    """
    _check_source_id(source_id)
    base = Path(tempfile.gettempdir()) / "paranoid-indexes"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{source_id}.db"
