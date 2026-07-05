"""CRUD operations for the activity log and user notifications (Phase 5).

Read operations use db.reader() (read-only pool connection).
Write operations use db.get() (writer singleton).
"""

import asyncio
import json
import logging
from typing import Any

from backend.db.connection import db
from backend.db.crud import generate_id, now_iso
from backend.db.utils import row_to_dict as _row


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


async def log_activity(
    project_id: str | None,
    user_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append an activity log entry. The log is append-only — no update/delete."""
    entry_id = generate_id()
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO activity_log
           (id, project_id, user_id, entity_type, entity_id, action, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry_id,
            project_id,
            user_id,
            entity_type,
            entity_id,
            action,
            json.dumps(details) if details is not None else None,
            now,
        ),
    )
    await conn.commit()
    return {
        "id": entry_id,
        "project_id": project_id,
        "user_id": user_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "details": details,
        "created_at": now,
    }


async def list_activity(project_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent activity entries for a project, newest first."""
    async with db.reader() as conn:
        async with conn.execute(
            """SELECT a.*, u.username, u.display_name
               FROM activity_log a
               LEFT JOIN users u ON u.id = a.user_id
               WHERE a.project_id = ?
               ORDER BY a.created_at DESC
               LIMIT ?""",
            (project_id, limit),
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    for row in rows:
        row["details"] = json.loads(row["details"]) if row.get("details") else None
    return rows


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


async def create_notification(
    user_id: str,
    notification_type: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> dict[str, Any]:
    notification_id = generate_id()
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO notifications
           (id, user_id, type, title, body, entity_type, entity_id, is_read, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (notification_id, user_id, notification_type, title, body, entity_type, entity_id, now),
    )
    await conn.commit()
    # Built from known inputs rather than re-SELECTing — every field here was
    # supplied by the caller or generated just above.
    return {
        "id": notification_id,
        "user_id": user_id,
        "type": notification_type,
        "title": title,
        "body": body,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "is_read": 0,
        "created_at": now,
    }


async def notify_users(
    user_ids: set[str] | list[str],
    notification_type: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Create the same notification for multiple users, skipping duplicates.

    Fanned out with asyncio.gather rather than a sequential loop — these are
    independent inserts (distinct user_id, no shared state to race on).
    """
    await asyncio.gather(
        *(
            create_notification(
                user_id=user_id,
                notification_type=notification_type,
                title=title,
                body=body,
                entity_type=entity_type,
                entity_id=entity_id,
            )
            for user_id in {uid for uid in user_ids if uid}
        )
    )


async def get_notification(notification_id: str) -> dict[str, Any] | None:
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        ) as cur:
            return _row(await cur.fetchone())


async def list_notifications(
    user_id: str, limit: int = 50, unread_only: bool = False
) -> list[dict[str, Any]]:
    query = "SELECT * FROM notifications WHERE user_id = ?"
    params: list[Any] = [user_id]
    if unread_only:
        query += " AND is_read = 0"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    async with db.reader() as conn:
        async with conn.execute(query, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def mark_notification_read(notification_id: str, user_id: str) -> dict[str, Any] | None:
    """Mark a single notification read. Returns None if not found or not owned."""
    notification = await get_notification(notification_id)
    if notification is None or notification["user_id"] != user_id:
        return None
    conn = await db.get()
    await conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ?",
        (notification_id,),
    )
    await conn.commit()
    # Already have the full row from the ownership check above — patch it in
    # memory instead of a third round-trip re-SELECT.
    notification["is_read"] = 1
    return notification


async def mark_all_read(user_id: str) -> None:
    conn = await db.get()
    await conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
        (user_id,),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Best-effort wrappers for route instrumentation
#
# Activity logging and notifications are side effects of a mutation, not the
# mutation itself — a DB hiccup here must never turn a successful approve/
# comment/invite into a 500. Mirrors the _embed_approved_threat pattern in
# routes/threats.py.
# ---------------------------------------------------------------------------


async def safe_log_activity(
    project_id: str | None,
    user_id: str | None,
    entity_type: str,
    entity_id: str,
    action: str,
    details: dict[str, Any] | None = None,
) -> None:
    try:
        await log_activity(project_id, user_id, entity_type, entity_id, action, details)
    except Exception as exc:
        logger.warning(f"Failed to log activity ({entity_type}/{action}): {exc}")


async def safe_notify_users(
    user_ids: set[str] | list[str],
    notification_type: str,
    title: str,
    body: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    try:
        await notify_users(user_ids, notification_type, title, body, entity_type, entity_id)
    except Exception as exc:
        logger.warning(f"Failed to send notifications ({notification_type}): {exc}")
