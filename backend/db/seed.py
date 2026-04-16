"""Seed data loader for threat patterns."""

import json
import logging
from pathlib import Path
from typing import Any

from backend.db.connection import db
from backend.db.crud import create_threat, create_threat_model
from backend.db.vectors import bulk_insert_seed_vectors, get_vector_stats


logger = logging.getLogger(__name__)


SEEDS_DIR = Path(__file__).parent.parent.parent / "seeds"

# Every seed file that should be imported, in load order.
# (title, framework) — framework is metadata on the seed threat-model record.
_SEED_FILE_META: dict[str, tuple[str, str]] = {
    "stride_patterns.json":         ("STRIDE Seed Patterns",       "STRIDE"),
    "maestro_patterns.json":        ("MAESTRO Seed Patterns",      "MAESTRO"),
    "owasp_llm_top10.json":         ("OWASP LLM Top 10",           "OWASP"),
    "atlas_patterns.json":          ("MITRE ATLAS Patterns",       "ATLAS"),
    "capec_patterns.json":          ("CAPEC Attack Patterns",      "CAPEC"),
    "aws_prowler_patterns.json":    ("AWS Cloud Patterns",         "STRIDE"),
    "azure_prowler_patterns.json":  ("Azure Cloud Patterns",       "STRIDE"),
    "gcp_prowler_patterns.json":    ("GCP Cloud Patterns",         "STRIDE"),
    "attack_cloud_patterns.json":   ("ATT&CK Cloud Patterns",      "STRIDE"),
    "ai_llm_patterns.json":         ("AI/LLM Attack Patterns",     "MAESTRO"),
    "framework_patterns.json":      ("Framework Patterns",         "STRIDE"),
    "auth_provider_patterns.json":  ("Auth Provider Patterns",     "STRIDE"),
    "cloud_service_patterns.json":  ("Cloud Service Patterns",     "STRIDE"),
    "infrastructure_patterns.json": ("Infrastructure Patterns",    "STRIDE"),
    "message_broker_patterns.json": ("Message Broker Patterns",    "STRIDE"),
    "orm_patterns.json":            ("ORM Patterns",               "STRIDE"),
}


async def load_seed_file(file_path: Path) -> list[dict[str, Any]]:
    """Load a seed JSON file and return the list of pattern dicts."""
    if not file_path.exists():
        logger.warning(f"Seed file not found: {file_path}")
        return []

    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            logger.info(f"Loaded {len(data)} patterns from {file_path.name}")
            return data
    except Exception as e:
        logger.error(f"Failed to load seed file {file_path}: {e}")
        return []


async def _import_patterns_file(filename: str, title: str, framework: str) -> int:
    """
    Import all patterns from a single seed JSON file.

    Creates one seed threat-model record per file and bulk-inserts
    embedding vectors for every pattern.

    Args:
        filename: Basename of the JSON file inside SEEDS_DIR.
        title:    Human-readable title for the seed threat-model record.
        framework: Framework label stored on the threat-model record.

    Returns:
        Number of patterns successfully imported.
    """
    patterns = await load_seed_file(SEEDS_DIR / filename)
    if not patterns:
        return 0

    model_id = await create_threat_model(
        title=title,
        description=f"Curated {title} for RAG-based threat modeling",
        provider="seed",
        model="seed",
        framework=framework,
    )

    count = 0
    threat_vectors: list[dict[str, str]] = []

    for pattern in patterns:
        try:
            threat_id = await create_threat(
                model_id=model_id,
                name=pattern["name"],
                description=pattern["description"],
                target=pattern.get("target", "Generic"),
                impact=pattern.get("impact", "Medium"),
                likelihood=pattern.get("likelihood", "Medium"),
                mitigations=pattern.get("mitigations", []),
                stride_category=pattern.get("stride_category"),
                maestro_category=pattern.get("maestro_category"),
                iteration_number=0,  # Seed patterns are iteration 0
            )
            threat_vectors.append(
                {"id": threat_id, "text": f"{pattern['name']} {pattern['description']}"}
            )
            count += 1
        except Exception as e:
            logger.error(f"Failed to import pattern '{pattern.get('name')}' from {filename}: {e}")

    if threat_vectors:
        await bulk_insert_seed_vectors(threat_vectors)

    logger.info(f"Imported {count} patterns from {filename}")
    return count


def _count_expected_seeds() -> int:
    """Count total patterns across every seed JSON file in SEEDS_DIR."""
    total = 0
    for path in sorted(SEEDS_DIR.glob("*.json")):
        try:
            with path.open("r", encoding="utf-8") as f:
                total += len(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass
    return total


async def _cleanup_seed_data() -> None:
    """Remove existing seed threat models and their cascaded data."""
    conn = await db.get()
    cursor = await conn.execute(
        "SELECT COUNT(*) FROM threat_models WHERE provider = ?", ("seed",)
    )
    count = (await cursor.fetchone())[0]

    await conn.execute("DELETE FROM threat_models WHERE provider = ?", ("seed",))
    await conn.execute("DELETE FROM threat_metadata WHERE source = ?", ("seed",))
    await conn.commit()

    if count > 0:
        logger.info(f"Cleaned up {count} existing seed threat models")


async def load_all_seeds(force: bool = False) -> dict[str, int]:
    """
    Load all seed patterns from every file in _SEED_FILE_META into the database.

    Detects partial loads by comparing the actual vector count against the
    total pattern count across all seed files on disk. Re-loads automatically
    when a mismatch is found (e.g. after adding new seed files).

    Args:
        force: If True, wipe and reload even when counts match.

    Returns:
        Dict mapping filename → imported count, plus a "total" key.
    """
    logger.info("Loading seed patterns")

    expected = _count_expected_seeds()

    if not force:
        stats = await get_vector_stats()
        actual = stats.get("seed", 0)

        if actual > 0 and actual >= expected:
            logger.info(f"Seeds already loaded ({actual} vectors)")
            return {"skipped": actual}

        if actual > 0 and actual < expected:
            logger.warning(
                f"Partial seed load detected ({actual}/{expected} vectors). "
                "Cleaning up and reloading."
            )
            force = True

    if force:
        await _cleanup_seed_data()

    results: dict[str, int] = {}

    for filename, (title, framework) in _SEED_FILE_META.items():
        try:
            results[filename] = await _import_patterns_file(filename, title, framework)
        except Exception as e:
            logger.error(f"Failed to import {filename}: {e}")
            results[filename] = 0

    results["total"] = sum(v for k, v in results.items() if k != "total")

    if results["total"] < expected:
        logger.warning(
            f"Seed load incomplete: {results['total']}/{expected} patterns imported"
        )
    else:
        logger.info(f"Loaded {results['total']} total seed patterns")

    return results


async def check_seeds_status() -> dict[str, Any]:
    """
    Return a status snapshot of the seed data.

    Returns:
        Dict with loaded/partial flags, actual and expected counts,
        total vector count, and per-file existence flags.
    """
    stats = await get_vector_stats()
    actual = stats.get("seed", 0)
    expected = _count_expected_seeds()

    return {
        "loaded": actual > 0 and actual >= expected,
        "partial": actual > 0 and actual < expected,
        "seed_count": actual,
        "expected_count": expected,
        "total_vectors": stats.get("total", 0),
        "files_exist": {
            filename: (SEEDS_DIR / filename).exists()
            for filename in _SEED_FILE_META
        },
    }
