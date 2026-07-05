"""Aggregate read queries for the project dashboard (Phase 7)."""

from __future__ import annotations

from typing import Any

from backend.db.connection import db


# Mirrors frontend/src/lib/utils.js::dreadColor — keep the two in sync.
_SEVERITY_CASE = """
    CASE
        WHEN t.dread_score >= 8 THEN 'critical'
        WHEN t.dread_score >= 6 THEN 'high'
        WHEN t.dread_score >= 4 THEN 'medium'
        ELSE 'low'
    END
"""


async def get_dashboard_stats(project_id: str) -> dict[str, Any]:
    """Header stat-card counts for a project: models, open threats, pending
    review, members, and the most recent model update (used for "last run")."""
    async with db.reader() as conn:
        async with conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM threat_models
                    WHERE project_id = ? AND provider != 'seed') AS model_count,
                (SELECT COUNT(*) FROM threats t
                    JOIN threat_models tm ON tm.id = t.model_id
                    WHERE tm.project_id = ? AND t.status = 'pending') AS open_threats,
                (SELECT COUNT(*) FROM threat_models
                    WHERE project_id = ? AND status = 'in_review') AS pending_review,
                (SELECT COUNT(*) FROM project_members
                    WHERE project_id = ?) AS member_count,
                (SELECT MAX(updated_at) FROM threat_models
                    WHERE project_id = ? AND provider != 'seed') AS last_run_at
            """,
            (project_id, project_id, project_id, project_id, project_id),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}


async def get_severity_breakdown(project_id: str) -> dict[str, int]:
    """Counts of open (pending) threats in a project, bucketed by DREAD severity."""
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    async with db.reader() as conn:
        async with conn.execute(
            f"""
            SELECT {_SEVERITY_CASE} AS severity, COUNT(*) AS count
            FROM threats t
            JOIN threat_models tm ON tm.id = t.model_id
            WHERE tm.project_id = ? AND t.status = 'pending'
            GROUP BY severity
            """,
            (project_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                counts[row["severity"]] = row["count"]
    return counts


async def get_assigned_threats(
    project_id: str, user_id: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Open threats in models assigned to `user_id` within a project, ordered
    by DREAD score (highest first) — backs the "Assigned to you" panel."""
    async with db.reader() as conn:
        async with conn.execute(
            """
            SELECT t.id, t.name, t.stride_category, t.maestro_category, t.dread_score,
                   tm.id AS model_id, tm.title AS model_title
            FROM threat_model_assignees tma
            JOIN threat_models tm ON tm.id = tma.threat_model_id
            JOIN threats t ON t.model_id = tm.id
            WHERE tma.user_id = ? AND tm.project_id = ? AND t.status = 'pending'
            ORDER BY t.dread_score IS NULL, t.dread_score DESC
            LIMIT ?
            """,
            (user_id, project_id, limit),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
