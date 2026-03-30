"""Seed data loader for threat patterns."""

import json
import logging
from pathlib import Path
from typing import Any

import aiosqlite

from backend.db.crud import create_threat
from backend.db.vectors import bulk_insert_seed_vectors, get_vector_stats


logger = logging.getLogger(__name__)


SEEDS_DIR = Path(__file__).parent.parent.parent / "seeds"


async def load_seed_file(file_path: Path) -> list[dict[str, Any]]:
    """
    Load a seed JSON file.

    Args:
        file_path: Path to JSON file

    Returns:
        List of threat pattern dictionaries
    """
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


async def import_stride_patterns(db_path: str) -> int:
    """
    Import STRIDE threat patterns from seeds/stride_patterns.json.

    Args:
        db_path: Path to SQLite database

    Returns:
        Number of patterns imported
    """
    patterns = await load_seed_file(SEEDS_DIR / "stride_patterns.json")
    if not patterns:
        return 0

    # Create a seed threat model to associate patterns with
    from backend.db.crud import create_threat_model

    model_id = await create_threat_model(
        db_path=db_path,
        title="STRIDE Seed Patterns",
        description="Curated STRIDE threat patterns for RAG",
        provider="seed",
        model="seed",
        framework="STRIDE",
    )

    count = 0
    threat_vectors = []

    for pattern in patterns:
        try:
            threat_id = await create_threat(
                db_path=db_path,
                model_id=model_id,
                name=pattern["name"],
                description=pattern["description"],
                target=pattern.get("target", "Generic"),
                impact=pattern.get("impact", "Medium"),
                likelihood=pattern.get("likelihood", "Medium"),
                mitigations=pattern.get("mitigations", []),
                stride_category=pattern.get("stride_category"),
                iteration_number=0,  # Seed patterns are iteration 0
            )

            # Prepare for vector insertion
            threat_vectors.append(
                {
                    "id": threat_id,
                    "text": f"{pattern['name']} {pattern['description']}",
                }
            )

            count += 1
        except Exception as e:
            logger.error(f"Failed to import STRIDE pattern {pattern.get('name')}: {e}")

    # Bulk insert vectors
    if threat_vectors:
        await bulk_insert_seed_vectors(db_path, threat_vectors)

    logger.info(f"Imported {count} STRIDE seed patterns")
    return count


async def import_maestro_patterns(db_path: str) -> int:
    """
    Import MAESTRO threat patterns from seeds/maestro_patterns.json.

    Args:
        db_path: Path to SQLite database

    Returns:
        Number of patterns imported
    """
    patterns = await load_seed_file(SEEDS_DIR / "maestro_patterns.json")
    if not patterns:
        return 0

    from backend.db.crud import create_threat_model

    model_id = await create_threat_model(
        db_path=db_path,
        title="MAESTRO Seed Patterns",
        description="Curated MAESTRO (ML/AI) threat patterns for RAG",
        provider="seed",
        model="seed",
        framework="MAESTRO",
    )

    count = 0
    threat_vectors = []

    for pattern in patterns:
        try:
            threat_id = await create_threat(
                db_path=db_path,
                model_id=model_id,
                name=pattern["name"],
                description=pattern["description"],
                target=pattern.get("target", "AI/ML System"),
                impact=pattern.get("impact", "Medium"),
                likelihood=pattern.get("likelihood", "Medium"),
                mitigations=pattern.get("mitigations", []),
                maestro_category=pattern.get("maestro_category"),
                iteration_number=0,
            )

            threat_vectors.append(
                {
                    "id": threat_id,
                    "text": f"{pattern['name']} {pattern['description']}",
                }
            )

            count += 1
        except Exception as e:
            logger.error(f"Failed to import MAESTRO pattern {pattern.get('name')}: {e}")

    if threat_vectors:
        await bulk_insert_seed_vectors(db_path, threat_vectors)

    logger.info(f"Imported {count} MAESTRO seed patterns")
    return count


