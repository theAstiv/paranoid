"""Add entity_type and entity_id columns to comments for entity-level anchoring."""

import aiosqlite


async def up(conn: aiosqlite.Connection) -> None:
    try:
        await conn.execute("ALTER TABLE comments ADD COLUMN entity_type TEXT")
    except Exception:
        pass  # column already exists

    try:
        await conn.execute("ALTER TABLE comments ADD COLUMN entity_id TEXT")
    except Exception:
        pass  # column already exists

    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type, entity_id)"
    )
