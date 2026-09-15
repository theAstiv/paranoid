"""Staleness detection queries for threat models."""

import logging

from backend.db.connection import db


logger = logging.getLogger(__name__)


async def find_stale_models() -> list[dict]:
    """Find completed models whose updated_at exceeds the project staleness threshold.

    Returns dicts with keys: id, title, updated_at, project_id, threshold_days, days_stale.
    """
    conn = await db.get()
    async with conn.execute(
        """
        SELECT
            tm.id,
            tm.title,
            tm.updated_at,
            tm.project_id,
            COALESCE(p.staleness_threshold_days, 30) AS threshold_days,
            CAST(julianday('now') - julianday(tm.updated_at) AS INTEGER) AS days_stale
        FROM threat_models tm
        LEFT JOIN projects p ON p.id = tm.project_id
        WHERE tm.status = 'completed'
          AND tm.provider != 'seed'
          AND julianday('now') - julianday(tm.updated_at)
              > COALESCE(p.staleness_threshold_days, 30)
        """
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_recently_notified_model_ids(since_hours: int = 23) -> set[str]:
    """Return model IDs that already had a staleness notification in the last N hours."""
    conn = await db.get()
    async with conn.execute(
        """
        SELECT DISTINCT entity_id
        FROM notifications
        WHERE type = 'model_stale'
          AND created_at > datetime('now', ?)
        """,
        (f"-{since_hours} hours",),
    ) as cursor:
        rows = await cursor.fetchall()
        return {row["entity_id"] for row in rows}
