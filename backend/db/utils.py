"""Shared row-conversion helper for CRUD modules."""

import aiosqlite


def row_to_dict(row: aiosqlite.Row | None) -> dict | None:
    return dict(row) if row else None
