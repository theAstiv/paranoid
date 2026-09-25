"""Shared helper for navigating a fetched package's on-disk layout.

`fetch_source()` (backend/deps/fetcher.py) strips the tarball's wrapper
directory (npm's `package/`, GitHub's `{repo}-{ref}/`, plus any
`repo_directory` for a monorepo) during scoped extraction, so the directory
it returns normally holds package.json etc. directly. `content_root()`
exists as a defensive collapse for any layout built by hand (fixtures,
tests) that still carries a single wrapper level, and is a no-op on a real
fetch. Any "exactly one entry means a wrapper" check must ignore dotfiles,
or it never collapses on a real fetched package (only ever in tests that
don't create the `.complete` marker).
"""

from pathlib import Path


def content_root(path: Path) -> Path:
    """Collapse `path`'s single non-hidden top-level directory, if there is one."""
    entries = [p for p in path.iterdir() if not p.name.startswith(".")]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return path
