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


async def list_threat_models(
    limit: int = 50,
    framework: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List threat models with per-model threat counts, optionally filtered."""
    conditions = []
    params: list[Any] = []

    if framework is not None:
        conditions.append("tm.framework = ?")
        params.append(framework)

    if status is not None:
        conditions.append("tm.status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    conn = await db.get()
    async with conn.execute(
        f"""
        SELECT
            tm.*,
            COUNT(t.id) AS threat_count
        FROM threat_models tm
        LEFT JOIN threats t ON t.model_id = tm.id
        {where}
        GROUP BY tm.id
        ORDER BY tm.created_at DESC
        LIMIT ?
        """,
        params,
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

    if not update_fields:
        logger.warning(f"No fields provided to update for asset {asset_id}")
        return

    params.append(asset_id)

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


async def update_trust_boundary(
    boundary_id: str,
    purpose: str | None = None,
    source_entity: str | None = None,
    target_entity: str | None = None,
) -> None:
    """Update trust boundary details. Only provided fields will be updated."""
    update_fields = []
    params = []

    if purpose is not None:
        update_fields.append("purpose = ?")
        params.append(purpose)

    if source_entity is not None:
        update_fields.append("source_entity = ?")
        params.append(source_entity)

    if target_entity is not None:
        update_fields.append("target_entity = ?")
        params.append(target_entity)

    if not update_fields:
        logger.warning(f"No fields provided to update for trust boundary {boundary_id}")
        return

    params.append(boundary_id)
    query = f"UPDATE trust_boundaries SET {', '.join(update_fields)} WHERE id = ?"

    conn = await db.get()
    await conn.execute(query, params)
    await conn.commit()
    logger.info(f"Updated trust boundary {boundary_id}")


async def delete_trust_boundary(boundary_id: str) -> None:
    """Delete a trust boundary by ID."""
    conn = await db.get()
    await conn.execute("DELETE FROM trust_boundaries WHERE id = ?", (boundary_id,))
    await conn.commit()
    logger.info(f"Deleted trust boundary {boundary_id}")


async def clear_model_data(model_id: str, preserve_user_edits: bool = False) -> None:
    """Delete all pipeline-generated data for a model (threats, assets, flows, trust boundaries).

    Called before each pipeline run so that re-running a model starts from a clean slate.

    Args:
        model_id: The model whose data to clear.
        preserve_user_edits: When True, rows with user_edited=1 in assets, flows, and
            trust_boundaries are kept so that manually-corrected context survives a re-run.
    """
    conn = await db.get()
    await conn.execute("DELETE FROM threats WHERE model_id = ?", (model_id,))
    if preserve_user_edits:
        await conn.execute("DELETE FROM assets WHERE model_id = ? AND user_edited = 0", (model_id,))
        await conn.execute("DELETE FROM flows WHERE model_id = ? AND user_edited = 0", (model_id,))
        await conn.execute(
            "DELETE FROM trust_boundaries WHERE model_id = ? AND user_edited = 0", (model_id,)
        )
    else:
        await conn.execute("DELETE FROM assets WHERE model_id = ?", (model_id,))
        await conn.execute("DELETE FROM flows WHERE model_id = ?", (model_id,))
        await conn.execute("DELETE FROM trust_boundaries WHERE model_id = ?", (model_id,))
    await conn.commit()
    logger.info(
        f"Cleared pipeline data for model {model_id} (preserve_user_edits={preserve_user_edits})"
    )


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


# Config KV store
#
# Keys ending in "_api_key" or "_pat" are always encrypted at rest using the
# Fernet key from backend.security.source_key. Other keys are stored as UTF-8
# plaintext bytes so non-sensitive runtime overrides don't pay the crypto tax.


def _is_secret_key(key: str) -> bool:
    return key.endswith("_api_key") or key.endswith("_pat")


async def get_config_value(key: str) -> str | None:
    """Fetch a config value, decrypting if stored encrypted.

    Raises:
        PATDecryptionError: ciphertext present but cannot be decrypted under
            the active Fernet key (wrong CONFIG_SECRET, key-source switch,
            or corrupted value).
    """
    from backend.security.source_key import decrypt_str

    conn = await db.get()
    async with conn.execute("SELECT value, encrypted FROM config WHERE key = ?", (key,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    # aiosqlite returns BLOB columns as bytes; we rely on that invariant here.
    raw, encrypted = row[0], row[1]
    if encrypted:
        return decrypt_str(raw)
    return raw.decode("utf-8")


async def set_config_value(key: str, value: str, *, encrypted: bool) -> None:
    """Upsert a config value. Forces encrypted=True for keys ending ``_api_key``/``_pat``."""
    from backend.security.source_key import encrypt_str

    if _is_secret_key(key) and not encrypted:
        # Defensive — callers always pass encrypted=True for secret keys.
        # If this fires a caller is wrong; log at error so it's visible.
        logger.error(f"set_config_value({key}) called with encrypted=False; forcing encryption")
        encrypted = True

    stored: bytes = encrypt_str(value) if encrypted else value.encode("utf-8")
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO config (key, value, encrypted, updated_at)
             VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            encrypted = excluded.encrypted,
            updated_at = excluded.updated_at
        """,
        (key, stored, 1 if encrypted else 0, now),
    )
    await conn.commit()


async def delete_config_value(key: str) -> None:
    """Delete a config row. Idempotent — absent key is a no-op."""
    conn = await db.get()
    await conn.execute("DELETE FROM config WHERE key = ?", (key,))
    await conn.commit()


# Code sources CRUD
#
# Clone path is NOT stored — it is derived from the source id at read time
# via backend.sources.paths.clone_dir_for. The row stores just the inputs
# (git_url, optional ref, optional encrypted PAT) and the last run's
# status/diagnostics.


