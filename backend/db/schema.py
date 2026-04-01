"""Database schema definitions for SQLite."""

import logging

import aiosqlite

from backend.db.connection import db


logger = logging.getLogger(__name__)


# Schema version for migrations
SCHEMA_VERSION = 1


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
    updated_at TEXT NOT NULL
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


CREATE_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_threats_model_id ON threats(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_threats_status ON threats(status);",
    "CREATE INDEX IF NOT EXISTS idx_threats_stride ON threats(stride_category);",
    "CREATE INDEX IF NOT EXISTS idx_assets_model_id ON assets(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_flows_model_id ON flows(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_runs_model_id ON pipeline_runs(model_id);",
    "CREATE INDEX IF NOT EXISTS idx_threat_metadata_threat_id ON threat_metadata(threat_id);",
]


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
