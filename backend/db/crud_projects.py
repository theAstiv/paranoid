"""CRUD operations for projects, members, and invitations (Phase 2)."""

import uuid
from datetime import UTC, datetime, timedelta

import aiosqlite

from backend.db.connection import db


_DEFAULT_PROJECT_ID = "00000000-0000-0000-0000-000000000000"

ROLE_ORDER = {"owner": 3, "editor": 2, "viewer": 1}


def _row(row: aiosqlite.Row | None) -> dict | None:
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


async def create_project(
    name: str,
    created_by: str,
    description: str | None = None,
) -> dict:
    project_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        """INSERT INTO projects (id, name, description, is_archived, created_by, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?, ?)""",
        (project_id, name, description, created_by, now, now),
    )
    # Add creator as owner
    member_id = str(uuid.uuid4())
    await conn.execute(
        """INSERT INTO project_members (id, project_id, user_id, role, created_at)
           VALUES (?, ?, ?, 'owner', ?)""",
        (member_id, project_id, created_by, now),
    )
    await conn.commit()
    return await get_project(project_id)


async def get_project(project_id: str) -> dict | None:
    conn = await db.get()
    async with conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)) as cur:
        return _row(await cur.fetchone())


async def list_projects_for_user(user_id: str) -> list[dict]:
    """Return all non-archived projects the user is a member of."""
    conn = await db.get()
    async with conn.execute(
        """SELECT p.*, pm.role AS member_role
           FROM projects p
           JOIN project_members pm ON pm.project_id = p.id
           WHERE pm.user_id = ? AND p.is_archived = 0
           ORDER BY p.created_at DESC""",
        (user_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def list_all_projects() -> list[dict]:
    """Admin-only: return all projects including archived."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM projects ORDER BY created_at DESC") as cur:
        return [dict(r) for r in await cur.fetchall()]


async def update_project(project_id: str, **fields) -> dict | None:
    allowed = {
        "name",
        "description",
        "default_provider",
        "default_model",
        "default_iterations",
        "default_temperature",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return await get_project(project_id)
    now = datetime.now(UTC).isoformat()
    updates["updated_at"] = now
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = await db.get()
    await conn.execute(
        f"UPDATE projects SET {set_clause} WHERE id = ?",
        (*updates.values(), project_id),
    )
    await conn.commit()
    return await get_project(project_id)


async def archive_project(project_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    await conn.execute(
        "UPDATE projects SET is_archived = 1, updated_at = ? WHERE id = ?",
        (now, project_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


async def get_member(project_id: str, user_id: str) -> dict | None:
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ) as cur:
        return _row(await cur.fetchone())


async def list_members(project_id: str) -> list[dict]:
    conn = await db.get()
    async with conn.execute(
        """SELECT pm.*, u.username, u.email, u.display_name
           FROM project_members pm
           JOIN users u ON u.id = pm.user_id
           WHERE pm.project_id = ?
           ORDER BY pm.created_at""",
        (project_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def add_member(project_id: str, user_id: str, role: str) -> dict:
    member_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    conn = await db.get()
    try:
        await conn.execute(
            """INSERT INTO project_members (id, project_id, user_id, role, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (member_id, project_id, user_id, role, now),
        )
        await conn.commit()
    except aiosqlite.IntegrityError:
        # Already a member — update role instead
        await conn.execute(
            "UPDATE project_members SET role = ? WHERE project_id = ? AND user_id = ?",
            (role, project_id, user_id),
        )
        await conn.commit()
    return await get_member(project_id, user_id)


async def update_member_role(project_id: str, user_id: str, role: str) -> dict | None:
    conn = await db.get()
    await conn.execute(
        "UPDATE project_members SET role = ? WHERE project_id = ? AND user_id = ?",
        (role, project_id, user_id),
    )
    await conn.commit()
    return await get_member(project_id, user_id)


async def remove_member(project_id: str, user_id: str) -> None:
    """Remove a member. Raises ValueError if they are the last owner."""
    conn = await db.get()
    # Guard: cannot remove the last owner
    async with conn.execute(
        "SELECT COUNT(*) FROM project_members WHERE project_id = ? AND role = 'owner'",
        (project_id,),
    ) as cur:
        row = await cur.fetchone()
    owner_count = row[0] if row else 0

    member = await get_member(project_id, user_id)
    if member and member["role"] == "owner" and owner_count <= 1:
        raise ValueError("Cannot remove the last owner of a project")

    await conn.execute(
        "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


async def create_invitation(
    project_id: str,
    invited_email: str,
    role: str,
    invited_by: str,
    expires_in_days: int = 7,
) -> dict:
    inv_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    expires_at = (now + timedelta(days=expires_in_days)).isoformat()
    conn = await db.get()
    try:
        await conn.execute(
            """INSERT INTO project_invitations
               (id, project_id, invited_email, role, invited_by, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (inv_id, project_id, invited_email, role, invited_by, now.isoformat(), expires_at),
        )
        await conn.commit()
    except aiosqlite.IntegrityError:
        raise ValueError(f"{invited_email} already has a pending invitation to this project")
    return await get_invitation(inv_id)


async def get_invitation(invitation_id: str) -> dict | None:
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM project_invitations WHERE id = ?", (invitation_id,)
    ) as cur:
        return _row(await cur.fetchone())


async def list_invitations(project_id: str) -> list[dict]:
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM project_invitations WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def accept_invitation(invitation_id: str, user_id: str, user_email: str) -> dict:
    """Accept an invitation: verify email match, add member, mark accepted.

    Returns the member record.
    Raises ValueError on business-logic failures (wrong email, already used, expired).
    """
    inv = await get_invitation(invitation_id)
    if not inv:
        raise LookupError("Invitation not found")

    # Security: only the invited email address may accept
    if inv["invited_email"].lower() != user_email.lower():
        raise PermissionError("This invitation was not sent to your email address")

    if inv["status"] != "pending":
        raise ValueError(f"Invitation is already {inv['status']}")

    now = datetime.now(UTC)
    expires = datetime.fromisoformat(inv["expires_at"])
    # Make both timezone-aware for a correct comparison
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if now > expires:
        conn = await db.get()
        await conn.execute(
            "UPDATE project_invitations SET status = 'expired' WHERE id = ?",
            (invitation_id,),
        )
        await conn.commit()
        raise ValueError("Invitation has expired")

    conn = await db.get()
    await conn.execute(
        "UPDATE project_invitations SET status = 'accepted' WHERE id = ?",
        (invitation_id,),
    )
    await conn.commit()
    return await add_member(inv["project_id"], user_id, inv["role"])


async def decline_invitation(invitation_id: str) -> None:
    conn = await db.get()
    await conn.execute(
        "UPDATE project_invitations SET status = 'declined' WHERE id = ?",
        (invitation_id,),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------


async def get_user_role_in_project(project_id: str, user_id: str) -> str | None:
    """Return 'owner'/'editor'/'viewer' or None if not a member."""
    member = await get_member(project_id, user_id)
    return member["role"] if member else None


async def resolve_project_id_from_model(model_id: str) -> str | None:
    conn = await db.get()
    async with conn.execute(
        "SELECT project_id FROM threat_models WHERE id = ?", (model_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def resolve_project_id_from_threat(threat_id: str) -> str | None:
    conn = await db.get()
    async with conn.execute(
        """SELECT tm.project_id FROM threats t
           JOIN threat_models tm ON tm.id = t.model_id
           WHERE t.id = ?""",
        (threat_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def resolve_project_id_from_source(source_id: str) -> str | None:
    conn = await db.get()
    async with conn.execute(
        "SELECT project_id FROM code_sources WHERE id = ?", (source_id,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None