# Routes store diagnostic stderr; keep it bounded so /api/sources list
# responses don't balloon. Writers (clone manager) should pre-truncate
# before calling into CRUD, but we defend in depth here too.
_LAST_INDEX_ERROR_MAX_CHARS = 4096


def _truncate_error(text: str | None) -> str | None:
    if text is None:
        return None
    if len(text) <= _LAST_INDEX_ERROR_MAX_CHARS:
        return text
    return text[:_LAST_INDEX_ERROR_MAX_CHARS] + "\n... [truncated]"


def _row_to_code_source(row: Any) -> dict[str, Any]:
    """Row dict with ``has_pat`` derived and ``pat_ciphertext`` stripped.

    Kept in the CRUD layer so ciphertext never escapes this module — the
    route layer receives a clean dict it can feed straight into the
    ``CodeSource`` Pydantic model.
    """
    d = dict(row)
    d["has_pat"] = d.get("pat_ciphertext") is not None
    d.pop("pat_ciphertext", None)
    # Normalise the sentinel empty-string ref back to None for the public API.
    if d.get("ref") == "":
        d["ref"] = None
    return d


async def create_code_source(
    *,
    name: str,
    git_url: str,
    ref: str | None,
    pat: str | None,
) -> str:
    """Insert a new code_sources row. Returns the new UUID4 hex id.

    When ``pat`` is non-None it is encrypted under the active Fernet key
    and the deployment's key source is recorded for future switch
    detection. Callers should pass an already-stripped value.
    """
    from backend.security.source_key import (
        assert_pat_key_source_matches,
        encrypt_pat,
        record_pat_key_source,
    )

    source_id = uuid.uuid4().hex
    now = now_iso()
    pat_ciphertext: bytes | None = None
    if pat:
        await assert_pat_key_source_matches()
        pat_ciphertext = encrypt_pat(pat)
        await record_pat_key_source()

    # Normalise None → "" so the UNIQUE (git_url, ref) constraint treats
    # "same URL, no ref" as a genuine duplicate. SQLite treats NULLs as
    # distinct, so NULL ≠ NULL in a UNIQUE index.
    stored_ref = ref if ref is not None else ""

    conn = await db.get()
    await conn.execute(
        """
        INSERT INTO code_sources (
            id, name, git_url, ref, pat_ciphertext, pat_last_used_at,
            last_indexed_at, last_index_status, last_index_error,
            resolved_sha, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'queued', NULL, NULL, NULL, ?, ?)
        """,
        (source_id, name, git_url, stored_ref, pat_ciphertext, now, now),
    )
    await conn.commit()
    logger.info(f"Created code source {source_id} ({git_url})")
    return source_id


async def get_code_source(source_id: str) -> dict[str, Any] | None:
    """Return the public dict for a single source, or ``None`` if absent."""
    conn = await db.get()
    async with conn.execute("SELECT * FROM code_sources WHERE id = ?", (source_id,)) as cursor:
        row = await cursor.fetchone()
    return _row_to_code_source(row) if row else None


async def list_code_sources() -> list[dict[str, Any]]:
    conn = await db.get()
    async with conn.execute("SELECT * FROM code_sources ORDER BY created_at DESC") as cursor:
        rows = await cursor.fetchall()
    return [_row_to_code_source(r) for r in rows]


async def get_code_source_pat(source_id: str) -> str | None:
    """Return the decrypted PAT or ``None`` when no PAT is stored.

    Raises ``PATDecryptionError`` on ciphertext that cannot be decrypted
    (rotated key, corrupt row). Raises ``KeySourceChangedError`` when the
    active Fernet source doesn't match the one the PAT was stored under —
    routes should map that to 409 with the actionable message.
    """
    from backend.security.source_key import assert_pat_key_source_matches, decrypt_pat

    conn = await db.get()
    async with conn.execute(
        "SELECT pat_ciphertext FROM code_sources WHERE id = ?", (source_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    await assert_pat_key_source_matches()
    return decrypt_pat(bytes(row[0]))


async def update_code_source_status(
    source_id: str,
    *,
    status: str,
    error: str | None = None,
    resolved_sha: str | None = None,
    indexed_at: str | None = None,
) -> None:
    """Record a clone/index lifecycle transition. Fields default to no change."""
    now = now_iso()
    fields = ["last_index_status = ?", "updated_at = ?"]
    params: list[Any] = [status, now]

    # Route the error through the truncator so writers can paste raw stderr.
    fields.append("last_index_error = ?")
    params.append(_truncate_error(error))

    if resolved_sha is not None:
        fields.append("resolved_sha = ?")
        params.append(resolved_sha)
    if indexed_at is not None:
        fields.append("last_indexed_at = ?")
        params.append(indexed_at)
    params.append(source_id)

    conn = await db.get()
    await conn.execute(
        f"UPDATE code_sources SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    await conn.commit()


async def mark_code_source_pat_used(source_id: str) -> None:
    """Bump ``pat_last_used_at`` after a successful clone using the stored PAT."""
    now = now_iso()
    conn = await db.get()
    await conn.execute(
        "UPDATE code_sources SET pat_last_used_at = ?, updated_at = ? WHERE id = ?",
        (now, now, source_id),
    )
    await conn.commit()


async def delete_code_source(source_id: str) -> bool:
    """Delete a source row. Returns True if a row existed.

    FK ``threat_models.code_source_id`` is declared ``ON DELETE SET NULL``,
    so historical threat models keep their assets/threats but lose the
    link. Rmtree of the clone dir is the route/manager's job — this
    function is DB-only.
    """
    conn = await db.get()
    async with conn.execute("DELETE FROM code_sources WHERE id = ?", (source_id,)) as cur:
        deleted = cur.rowcount
    await conn.commit()
    return bool(deleted)
