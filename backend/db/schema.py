"""Database schema definitions for SQLite."""

import logging

import aiosqlite

from backend.db.connection import db


logger = logging.getLogger(__name__)


# Schema version for migrations
SCHEMA_VERSION = 2


CREATE_THREAT_MODELS_TABLE = """
CREATE TABLE IF NOT EXISTS threat_models (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    framework TEXT DEFAULT 'STRIDE',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    iteration_count INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    code_source_id TEXT REFERENCES code_sources(id) ON DELETE SET NULL,
    created_by TEXT,
    gap_summaries TEXT,
    code_summary TEXT
);
"""


CREATE_THREATS_TABLE = """
CREATE TABLE IF NOT EXISTS threats (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    stride_category TEXT,
    maestro_category TEXT,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    target TEXT NOT NULL,
    impact TEXT NOT NULL,
    likelihood TEXT NOT NULL,
    dread_damage INTEGER,
    dread_reproducibility INTEGER,
    dread_exploitability INTEGER,
    dread_affected_users INTEGER,
    dread_discoverability INTEGER,
    dread_score REAL,
    mitigations TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    iteration_number INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


CREATE_ASSETS_TABLE = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    user_edited INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


CREATE_FLOWS_TABLE = """
CREATE TABLE IF NOT EXISTS flows (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    flow_type TEXT NOT NULL,
    flow_description TEXT NOT NULL,
    source_entity TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    user_edited INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


CREATE_TRUST_BOUNDARIES_TABLE = """
CREATE TABLE IF NOT EXISTS trust_boundaries (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    source_entity TEXT NOT NULL,
    target_entity TEXT NOT NULL,
    user_edited INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


CREATE_THREAT_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS threat_sources (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    example TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


CREATE_ATTACK_TREES_TABLE = """
CREATE TABLE IF NOT EXISTS attack_trees (
    id TEXT PRIMARY KEY,
    threat_id TEXT NOT NULL,
    mermaid_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (threat_id) REFERENCES threats(id) ON DELETE CASCADE
);
"""


CREATE_TEST_CASES_TABLE = """
CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    threat_id TEXT NOT NULL,
    gherkin_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (threat_id) REFERENCES threats(id) ON DELETE CASCADE
);
"""


CREATE_THREAT_METADATA_TABLE = """
CREATE TABLE IF NOT EXISTS threat_metadata (
    id TEXT PRIMARY KEY,
    threat_id TEXT,
    source TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_rowid INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY (threat_id) REFERENCES threats(id) ON DELETE CASCADE
);
"""


CREATE_PIPELINE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    iteration INTEGER NOT NULL,
    step TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    tokens_used INTEGER,
    duration_ms INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (model_id) REFERENCES threat_models(id) ON DELETE CASCADE
);
"""


# Runtime key/value store for config fields seeded at runtime (e.g. API keys
# entered via Settings UI). Values may be plaintext (encrypted=0) or Fernet
# ciphertext (encrypted=1). CRUD enforces encrypted=1 for *_api_key keys.
CREATE_CONFIG_TABLE = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value BLOB NOT NULL,
    encrypted INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


# Persistent code sources — git URL + optional PAT + cached index status.
# Clone location is derived at read time (see backend.sources.paths), not
# stored, so a volume remount doesn't break the row. pat_ciphertext is
# Fernet-encrypted; CRUD is the only layer that touches plaintext.
# UNIQUE (git_url, ref) is the concurrency guard — two simultaneous POSTs
# with the same target get a unique-violation which the route maps to 409.
# SQLite treats NULLs as distinct in UNIQUE constraints, so two rows with
# the same git_url and ref=NULL are both allowed. The CRUD layer rejects
# this at the application level by normalising ref=None to ref="" (empty
# string) before insert, which the UNIQUE constraint treats uniformly.
CREATE_CODE_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS code_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    git_url TEXT NOT NULL,
    ref TEXT,
    pat_ciphertext BLOB,
    pat_last_used_at TEXT,
    last_indexed_at TEXT,
    last_index_status TEXT,
    last_index_error TEXT,
    resolved_sha TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (git_url, ref)
);
"""


CREATE_USERS_TABLE = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    display_name TEXT,
    password_hash TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT
);
"""

CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
"""

CREATE_PERSONAL_ACCESS_TOKENS_TABLE = """
CREATE TABLE IF NOT EXISTS personal_access_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    project_id TEXT,
    last_used_at TEXT,
    expires_at TEXT,
    created_at TEXT NOT NULL
);
"""

CREATE_PROJECTS_TABLE = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    default_provider TEXT,
    default_model TEXT,
    default_iterations INTEGER,
    default_temperature REAL,
    is_archived INTEGER NOT NULL DEFAULT 0,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_PROJECT_MEMBERS_TABLE = """
