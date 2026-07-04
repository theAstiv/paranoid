"""CRUD operations for threat model comments and assignees (Phase 3)."""

import uuid
from datetime import UTC, datetime

from backend.db.connection import db
from backend.db.utils import row_to_dict as _row


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


async def create_comment(
    threat_model_id: str,
    user_id: str | None,
    body: str,
    parent_id: str | None = None,
) -> dict:
    comment_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO comments
           (id, threat_model_id, user_id, parent_id, body, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (comment_id, threat_model_id, user_id, parent_id, body, now, now),
    )
    await conn.commit()
    return await get_comment(comment_id)


async def get_comment(comment_id: str) -> dict | None:
    conn = await db.get()
    async with conn.execute(
        """SELECT c.*, u.username, u.display_name
           FROM comments c
           LEFT JOIN users u ON u.id = c.user_id
           WHERE c.id = ?""",
        (comment_id,),
    ) as cur:
        return _row(await cur.fetchone())


async def list_comments(threat_model_id: str) -> list[dict]:
    conn = await db.get()
    async with conn.execute(
        """SELECT c.*, u.username, u.display_name
           FROM comments c
           LEFT JOIN users u ON u.id = c.user_id
           WHERE c.threat_model_id = ?
           ORDER BY c.created_at ASC""",
        (threat_model_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def update_comment(comment_id: str, body: str) -> dict | None:
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        "UPDATE comments SET body = ?, updated_at = ? WHERE id = ?",
        (body, now, comment_id),
    )
    await conn.commit()
    return await get_comment(comment_id)


async def delete_comment(comment_id: str) -> None:
    conn = await db.get()
    await conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    await conn.commit()


# ---------------------------------------------------------------------------
# Assignees
# ---------------------------------------------------------------------------


async def get_assignee(threat_model_id: str, user_id: str) -> dict | None:
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM threat_model_assignees WHERE threat_model_id = ? AND user_id = ?",
        (threat_model_id, user_id),
    ) as cur:
        return _row(await cur.fetchone())


async def add_assignee(threat_model_id: str, user_id: str, assigned_by: str | None) -> dict:
    assignee_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        """INSERT OR IGNORE INTO threat_model_assignees
           (id, threat_model_id, user_id, assigned_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (assignee_id, threat_model_id, user_id, assigned_by, now),
    )
    await conn.commit()
    return await get_assignee(threat_model_id, user_id)


async def remove_assignee(threat_model_id: str, user_id: str) -> None:
    conn = await db.get()
    await conn.execute(
        "DELETE FROM threat_model_assignees WHERE threat_model_id = ? AND user_id = ?",
        (threat_model_id, user_id),
    )
    await conn.commit()


async def list_assignees(threat_model_id: str) -> list[dict]:
    conn = await db.get()
    async with conn.execute(
        """SELECT a.*, u.username, u.email, u.display_name
           FROM threat_model_assignees a
           JOIN users u ON u.id = a.user_id
           WHERE a.threat_model_id = ?
           ORDER BY a.created_at""",
        (threat_model_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]
