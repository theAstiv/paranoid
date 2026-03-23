"""Async CRUD operations for SQLite database."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite


logger = logging.getLogger(__name__)


def generate_id() -> str:
    """Generate a UUID for database records."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Get current timestamp in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


# Threat Models CRUD


async def create_threat_model(
    db_path: str,
    title: str,
    description: str,
    provider: str,
    model: str,
    framework: str = "STRIDE",
    iteration_count: int = 1,
) -> str:
    """Create a new threat model."""
    model_id = generate_id()
    now = now_iso()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO threat_models (
                id, title, description, framework, provider, model,
                status, iteration_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_id,
                title,
                description,
                framework,
                provider,
                model,
                "pending",
                iteration_count,
                now,
                now,
            ),
        )
        await db.commit()

    logger.info(f"Created threat model {model_id}")
    return model_id


async def get_threat_model(db_path: str, model_id: str) -> dict[str, Any] | None:
    """Get a threat model by ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM threat_models WHERE id = ?", (model_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def update_threat_model_status(
    db_path: str, model_id: str, status: str
) -> None:
    """Update threat model status."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            UPDATE threat_models
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, now_iso(), model_id),
        )
        await db.commit()

    logger.info(f"Updated threat model {model_id} status to {status}")


async def list_threat_models(db_path: str, limit: int = 50) -> list[dict[str, Any]]:
    """List all threat models."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM threat_models ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Threats CRUD


async def create_threat(
    db_path: str,
    model_id: str,
    name: str,
    description: str,
    target: str,
    impact: str,
    likelihood: str,
    mitigations: list[str],
    stride_category: str | None = None,
    maestro_category: str | None = None,
    dread_score: float | None = None,
    iteration_number: int = 1,
) -> str:
    """Create a new threat."""
    threat_id = generate_id()
    now = now_iso()
    mitigations_json = json.dumps(mitigations)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO threats (
                id, model_id, stride_category, maestro_category, name,
                description, target, impact, likelihood, dread_score,
                mitigations, status, iteration_number, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                threat_id,
                model_id,
                stride_category,
                maestro_category,
                name,
                description,
                target,
                impact,
                likelihood,
                dread_score,
                mitigations_json,
                "pending",
                iteration_number,
                now,
                now,
            ),
        )
        await db.commit()

    logger.info(f"Created threat {threat_id} for model {model_id}")
    return threat_id


async def get_threat(db_path: str, threat_id: str) -> dict[str, Any] | None:
    """Get a threat by ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM threats WHERE id = ?", (threat_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                threat = dict(row)
                threat["mitigations"] = json.loads(threat["mitigations"])
                return threat
            return None


async def list_threats(
    db_path: str, model_id: str, status: str | None = None
) -> list[dict[str, Any]]:
    """List threats for a model, optionally filtered by status."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row

        if status:
            query = "SELECT * FROM threats WHERE model_id = ? AND status = ? ORDER BY created_at"
            params = (model_id, status)
        else:
            query = "SELECT * FROM threats WHERE model_id = ? ORDER BY created_at"
            params = (model_id,)

        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            threats = []
            for row in rows:
                threat = dict(row)
                threat["mitigations"] = json.loads(threat["mitigations"])
                threats.append(threat)
            return threats


async def update_threat_status(
    db_path: str, threat_id: str, status: str
) -> None:
    """Update threat status (pending/approved/rejected)."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            UPDATE threats
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, now_iso(), threat_id),
        )
        await db.commit()

    logger.info(f"Updated threat {threat_id} status to {status}")


# Assets CRUD


async def create_asset(
    db_path: str, model_id: str, asset_type: str, name: str, description: str
) -> str:
    """Create a new asset."""
    asset_id = generate_id()
    now = now_iso()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO assets (id, model_id, type, name, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (asset_id, model_id, asset_type, name, description, now),
        )
        await db.commit()

    return asset_id


async def list_assets(db_path: str, model_id: str) -> list[dict[str, Any]]:
    """List all assets for a model."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM assets WHERE model_id = ? ORDER BY created_at", (model_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Flows CRUD


async def create_flow(
    db_path: str,
    model_id: str,
    flow_type: str,
    flow_description: str,
    source_entity: str,
    target_entity: str,
) -> str:
    """Create a new data flow."""
    flow_id = generate_id()
    now = now_iso()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO flows (
                id, model_id, flow_type, flow_description,
                source_entity, target_entity, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (flow_id, model_id, flow_type, flow_description, source_entity, target_entity, now),
        )
        await db.commit()

    return flow_id


async def list_flows(db_path: str, model_id: str) -> list[dict[str, Any]]:
    """List all data flows for a model."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM flows WHERE model_id = ? ORDER BY created_at", (model_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Pipeline Runs CRUD


async def create_pipeline_run(
    db_path: str,
    model_id: str,
    iteration: int,
    step: str,
    input_hash: str,
    output_hash: str,
    provider: str,
    duration_ms: int,
    tokens_used: int | None = None,
) -> str:
    """Create a pipeline run audit record."""
    run_id = generate_id()
    now = now_iso()

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(
            """
            INSERT INTO pipeline_runs (
                id, model_id, iteration, step, input_hash, output_hash,
                provider, tokens_used, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                model_id,
                iteration,
                step,
                input_hash,
                output_hash,
                provider,
                tokens_used,
                duration_ms,
                now,
            ),
        )
        await db.commit()

    return run_id


async def get_pipeline_stats(db_path: str, model_id: str) -> dict[str, Any]:
    """Get pipeline execution statistics for a model."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            """
            SELECT
                COUNT(*) as total_steps,
                SUM(duration_ms) as total_duration_ms,
                SUM(tokens_used) as total_tokens,
                AVG(duration_ms) as avg_duration_ms
            FROM pipeline_runs
            WHERE model_id = ?
            """,
            (model_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "total_steps": row[0],
                    "total_duration_ms": row[1],
                    "total_tokens": row[2],
                    "avg_duration_ms": row[3],
                }
            return {}
