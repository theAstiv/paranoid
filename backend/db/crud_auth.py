"""CRUD operations for users, sessions, and personal access tokens.

Read operations use db.reader() (read-only pool connection).
Write operations use db.get() (writer singleton).
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.db.connection import db
from backend.db.crud import generate_id, now_iso


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


async def create_user(
    username: str,
    email: str,
    password_hash: str,
    display_name: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any]:
    """Create a new user.

    Raises aiosqlite.IntegrityError on duplicate username/email.
    """
    user_id = generate_id()
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO users
            (id, username, email, display_name, password_hash,
             is_active, is_admin, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (user_id, username, email, display_name, password_hash, int(is_admin), now, now),
    )
    await conn.commit()
    user = await get_user_by_id(user_id)
    if user is None:
        msg = "Failed to create user"
        raise RuntimeError(msg)
    return user


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Fetch a user row by UUID."""
    async with db.reader() as conn:
        async with conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Case-insensitive username lookup."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Case-insensitive email lookup."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_last_login(user_id: str) -> None:
    """Stamp last_login_at for a successful authentication."""
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
        (now, now, user_id),
    )
    await conn.commit()


async def list_users() -> list[dict[str, Any]]:
    """List all users (admin-only). Excludes password_hash."""
    async with db.reader() as conn:
        async with conn.execute(
            """
            SELECT id, username, email, display_name, is_active, is_admin,
                   created_at, updated_at, last_login_at
            FROM users ORDER BY created_at
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def user_count() -> int:
    """Return the total number of user rows."""
    async with db.reader() as conn:
        async with conn.execute("SELECT COUNT(*) FROM users") as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ---------------------------------------------------------------------------
# Sessions (refresh tokens)
# ---------------------------------------------------------------------------


async def create_session(
    jti: str,
    user_id: str,
    expires_days: int = 7,
) -> dict[str, Any]:
    """Persist a refresh-token session."""
    now = now_iso()
    expires_at = (datetime.now(UTC) + timedelta(days=expires_days)).isoformat()
    conn = await db.get()
    await conn.execute(
        "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (jti, user_id, now, expires_at),
    )
    await conn.commit()
    return {
        "id": jti,
        "user_id": user_id,
        "created_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
    }


async def get_session(jti: str) -> dict[str, Any] | None:
    """Fetch a session by jti."""
    async with db.reader() as conn:
        async with conn.execute("SELECT * FROM sessions WHERE id = ?", (jti,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def revoke_session(jti: str) -> None:
    """Mark a single session as revoked."""
    conn = await db.get()
    await conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE id = ?",
        (now_iso(), jti),
    )
    await conn.commit()


async def revoke_all_user_sessions(user_id: str) -> None:
    """Revoke every active session for a user (stolen-token kill-switch)."""
    conn = await db.get()
    await conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now_iso(), user_id),
    )
    await conn.commit()


async def cleanup_expired_sessions() -> None:
    """Delete sessions that are expired or already revoked.

    Safe to call from startup and from a 24-h background task.
    """
    conn = await db.get()
    await conn.execute(
        "DELETE FROM sessions WHERE expires_at < ? OR revoked_at IS NOT NULL",
        (now_iso(),),
    )
    await conn.commit()


# ---------------------------------------------------------------------------
# Personal Access Tokens
# ---------------------------------------------------------------------------


async def create_pat(
    token_id: str,
    user_id: str,
    name: str,
    token_hash: str,
    project_id: str | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Persist a PAT row.  token_id and token_hash come from auth.tokens.create_pat()."""
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO personal_access_tokens
            (id, user_id, name, token_hash, project_id, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (token_id, user_id, name, token_hash, project_id, expires_at, now),
    )
    await conn.commit()
    pat = await get_pat_by_id(token_id)
    if pat is None:
        msg = "Failed to create PAT"
        raise RuntimeError(msg)
    return pat


async def get_pat_by_id(token_id: str) -> dict[str, Any] | None:
    """Fetch a PAT row by token_id (PK lookup for O(1) validation)."""
    async with db.reader() as conn:
        async with conn.execute(
            "SELECT * FROM personal_access_tokens WHERE id = ?", (token_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def list_pats(user_id: str) -> list[dict[str, Any]]:
    """Return metadata for all PATs owned by *user_id* (token_hash excluded)."""
    async with db.reader() as conn:
        async with conn.execute(
            """
            SELECT id, user_id, name, project_id, last_used_at, expires_at, created_at
            FROM personal_access_tokens
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def update_pat_last_used(token_id: str) -> None:
    """Stamp last_used_at (best-effort; not called inside critical path)."""
    conn = await db.get()
    await conn.execute(
        "UPDATE personal_access_tokens SET last_used_at = ? WHERE id = ?",
        (now_iso(), token_id),
    )
    await conn.commit()


async def delete_pat(token_id: str, user_id: str) -> bool:
    """Delete a PAT owned by *user_id*.

    Returns True unconditionally; the caller can verify via list_pats if needed.
    """
    conn = await db.get()
    await conn.execute(
        "DELETE FROM personal_access_tokens WHERE id = ? AND user_id = ?",
        (token_id, user_id),
    )
    await conn.commit()
    return True