CREATE TABLE IF NOT EXISTS project_members (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('owner', 'editor', 'viewer')),
    created_at TEXT NOT NULL,
    UNIQUE(project_id, user_id)
);
"""

CREATE_PROJECT_INVITATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS project_invitations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    invited_email TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('owner', 'editor', 'viewer')),
    invited_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'declined', 'expired')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    UNIQUE(project_id, invited_email)
);
"""

CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_threats_model_id ON threats(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_threats_status ON threats(status);",
    "CREATE INDEX IF NOT EXISTS idx_threats_stride ON threats(stride_category);",
    "CREATE INDEX IF NOT EXISTS idx_assets_model_id ON assets(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_flows_model_id ON flows(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_model_id ON pipeline_runs(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_threat_metadata_threat_id ON threat_metadata(threat_id);",
    # Auth indices
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username COLLATE NOCASE);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_pat_hash ON personal_access_tokens(token_hash);",
    "CREATE INDEX IF NOT EXISTS idx_pat_user_id ON personal_access_tokens(user_id);",
    # Phase 2 indices
    "CREATE INDEX IF NOT EXISTS idx_project_members_project_id ON project_members(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_project_members_user_id ON project_members(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_project_invitations_email ON project_invitations(invited_email);",
    "CREATE INDEX IF NOT EXISTS idx_threat_models_project_id ON threat_models(project_id);",
    "CREATE INDEX IF NOT EXISTS idx_code_sources_project_id ON code_sources(project_id);",
]


async def _migrate_v1_to_v2(conn: aiosqlite.Connection) -> None:
    """Idempotent v1→v2 migration inside a single IMMEDIATE transaction.

    Creates the Default Project (sentinel UUID), backfills project_id on
    threat_models and code_sources, sets user_version=2.
    Only runs when user_version < 2.
    """
    import uuid
    from datetime import UTC, datetime

    async with conn.execute("PRAGMA user_version;") as cur:
        row = await cur.fetchone()
    version = row[0] if row else 0
    if version >= 2:
        return

    default_project_id = "00000000-0000-0000-0000-000000000000"
    now = datetime.now(UTC).isoformat()

    # Resolve the admin user_id — may not exist yet if first run
    async with conn.execute("SELECT id FROM users WHERE username = 'admin' LIMIT 1") as cur:
        row = await cur.fetchone()
    admin_id = row[0] if row else None

    try:
        await conn.execute("BEGIN IMMEDIATE")

        # Create Default Project (idempotent via OR IGNORE)
        await conn.execute(
            """INSERT OR IGNORE INTO projects
               (id, name, description, is_archived, created_by, created_at, updated_at)
               VALUES (?, 'Default Project', 'Automatically created on first startup', 0, ?, ?, ?)""",
            (default_project_id, admin_id, now, now),
        )

        # Backfill threat_models
        await conn.execute(
            "UPDATE threat_models SET project_id = ? WHERE project_id IS NULL",
            (default_project_id,),
        )

        # Backfill code_sources
        await conn.execute(
            "UPDATE code_sources SET project_id = ? WHERE project_id IS NULL",
            (default_project_id,),
        )

        # Add admin as owner of Default Project (idempotent via OR IGNORE)
        if admin_id:
            member_id = str(uuid.uuid4())
            await conn.execute(
                """INSERT OR IGNORE INTO project_members
                   (id, project_id, user_id, role, created_at)
                   VALUES (?, ?, ?, 'owner', ?)""",
                (member_id, default_project_id, admin_id, now),
            )

        # Bump schema version — inside the same transaction
        await conn.execute("PRAGMA user_version = 2;")
        await conn.commit()
        logger.info("Schema migration v1→v2 complete (Default Project created)")
    except Exception:
        await conn.rollback()
        raise


