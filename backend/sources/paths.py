"""Filesystem layout helpers for persisted code sources.

Derived from ``settings.db_path`` rather than stored on the row so that
volume remounts (Docker bind-mount change, a different host path during
dev vs CI) don't leave rows pointing at stale absolute paths.
"""

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
