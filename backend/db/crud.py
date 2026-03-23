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


async def update_threat_model(
    db_path: str,
    model_id: str,
    title: str | None = None,
    description: str | None = None,
    framework: str | None = None,
    status: str | None = None,
) -> None:
    """
    Update threat model details. Only provided fields will be updated.

    Args:
        db_path: Path to SQLite database
        model_id: ID of threat model to update
        title: Model title
        description: Model description
        framework: Framework (STRIDE, MAESTRO, etc.)
        status: Status (pending, in_progress, completed, failed)
    """
    update_fields = []
    params = []

    if title is not None:
        update_fields.append("title = ?")
        params.append(title)

    if description is not None:
        update_fields.append("description = ?")
        params.append(description)

    if framework is not None:
        update_fields.append("framework = ?")
        params.append(framework)

    if status is not None:
        update_fields.append("status = ?")
        params.append(status)

    # Always update timestamp
    update_fields.append("updated_at = ?")
    params.append(now_iso())
    params.append(model_id)

    if len(update_fields) == 1:
        logger.warning(f"No fields provided to update for model {model_id}")
        return

    query = f"UPDATE threat_models SET {', '.join(update_fields)} WHERE id = ?"

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(query, params)
        await db.commit()

    logger.info(f"Updated threat model {model_id}")


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


async def update_threat(
    db_path: str,
    threat_id: str,
    name: str | None = None,
    description: str | None = None,
    target: str | None = None,
    impact: str | None = None,
    likelihood: str | None = None,
    mitigations: list[str] | None = None,
    stride_category: str | None = None,
    maestro_category: str | None = None,
    dread_damage: int | None = None,
    dread_reproducibility: int | None = None,
    dread_exploitability: int | None = None,
    dread_affected_users: int | None = None,
    dread_discoverability: int | None = None,
    dread_score: float | None = None,
) -> None:
    """
    Update threat details. Only provided fields will be updated.

    Args:
        db_path: Path to SQLite database
        threat_id: ID of threat to update
        name: Threat name
        description: Threat description
        target: Threat target
        impact: Impact assessment
        likelihood: Likelihood assessment
        mitigations: List of mitigation strategies
        stride_category: STRIDE category
        maestro_category: MAESTRO category
        dread_damage: DREAD damage score (0-10)
        dread_reproducibility: DREAD reproducibility score (0-10)
        dread_exploitability: DREAD exploitability score (0-10)
        dread_affected_users: DREAD affected users score (0-10)
        dread_discoverability: DREAD discoverability score (0-10)
        dread_score: Overall DREAD score
    """
    # Build dynamic UPDATE query for only provided fields
    update_fields = []
    params = []

    if name is not None:
        update_fields.append("name = ?")
        params.append(name)

    if description is not None:
        update_fields.append("description = ?")
        params.append(description)

    if target is not None:
        update_fields.append("target = ?")
        params.append(target)

    if impact is not None:
        update_fields.append("impact = ?")
        params.append(impact)

    if likelihood is not None:
        update_fields.append("likelihood = ?")
        params.append(likelihood)

    if mitigations is not None:
        update_fields.append("mitigations = ?")
        params.append(json.dumps(mitigations))

    if stride_category is not None:
        update_fields.append("stride_category = ?")
        params.append(stride_category)

    if maestro_category is not None:
        update_fields.append("maestro_category = ?")
        params.append(maestro_category)

    if dread_damage is not None:
        update_fields.append("dread_damage = ?")
        params.append(dread_damage)

    if dread_reproducibility is not None:
        update_fields.append("dread_reproducibility = ?")
        params.append(dread_reproducibility)

    if dread_exploitability is not None:
        update_fields.append("dread_exploitability = ?")
        params.append(dread_exploitability)

    if dread_affected_users is not None:
        update_fields.append("dread_affected_users = ?")
        params.append(dread_affected_users)

    if dread_discoverability is not None:
        update_fields.append("dread_discoverability = ?")
        params.append(dread_discoverability)

    if dread_score is not None:
        update_fields.append("dread_score = ?")
        params.append(dread_score)

    # Always update the updated_at timestamp
    update_fields.append("updated_at = ?")
    params.append(now_iso())

    # Add threat_id as final parameter
    params.append(threat_id)

    if len(update_fields) == 1:  # Only updated_at, nothing to update
        logger.warning(f"No fields provided to update for threat {threat_id}")
        return

    query = f"UPDATE threats SET {', '.join(update_fields)} WHERE id = ?"

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(query, params)
        await db.commit()

    logger.info(f"Updated threat {threat_id} with {len(update_fields)} fields")


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


async def update_asset(
    db_path: str,
    asset_id: str,
    name: str | None = None,
    description: str | None = None,
    asset_type: str | None = None,
) -> None:
    """
    Update asset details. Only provided fields will be updated.

    Args:
        db_path: Path to SQLite database
        asset_id: ID of asset to update
        name: Asset name
        description: Asset description
        asset_type: Asset type (Asset/Entity)
    """
    update_fields = []
    params = []

    if name is not None:
        update_fields.append("name = ?")
        params.append(name)

    if description is not None:
        update_fields.append("description = ?")
        params.append(description)

    if asset_type is not None:
        update_fields.append("type = ?")
        params.append(asset_type)

    params.append(asset_id)

    if not update_fields:
        logger.warning(f"No fields provided to update for asset {asset_id}")
        return

    query = f"UPDATE assets SET {', '.join(update_fields)} WHERE id = ?"

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.execute(query, params)
        await db.commit()

    logger.info(f"Updated asset {asset_id}")


async def delete_threat(db_path: str, threat_id: str) -> None:
    """
    Delete a threat and its associated data.

    Args:
        db_path: Path to SQLite database
        threat_id: ID of threat to delete
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # Delete threat (CASCADE will handle related records)
        await db.execute("DELETE FROM threats WHERE id = ?", (threat_id,))
        await db.commit()

    logger.info(f"Deleted threat {threat_id}")


async def delete_threat_model(db_path: str, model_id: str) -> None:
    """
    Delete a threat model and all associated data.

    Args:
        db_path: Path to SQLite database
        model_id: ID of threat model to delete
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # Delete model (CASCADE will handle all related records)
        await db.execute("DELETE FROM threat_models WHERE id = ?", (model_id,))
        await db.commit()

    logger.info(f"Deleted threat model {model_id}")


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