async def import_owasp_patterns(db_path: str) -> int:
    """
    Import OWASP LLM Top 10 patterns from seeds/owasp_llm_top10.json.

    Args:
        db_path: Path to SQLite database

    Returns:
        Number of patterns imported
    """
    patterns = await load_seed_file(SEEDS_DIR / "owasp_llm_top10.json")
    if not patterns:
        return 0

    from backend.db.crud import create_threat_model

    model_id = await create_threat_model(
        db_path=db_path,
        title="OWASP LLM Top 10",
        description="OWASP Top 10 for LLM Applications",
        provider="seed",
        model="seed",
        framework="OWASP",
    )

    count = 0
    threat_vectors = []

    for pattern in patterns:
        try:
            threat_id = await create_threat(
                db_path=db_path,
                model_id=model_id,
                name=pattern["name"],
                description=pattern["description"],
                target=pattern.get("target", "LLM Application"),
                impact=pattern.get("impact", "High"),
                likelihood=pattern.get("likelihood", "Medium"),
                mitigations=pattern.get("mitigations", []),
                stride_category=pattern.get("stride_category"),
                maestro_category=pattern.get("maestro_category"),
                iteration_number=0,
            )

            threat_vectors.append(
                {
                    "id": threat_id,
                    "text": f"{pattern['name']} {pattern['description']}",
                }
            )

            count += 1
        except Exception as e:
            logger.error(f"Failed to import OWASP pattern {pattern.get('name')}: {e}")

    if threat_vectors:
        await bulk_insert_seed_vectors(db_path, threat_vectors)

    logger.info(f"Imported {count} OWASP LLM patterns")
    return count


def _count_expected_seeds() -> int:
    """Count total patterns across all seed files."""
    total = 0
    for filename in ("stride_patterns.json", "maestro_patterns.json", "owasp_llm_top10.json"):
        path = SEEDS_DIR / filename
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    total += len(json.load(f))
            except (json.JSONDecodeError, OSError):
                pass
    return total


async def _cleanup_seed_data(db_path: str) -> None:
    """Remove existing seed threat models and their cascaded data."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")
        cursor = await db.execute(
            "SELECT COUNT(*) FROM threat_models WHERE provider = ?", ("seed",)
        )
        count = (await cursor.fetchone())[0]

        await db.execute("DELETE FROM threat_models WHERE provider = ?", ("seed",))

        # Clean orphaned seed vectors from threat_metadata
        await db.execute("DELETE FROM threat_metadata WHERE source = ?", ("seed",))
        await db.commit()

    if count > 0:
        logger.info(f"Cleaned up {count} existing seed threat models")


async def load_all_seeds(db_path: str, force: bool = False) -> dict[str, int]:
    """
    Load all seed patterns into the database.

    Detects partial loads by comparing actual seed count against expected
    count from seed files. If counts don't match, cleans up and reloads.

    Args:
        db_path: Path to SQLite database
        force: If True, reload even if seeds already exist

    Returns:
        Dictionary with counts per seed type
    """
    logger.info("Loading seed patterns")

    expected = _count_expected_seeds()

    # Check if seeds already loaded (and complete)
    if not force:
        stats = await get_vector_stats(db_path)
        actual = stats.get("seed", 0)

        if actual > 0 and actual >= expected:
            logger.info(f"Seeds already loaded ({actual} vectors)")
            return {"skipped": actual}

        if actual > 0 and actual < expected:
            logger.warning(
                f"Partial seed load detected ({actual}/{expected} vectors). "
                "Cleaning up and reloading."
            )
            force = True  # Trigger cleanup and reload

    # Clean up existing seed data before reimporting
    if force:
        await _cleanup_seed_data(db_path)

    results = {}

    try:
        results["stride"] = await import_stride_patterns(db_path)
    except Exception as e:
        logger.error(f"Failed to import STRIDE patterns: {e}")
        results["stride"] = 0

    try:
        results["maestro"] = await import_maestro_patterns(db_path)
    except Exception as e:
        logger.error(f"Failed to import MAESTRO patterns: {e}")
        results["maestro"] = 0

    try:
        results["owasp"] = await import_owasp_patterns(db_path)
    except Exception as e:
        logger.error(f"Failed to import OWASP patterns: {e}")
        results["owasp"] = 0

    results["total"] = sum(results.values())

    if results["total"] < expected:
        logger.warning(f"Seed load incomplete: {results['total']}/{expected} patterns imported")
    else:
        logger.info(f"Loaded {results['total']} total seed patterns")

    return results


async def check_seeds_status(db_path: str) -> dict[str, Any]:
    """
    Check the status of seed data.

    Args:
        db_path: Path to SQLite database

    Returns:
        Dictionary with seed status information
    """
    stats = await get_vector_stats(db_path)
    actual = stats.get("seed", 0)
    expected = _count_expected_seeds()

    stride_file = SEEDS_DIR / "stride_patterns.json"
    maestro_file = SEEDS_DIR / "maestro_patterns.json"
    owasp_file = SEEDS_DIR / "owasp_llm_top10.json"

    return {
        "loaded": actual > 0 and actual >= expected,
        "partial": actual > 0 and actual < expected,
        "seed_count": actual,
        "expected_count": expected,
        "total_vectors": stats.get("total", 0),
        "files_exist": {
            "stride": stride_file.exists(),
            "maestro": maestro_file.exists(),
            "owasp": owasp_file.exists(),
        },
    }
