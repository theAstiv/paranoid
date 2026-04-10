"""Async CRUD operations for SQLite database."""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.db.connection import db


logger = logging.getLogger(__name__)


def generate_id() -> str:
    """Generate a UUID for database records."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Get current timestamp in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


# Threat Models CRUD


async def create_threat_model(
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

    conn = await db.get()
    await conn.execute(
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
    await conn.commit()

    logger.info(f"Created threat model {model_id}")
    return model_id


async def get_threat_model(model_id: str) -> dict[str, Any] | None:
    """Get a threat model by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM threat_models WHERE id = ?", (model_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_threat_model_status(model_id: str, status: str) -> None:
    """Update threat model status."""
    conn = await db.get()
    await conn.execute(
        """
        UPDATE threat_models
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, now_iso(), model_id),
    )
    await conn.commit()

    logger.info(f"Updated threat model {model_id} status to {status}")


async def update_threat_model(
    model_id: str,
    title: str | None = None,
    description: str | None = None,
    framework: str | None = None,
    status: str | None = None,
) -> None:
    """
    Update threat model details. Only provided fields will be updated.

    Args:
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

    conn = await db.get()
    await conn.execute(query, params)
    await conn.commit()

    logger.info(f"Updated threat model {model_id}")


async def list_threat_models(limit: int = 50) -> list[dict[str, Any]]:
    """List all threat models with per-model threat counts."""
    conn = await db.get()
    async with conn.execute(
        """
        SELECT
            tm.*,
            COUNT(t.id) AS threat_count
        FROM threat_models tm
        LEFT JOIN threats t ON t.model_id = tm.id
        GROUP BY tm.id
        ORDER BY tm.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def find_threat_model_by_prefix(prefix: str) -> dict[str, Any] | None:
    """Find a threat model by ID prefix (first N characters).

    Returns the first match if the prefix is unambiguous, or None if no match.
    Raises ValueError if the prefix matches more than one model.
    """
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM threat_models WHERE id LIKE ? ORDER BY created_at DESC",
        (f"{prefix}%",),
    ) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        return None
    if len(rows) > 1:
        raise ValueError(
            f"Prefix '{prefix}' is ambiguous — matches {len(rows)} models. Use more characters."
        )
    return dict(rows[0])


# Threats CRUD


async def create_threat(
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
    dread_damage: float | None = None,
    dread_reproducibility: float | None = None,
    dread_exploitability: float | None = None,
    dread_affected_users: float | None = None,
    dread_discoverability: float | None = None,
    iteration_number: int = 1,
) -> str:
    """Create a new threat."""
    threat_id = generate_id()
    now = now_iso()
    mitigations_json = json.dumps(mitigations)

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO threats (
            id, model_id, stride_category, maestro_category, name,
            description, target, impact, likelihood,
            dread_damage, dread_reproducibility, dread_exploitability,
            dread_affected_users, dread_discoverability, dread_score,
            mitigations, status, iteration_number, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            dread_damage,
            dread_reproducibility,
            dread_exploitability,
            dread_affected_users,
            dread_discoverability,
            dread_score,
            mitigations_json,
            "pending",
            iteration_number,
            now,
            now,
        ),
    )
    await conn.commit()

    logger.info(f"Created threat {threat_id} for model {model_id}")
    return threat_id


async def get_threat(threat_id: str) -> dict[str, Any] | None:
    """Get a threat by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM threats WHERE id = ?", (threat_id,)) as cursor:
        row = await cursor.fetchone()
        if row:
            threat = dict(row)
            threat["mitigations"] = json.loads(threat["mitigations"])
            return threat
        return None


async def list_threats(model_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """List threats for a model, optionally filtered by status."""
    conn = await db.get()

    if status:
        query = "SELECT * FROM threats WHERE model_id = ? AND status = ? ORDER BY created_at"
        params = (model_id, status)
    else:
        query = "SELECT * FROM threats WHERE model_id = ? ORDER BY created_at"
        params = (model_id,)

    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        threats = []
        for row in rows:
            threat = dict(row)
            threat["mitigations"] = json.loads(threat["mitigations"])
            threats.append(threat)
        return threats


async def update_threat_status(threat_id: str, status: str) -> None:
    """Update threat status (pending/approved/rejected)."""
    conn = await db.get()
    await conn.execute(
        """
        UPDATE threats
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, now_iso(), threat_id),
    )
    await conn.commit()

    logger.info(f"Updated threat {threat_id} status to {status}")


async def update_threat(
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

    conn = await db.get()
    await conn.execute(query, params)
    await conn.commit()

    logger.info(f"Updated threat {threat_id} with {len(update_fields)} fields")


# Assets CRUD


async def create_asset(model_id: str, asset_type: str, name: str, description: str) -> str:
    """Create a new asset."""
    asset_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO assets (id, model_id, type, name, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (asset_id, model_id, asset_type, name, description, now),
    )
    await conn.commit()

    return asset_id


async def list_assets(model_id: str) -> list[dict[str, Any]]:
    """List all assets for a model."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM assets WHERE model_id = ? ORDER BY created_at", (model_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def update_asset(
    asset_id: str,
    name: str | None = None,
    description: str | None = None,
    asset_type: str | None = None,
) -> None:
    """
    Update asset details. Only provided fields will be updated.

    Args:
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

    conn = await db.get()
    await conn.execute(query, params)
    await conn.commit()

    logger.info(f"Updated asset {asset_id}")


async def delete_threat(threat_id: str) -> None:
    """
    Delete a threat and its associated data.

    Args:
        threat_id: ID of threat to delete
    """
    conn = await db.get()

    # Delete threat (CASCADE will handle related records)
    await conn.execute("DELETE FROM threats WHERE id = ?", (threat_id,))
    await conn.commit()

    logger.info(f"Deleted threat {threat_id}")


async def get_asset(asset_id: str) -> dict[str, Any] | None:
    """Get an asset by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM assets WHERE id = ?", (asset_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_asset(asset_id: str) -> None:
    """Delete an asset by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    await conn.commit()
    logger.info(f"Deleted asset {asset_id}")


async def delete_threat_model(model_id: str) -> None:
    """
    Delete a threat model and all associated data.

    Args:
        model_id: ID of threat model to delete
    """
    conn = await db.get()

    # Delete model (CASCADE will handle all related records)
    await conn.execute("DELETE FROM threat_models WHERE id = ?", (model_id,))
    await conn.commit()

    logger.info(f"Deleted threat model {model_id}")


async def find_threat_models_for_prune(
    older_than_days: int | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Find threat models matching prune criteria without deleting them.

    Args:
        older_than_days: Include models created more than N days ago.
        status: Include only models with this status (pending/completed/failed).

    Returns:
        List of matching model dicts.
    """
    conditions = []
    params: list[Any] = []

    if older_than_days is not None:
        conditions.append("created_at < datetime('now', ?)")
        params.append(f"-{older_than_days} days")

    if status is not None:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT * FROM threat_models {where} ORDER BY created_at"

    conn = await db.get()
    async with conn.execute(query, params) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_threat_models_batch(model_ids: list[str]) -> int:
    """Delete a batch of threat models by ID list. Returns count deleted."""
    if not model_ids:
        return 0

    placeholders = ",".join("?" * len(model_ids))
    conn = await db.get()
    cursor = await conn.execute(
        f"DELETE FROM threat_models WHERE id IN ({placeholders})", model_ids
    )
    await conn.commit()
    deleted = cursor.rowcount
    logger.info(f"Batch deleted {deleted} threat model(s)")
    return deleted


# Threat Sources CRUD


async def create_threat_source(
    model_id: str,
    category: str,
    description: str,
    example: str,
) -> str:
    """Create a new threat source (threat actor)."""
    source_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO threat_sources (id, model_id, category, description, example, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (source_id, model_id, category, description, example, now),
    )
    await conn.commit()

    return source_id


async def list_threat_sources(model_id: str) -> list[dict[str, Any]]:
    """List all threat sources for a model."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM threat_sources WHERE model_id = ? ORDER BY created_at", (model_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_threat_source(source_id: str) -> dict[str, Any] | None:
    """Get a threat source by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM threat_sources WHERE id = ?", (source_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_threat_source(source_id: str) -> None:
    """Delete a threat source by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM threat_sources WHERE id = ?", (source_id,))
    await conn.commit()
    logger.info(f"Deleted threat source {source_id}")


# Flows CRUD


async def create_flow(
    model_id: str,
    flow_type: str,
    flow_description: str,
    source_entity: str,
    target_entity: str,
) -> str:
    """Create a new data flow."""
    flow_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO flows (
            id, model_id, flow_type, flow_description,
            source_entity, target_entity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (flow_id, model_id, flow_type, flow_description, source_entity, target_entity, now),
    )
    await conn.commit()

    return flow_id


async def list_flows(model_id: str) -> list[dict[str, Any]]:
    """List all data flows for a model."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM flows WHERE model_id = ? ORDER BY created_at", (model_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_flow(flow_id: str) -> dict[str, Any] | None:
    """Get a data flow by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM flows WHERE id = ?", (flow_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def update_flow(
    flow_id: str,
    flow_type: str | None = None,
    flow_description: str | None = None,
    source_entity: str | None = None,
    target_entity: str | None = None,
) -> None:
    """Update flow details. Only provided fields will be updated."""
    update_fields = []
    params = []

    if flow_type is not None:
        update_fields.append("flow_type = ?")
        params.append(flow_type)

    if flow_description is not None:
        update_fields.append("flow_description = ?")
        params.append(flow_description)

    if source_entity is not None:
        update_fields.append("source_entity = ?")
        params.append(source_entity)

    if target_entity is not None:
        update_fields.append("target_entity = ?")
        params.append(target_entity)

    if not update_fields:
        logger.warning(f"No fields provided to update for flow {flow_id}")
        return

    params.append(flow_id)
    query = f"UPDATE flows SET {', '.join(update_fields)} WHERE id = ?"

    conn = await db.get()
    await conn.execute(query, params)
    await conn.commit()
    logger.info(f"Updated flow {flow_id}")


async def delete_flow(flow_id: str) -> None:
    """Delete a data flow by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM flows WHERE id = ?", (flow_id,))
    await conn.commit()
    logger.info(f"Deleted flow {flow_id}")


# Trust Boundaries CRUD


async def create_trust_boundary(
    model_id: str,
    purpose: str,
    source_entity: str,
    target_entity: str,
) -> str:
    """Create a new trust boundary."""
    boundary_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO trust_boundaries (id, model_id, purpose, source_entity, target_entity, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (boundary_id, model_id, purpose, source_entity, target_entity, now),
    )
    await conn.commit()
    return boundary_id


async def get_trust_boundary(boundary_id: str) -> dict[str, Any] | None:
    """Get a trust boundary by ID."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM trust_boundaries WHERE id = ?", (boundary_id,)
    ) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_trust_boundaries(model_id: str) -> list[dict[str, Any]]:
    """List all trust boundaries for a model."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM trust_boundaries WHERE model_id = ? ORDER BY created_at", (model_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_trust_boundary(boundary_id: str) -> None:
    """Delete a trust boundary by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM trust_boundaries WHERE id = ?", (boundary_id,))
    await conn.commit()
    logger.info(f"Deleted trust boundary {boundary_id}")


# Attack Trees CRUD


async def create_attack_tree(threat_id: str, mermaid_source: str) -> str:
    """Create an attack tree diagram for a threat."""
    tree_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO attack_trees (id, threat_id, mermaid_source, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (tree_id, threat_id, mermaid_source, now),
    )
    await conn.commit()
    return tree_id


async def get_attack_tree(tree_id: str) -> dict[str, Any] | None:
    """Get an attack tree by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM attack_trees WHERE id = ?", (tree_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_attack_trees(threat_id: str) -> list[dict[str, Any]]:
    """List all attack trees for a threat."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM attack_trees WHERE threat_id = ? ORDER BY created_at", (threat_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_attack_tree(tree_id: str) -> None:
    """Delete an attack tree by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM attack_trees WHERE id = ?", (tree_id,))
    await conn.commit()
    logger.info(f"Deleted attack tree {tree_id}")


# Test Cases CRUD


async def create_test_case(threat_id: str, gherkin_source: str) -> str:
    """Create a test case (Gherkin/BDD) for a threat."""
    case_id = generate_id()
    now = now_iso()

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO test_cases (id, threat_id, gherkin_source, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (case_id, threat_id, gherkin_source, now),
    )
    await conn.commit()
    return case_id


async def get_test_case(case_id: str) -> dict[str, Any] | None:
    """Get a test case by ID."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM test_cases WHERE id = ?", (case_id,)) as cursor:
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_test_cases(threat_id: str) -> list[dict[str, Any]]:
    """List all test cases for a threat."""
    conn = await db.get()
    async with conn.execute(
        "SELECT * FROM test_cases WHERE threat_id = ? ORDER BY created_at", (threat_id,)
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_test_case(case_id: str) -> None:
    """Delete a test case by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM test_cases WHERE id = ?", (case_id,))
    await conn.commit()
    logger.info(f"Deleted test case {case_id}")


# Pipeline Runs CRUD


async def create_pipeline_run(
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

    conn = await db.get()
    await conn.execute(
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
    await conn.commit()

    return run_id


async def get_pipeline_stats(model_id: str) -> dict[str, Any]:
    """Get pipeline execution statistics for a model."""
    conn = await db.get()
    async with conn.execute(
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
