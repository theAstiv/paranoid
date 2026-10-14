"""Derive asset links for flows, trust boundaries and threats (component IDs, B1).

The text columns stay authoritative. These functions fill the nullable
`*_asset_id` columns from them using backend.pipeline.nodes.entities, so the
LLM never sets or sees a link. Everything is idempotent and fills only NULL
links unless a caller says the text changed.
"""

import logging
from typing import Any

from backend.db import crud
from backend.db.connection import db
from backend.pipeline.nodes.entities import AssetRef, resolve_asset


logger = logging.getLogger(__name__)

# (table, [(text column, link column), ...])
_LINK_TARGETS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    ("flows", (("source_entity", "source_asset_id"), ("target_entity", "target_asset_id"))),
    (
        "trust_boundaries",
        (("source_entity", "source_asset_id"), ("target_entity", "target_asset_id")),
    ),
    ("threats", (("target", "target_asset_id"),)),
)


_BACKFILL_FLAG = "component_links_backfilled"


async def _asset_refs(model_id: str) -> list[AssetRef]:
    conn = await db.get()
    async with conn.execute("SELECT id, name FROM assets WHERE model_id = ?", (model_id,)) as cur:
        return [(row["id"], row["name"]) for row in await cur.fetchall()]


async def link_model_components(model_id: str) -> dict[str, int]:
    """Fill missing asset links for every flow, boundary and threat of a model.

    Returns {"linked": n, "unresolved": n} for the endpoints it looked at. Rows
    that already have a link are left alone, so an asset rename keeps its links.
    """
    stats = {"linked": 0, "unresolved": 0}
    assets = await _asset_refs(model_id)
    if not assets:
        return stats

    conn = await db.get()
    for table, columns in _LINK_TARGETS:
        select = ", ".join(["id", *(c for pair in columns for c in pair)])
        async with conn.execute(
            f"SELECT {select} FROM {table} WHERE model_id = ?", (model_id,)
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        for row in rows:
            for text_col, link_col in columns:
                if row[link_col] is not None:
                    continue
                asset_id = resolve_asset(row[text_col] or "", assets)
                if asset_id is None:
                    stats["unresolved"] += 1
                    continue
                await conn.execute(
                    f"UPDATE {table} SET {link_col} = ? WHERE id = ?", (asset_id, row["id"])
                )
                stats["linked"] += 1
    await conn.commit()
    return stats


async def try_link_model_components(model_id: str) -> None:
    """link_model_components for write paths: links are derived data, so a failure
    here is logged and must never fail the save that triggered it."""
    try:
        await link_model_components(model_id)
    except Exception:
        logger.warning(
            "Failed to link components for model %s (non-fatal)", model_id, exc_info=True
        )


async def _relink_row(
    table: str, row_id: str, columns: dict[str, str], row_text: dict[str, Any]
) -> None:
    """Re-resolve the given (link column -> text column) pairs, overwriting old links."""
    try:
        conn = await db.get()
        async with conn.execute(f"SELECT model_id FROM {table} WHERE id = ?", (row_id,)) as cur:
            found = await cur.fetchone()
        if found is None:
            return
        assets = await _asset_refs(found["model_id"])
        for link_col, text_col in columns.items():
            asset_id = resolve_asset(row_text.get(text_col) or "", assets)
            await conn.execute(
                f"UPDATE {table} SET {link_col} = ? WHERE id = ?", (asset_id, row_id)
            )
        await conn.commit()
    except Exception:
        logger.warning("Failed to relink %s %s (non-fatal)", table, row_id, exc_info=True)


async def relink_flow(
    flow_id: str, *, source: str | None = None, target: str | None = None
) -> None:
    """Re-resolve the sides of a flow whose entity text was just edited."""
    columns: dict[str, str] = {}
    text: dict[str, Any] = {}
    if source is not None:
        columns["source_asset_id"], text["source_entity"] = "source_entity", source
    if target is not None:
        columns["target_asset_id"], text["target_entity"] = "target_entity", target
    if columns:
        await _relink_row("flows", flow_id, columns, text)


async def relink_boundary(
    boundary_id: str, *, source: str | None = None, target: str | None = None
) -> None:
    """Re-resolve the sides of a trust boundary whose entity text was just edited."""
    columns: dict[str, str] = {}
    text: dict[str, Any] = {}
    if source is not None:
        columns["source_asset_id"], text["source_entity"] = "source_entity", source
    if target is not None:
        columns["target_asset_id"], text["target_entity"] = "target_entity", target
    if columns:
        await _relink_row("trust_boundaries", boundary_id, columns, text)


async def relink_threat(threat_id: str, target: str) -> None:
    """Re-resolve a threat's target after its text was edited."""
    await _relink_row("threats", threat_id, {"target_asset_id": "target"}, {"target": target})


async def backfill_component_links() -> None:
    """Link models saved before migration 0013, once. Never raises.

    Rows written since then are linked on save, so this only has to run on the
    first startup after the upgrade; a config flag records that it did. A failure
    leaves the flag unset so the next startup retries.
    """
    try:
        if await crud.get_config_value(_BACKFILL_FLAG):
            return
        conn = await db.get()
        async with conn.execute("SELECT DISTINCT model_id FROM assets") as cur:
            model_ids = [row["model_id"] for row in await cur.fetchall()]
        linked = 0
        for model_id in model_ids:
            linked += (await link_model_components(model_id))["linked"]
        await crud.set_config_value(_BACKFILL_FLAG, "1", encrypted=False)
        logger.info(
            "Component link backfill: %d link(s) added across %d model(s)", linked, len(model_ids)
        )
    except Exception:
        logger.warning("Component link backfill failed (non-fatal)", exc_info=True)
