"""Shared helper for navigating a fetched package's on-disk layout.

`fetch_source()` (backend/deps/fetcher.py) never strips the tarball/tarfile's
single top-level wrapper directory (npm's `package/`, GitHub's
`{repo}-{ref}/`) from the directory it returns — and that directory also
carries a sibling `.complete` marker file once the fetch finishes. Any
"exactly one entry means a wrapper" check must ignore dotfiles, or it never
collapses on a real fetched package (only ever in tests that don't create
the marker).
"""

from pathlib import Path


def content_root(path: Path) -> Path:
    """Collapse `path`'s single non-hidden top-level directory, if there is one."""
    entries = [p for p in path.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return path
