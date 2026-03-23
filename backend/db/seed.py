"""Seed data loader for threat patterns."""

import json
import logging
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.db.crud import create_threat, generate_id
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
            threat_vectors.append({
                "id": threat_id,
                "text": f"{pattern['name']} {pattern['description']}",
            })

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

            threat_vectors.append({
                "id": threat_id,
                "text": f"{pattern['name']} {pattern['description']}",
            })

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

            threat_vectors.append({
                "id": threat_id,
                "text": f"{pattern['name']} {pattern['description']}",
            })

            count += 1
        except Exception as e:
            logger.error(f"Failed to import OWASP pattern {pattern.get('name')}: {e}")

    if threat_vectors:
        await bulk_insert_seed_vectors(db_path, threat_vectors)

    logger.info(f"Imported {count} OWASP LLM patterns")
    return count


async def load_all_seeds(db_path: str, force: bool = False) -> dict[str, int]:
    """
    Load all seed patterns into the database.

    Args:
        db_path: Path to SQLite database
        force: If True, reload even if seeds already exist

    Returns:
        Dictionary with counts per seed type
    """
    logger.info("Loading seed patterns")

    # Check if seeds already loaded
    if not force:
        stats = await get_vector_stats(db_path)
        if stats.get("seed", 0) > 0:
            logger.info(f"Seeds already loaded ({stats['seed']} vectors)")
            return {"skipped": stats["seed"]}

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

    stride_file = SEEDS_DIR / "stride_patterns.json"
    maestro_file = SEEDS_DIR / "maestro_patterns.json"
    owasp_file = SEEDS_DIR / "owasp_llm_top10.json"

    return {
        "loaded": stats.get("seed", 0) > 0,
        "seed_count": stats.get("seed", 0),
        "total_vectors": stats.get("total", 0),
        "files_exist": {
            "stride": stride_file.exists(),
            "maestro": maestro_file.exists(),
            "owasp": owasp_file.exists(),
        },
    }
