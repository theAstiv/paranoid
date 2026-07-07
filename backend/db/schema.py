"""Database schema — public constants and the init_database_with_connection entry point.

Schema changes: add a new file to backend/db/migrations/ (NNNN_description.py)
exposing  async def up(conn).  Do NOT add inline ALTER TABLE patches here.

SCHEMA_VERSION is kept for one release as a read-only fallback; new code
should use the schema_migrations ledger table as the authoritative source.
"""

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
    code_summary TEXT,
    assumptions TEXT
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

CREATE_COMMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    threat_model_id TEXT NOT NULL REFERENCES threat_models(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    parent_id TEXT REFERENCES comments(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

CREATE_THREAT_MODEL_ASSIGNEES_TABLE = """
CREATE TABLE IF NOT EXISTS threat_model_assignees (
    id TEXT PRIMARY KEY,
    threat_model_id TEXT NOT NULL REFERENCES threat_models(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assigned_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    UNIQUE(threat_model_id, user_id)
);
"""

# Append-only audit trail. project_id uses CASCADE — list_activity() only
# ever queries by an exact project_id, so a SET NULL row would be preserved
# in the table but permanently unreachable via any API (projects are
# soft-deleted/archived today, never hard-deleted, but this keeps a future
# hard-delete from silently orphaning history instead of erroring loudly).
# user_id stays SET NULL: the entry is still reachable via project_id even
# after the acting user is deleted.
CREATE_ACTIVITY_LOG_TABLE = """
CREATE TABLE IF NOT EXISTS activity_log (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL
);
"""

CREATE_NOTIFICATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    entity_type TEXT,
    entity_id TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
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
    # Phase 3 indices
    "CREATE INDEX IF NOT EXISTS idx_comments_model_id ON comments(threat_model_id);",
    "CREATE INDEX IF NOT EXISTS idx_comments_parent_id ON comments(parent_id);",
    "CREATE INDEX IF NOT EXISTS idx_assignees_model_id ON threat_model_assignees(threat_model_id);",
    "CREATE INDEX IF NOT EXISTS idx_assignees_user_id ON threat_model_assignees(user_id);",
    # Phase 4 indices
    "CREATE INDEX IF NOT EXISTS idx_threat_metadata_project ON threat_metadata(project_id);",
    # Phase 5 indices
    "CREATE INDEX IF NOT EXISTS idx_activity_project_created ON activity_log(project_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_activity_user_created ON activity_log(user_id, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_activity_entity ON activity_log(entity_type, entity_id);",
    "CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created "
    "ON notifications(user_id, is_read, created_at);",
]


async def init_database_with_connection(conn: aiosqlite.Connection) -> None:
    """Initialize (or migrate) the database schema using an existing connection.

    Delegates entirely to the migration ledger runner.  To add a new schema
    change, drop a file in backend/db/migrations/ — do not add code here.

    Args:
        conn: Active aiosqlite connection (PRAGMA foreign_keys already ON).
    """
    from backend.db.migrations.runner import run_migrations

    logger.info("Initializing database schema via migration ledger")
    await run_migrations(conn)
    logger.info("Database schema initialized successfully")


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
