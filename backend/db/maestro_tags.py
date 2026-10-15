"""Persist MAESTRO applicability tags on assets (B2).

The tags are a pure function of an asset's name and description
(backend.pipeline.nodes.maestro_tags), so every entry point just recomputes and
writes the rows whose stored value differs. That makes each call idempotent and
lets an asset edit use the same path as a first save.
"""

import json
import logging

from backend.db import crud
from backend.db.connection import db
from backend.pipeline.nodes.maestro_tags import maestro_coverage, rules_version, tag_asset


logger = logging.getLogger(__name__)

_BACKFILL_FLAG = "maestro_tags_backfilled"


def parse_categories(raw: str | None) -> list[str] | None:
    """Stored JSON -> list of category names; None when untagged or unreadable."""
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, list) else None


async def get_model_coverage(model_id: str) -> dict:
    """MAESTRO coverage for a model, computed on read from its tags and threats."""
    conn = await db.get()
    async with conn.execute(
        "SELECT maestro_categories FROM assets WHERE model_id = ?", (model_id,)
    ) as cur:
        asset_tags = [parse_categories(row["maestro_categories"]) for row in await cur.fetchall()]
    async with conn.execute(
        "SELECT maestro_category, COUNT(*) AS n FROM threats "
        "WHERE model_id = ? AND maestro_category IS NOT NULL AND status != 'rejected' "
        "GROUP BY maestro_category",
        (model_id,),
    ) as cur:
        counts = {row["maestro_category"]: row["n"] for row in await cur.fetchall()}
    return maestro_coverage(asset_tags, counts)


async def tag_model_assets(model_id: str) -> int:
    """Recompute every asset's tags for a model; returns how many rows changed."""
    conn = await db.get()
    async with conn.execute(
        "SELECT id, name, description, maestro_categories FROM assets WHERE model_id = ?",
        (model_id,),
    ) as cur:
        rows = await cur.fetchall()
    changed = 0
    for row in rows:
        tags = json.dumps([c.value for c in tag_asset(row["name"], row["description"] or "")])
        if row["maestro_categories"] == tags:
            continue
        await conn.execute(
            "UPDATE assets SET maestro_categories = ? WHERE id = ?", (tags, row["id"])
        )
        changed += 1
    await conn.commit()
    return changed


async def try_tag_model_assets(model_id: str) -> None:
    """tag_model_assets for write paths: tags are derived data, so a failure is
    logged and must never fail the save that triggered it."""
    try:
        await tag_model_assets(model_id)
    except Exception:
        logger.warning("Failed to tag assets for model %s (non-fatal)", model_id, exc_info=True)


async def backfill_maestro_tags() -> None:
    """Tag models saved before migration 0014, once. Never raises.

    The config value records the rule-set version that was applied, so a rule
    change re-runs it on the next startup. A failure leaves the value unchanged
    so the next startup retries.
    """
    try:
        version = rules_version()
        if await crud.get_config_value(_BACKFILL_FLAG) == version:
            return
        conn = await db.get()
        async with conn.execute("SELECT DISTINCT model_id FROM assets") as cur:
            model_ids = [row["model_id"] for row in await cur.fetchall()]
        changed = 0
        for model_id in model_ids:
            changed += await tag_model_assets(model_id)
        await crud.set_config_value(_BACKFILL_FLAG, version, encrypted=False)
        logger.info(
            "MAESTRO tag backfill: %d asset(s) tagged across %d model(s)", changed, len(model_ids)
        )
    except Exception:
        logger.warning("MAESTRO tag backfill failed (non-fatal)", exc_info=True)
