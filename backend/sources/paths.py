"""Filesystem layout helpers for persisted code sources.

Derived from ``settings.db_path`` rather than stored on the row so that
volume remounts (Docker bind-mount change, a different host path during
dev vs CI) don't leave rows pointing at stale absolute paths.
"""

import tempfile
from pathlib import Path

from backend.config import settings


def data_dir() -> Path:
    """Directory that holds the SQLite DB, source-key file, and clones."""
    return Path(settings.db_path).parent


def clone_dir_for(source_id: str) -> Path:
    """The directory a source's ``git clone`` lives in.

    The caller is responsible for creating / rmtreeing. The id is a UUID4 hex
    from our own CRUD, so it is safe to concatenate directly.
    """
    return data_dir() / "sources" / source_id


def index_db_for(source_id: str) -> Path:
    """Path for the context-link index database.

    Stored on the container's native filesystem (system temp dir) rather
    than in the clone directory, which sits on a bind-mounted volume.
    Windows Docker bind mounts don't support SQLite's memory-mapped I/O,
    causing ``SQLITE_CANTOPEN (14)`` on ``open()``.

    The index is cheap to regenerate (~20 s for a 350-file repo), so
    loss on container restart is acceptable.
    """
    base = Path(tempfile.gettempdir()) / "paranoid-indexes"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{source_id}.db"