async def init_database_with_connection(conn: aiosqlite.Connection) -> None:
    """Initialize database schema using an existing connection.

    Args:
        conn: Active aiosqlite connection (PRAGMA foreign_keys already set)
    """
    logger.info("Initializing database schema")

    # Create all tables
    await conn.execute(CREATE_THREAT_MODELS_TABLE)
    await conn.execute(CREATE_THREATS_TABLE)
    await conn.execute(CREATE_ASSETS_TABLE)
    await conn.execute(CREATE_FLOWS_TABLE)
    await conn.execute(CREATE_TRUST_BOUNDARIES_TABLE)
    await conn.execute(CREATE_THREAT_SOURCES_TABLE)
    await conn.execute(CREATE_ATTACK_TREES_TABLE)
    await conn.execute(CREATE_TEST_CASES_TABLE)
    await conn.execute(CREATE_THREAT_METADATA_TABLE)
    await conn.execute(CREATE_PIPELINE_RUNS_TABLE)
    await conn.execute(CREATE_CONFIG_TABLE)
    await conn.execute(CREATE_CODE_SOURCES_TABLE)
    # Auth tables (Phase 0)
    await conn.execute(CREATE_USERS_TABLE)
    await conn.execute(CREATE_SESSIONS_TABLE)
    await conn.execute(CREATE_PERSONAL_ACCESS_TOKENS_TABLE)
    # Phase 2 tables
    await conn.execute(CREATE_PROJECTS_TABLE)
    await conn.execute(CREATE_PROJECT_MEMBERS_TABLE)
    await conn.execute(CREATE_PROJECT_INVITATIONS_TABLE)

    # Add columns to threat_models that link to a code source and (reserved
    # for v2) record the creating user. Wrapped in try/except to stay
    # idempotent on databases that already ran this migration — same
    # pattern as the threat_metadata / user_edited migrations above.
    # Fresh DBs get these columns from CREATE_THREAT_MODELS_TABLE; only
    # pre-Task-4 DBs need the ALTER path.
    for column_sql in (
        "ALTER TABLE threat_models ADD COLUMN code_source_id TEXT "
        "REFERENCES code_sources(id) ON DELETE SET NULL",
        "ALTER TABLE threat_models ADD COLUMN created_by TEXT",
        "ALTER TABLE threat_models ADD COLUMN gap_summaries TEXT",
        "ALTER TABLE threat_models ADD COLUMN code_summary TEXT",
    ):
        try:
            await conn.execute(column_sql)
            await conn.commit()
            logger.info(f"Applied schema migration: {column_sql.split(' ADD COLUMN ', 1)[1]}")
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # Migrate existing threat_metadata tables that lack vector_rowid column
    try:
        await conn.execute("ALTER TABLE threat_metadata ADD COLUMN vector_rowid INTEGER")
        await conn.commit()
        logger.info("Migrated threat_metadata: added vector_rowid column")
    except aiosqlite.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise

    # Migrate existing assets/flows/trust_boundaries tables that lack user_edited column
    for table in ("assets", "flows", "trust_boundaries"):
        try:
            await conn.execute(f"ALTER TABLE {table} ADD COLUMN user_edited INTEGER DEFAULT 0")
            await conn.commit()
            logger.info(f"Migrated {table}: added user_edited column")
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # Phase 2: project_id on threat_models and code_sources
    for column_sql in (
        "ALTER TABLE threat_models ADD COLUMN project_id TEXT REFERENCES projects(id)",
        "ALTER TABLE code_sources ADD COLUMN project_id TEXT REFERENCES projects(id)",
    ):
        try:
            await conn.execute(column_sql)
            await conn.commit()
            logger.info(f"Applied schema migration: {column_sql.split(' ADD COLUMN ', 1)[1]}")
        except aiosqlite.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    # Create vector table for embeddings (384-dim, BAAI/bge-small-en-v1.5)
    # vec0 requires the sqlite-vec extension; skip gracefully if unavailable
    try:
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS threat_vectors
            USING vec0(
                embedding float[384]
            );
        """)
    except Exception:
        logger.warning(
            "sqlite-vec extension not available — threat_vectors table not created. "
            "Vector search features will be unavailable."
        )

    # Create indices
    for index_sql in CREATE_INDICES:
        await conn.execute(index_sql)

    await conn.commit()

    await _migrate_v1_to_v2(conn)

    logger.info("Database schema initialized successfully")


async def init_database(db_path: str) -> None:
    """Initialize database with schema (legacy function for standalone use).

    Prefer init_database_with_connection() when using ConnectionManager.
    """
    logger.info(f"Initializing database at {db_path}")

    async with aiosqlite.connect(db_path) as db:
        # Enable foreign keys
        await db.execute("PRAGMA foreign_keys = ON;")

        # Create all tables
        await db.execute(CREATE_THREAT_MODELS_TABLE)
        await db.execute(CREATE_THREATS_TABLE)
        await db.execute(CREATE_ASSETS_TABLE)
        await db.execute(CREATE_FLOWS_TABLE)
        await db.execute(CREATE_TRUST_BOUNDARIES_TABLE)
        await db.execute(CREATE_THREAT_SOURCES_TABLE)
        await db.execute(CREATE_ATTACK_TREES_TABLE)
        await db.execute(CREATE_TEST_CASES_TABLE)
        await db.execute(CREATE_THREAT_METADATA_TABLE)
        await db.execute(CREATE_PIPELINE_RUNS_TABLE)
        await db.execute(CREATE_CONFIG_TABLE)
        await db.execute(CREATE_CODE_SOURCES_TABLE)

        # Create indices
        for index_sql in CREATE_INDICES:
            await db.execute(index_sql)

        await db.commit()

    logger.info("Database initialized successfully")


async def get_schema_version() -> int:
    """Get current schema version."""
    try:
        conn = await db.get()
        async with conn.execute("PRAGMA user_version;") as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.warning(f"Could not read schema version: {e}")
        return 0


async def set_schema_version(version: int) -> None:
    """Set schema version."""
    conn = await db.get()
    await conn.execute(f"PRAGMA user_version = {version};")
    await conn.commit()
