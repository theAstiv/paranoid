"""Vector operations using sqlite-vec and fastembed for embeddings."""

import hashlib
import logging
import struct
from typing import Any

import aiosqlite

from backend.config import settings


logger = logging.getLogger(__name__)

# Global embedding model instance (lazy loaded)
_embedding_model: Any = None


def get_embedding_model() -> Any:
    """Get or create the embedding model instance.

    Imports fastembed lazily so the module can be imported without
    numpy/ONNX being installed (e.g. in PyInstaller CLI builds).
    """
    global _embedding_model
    if _embedding_model is None:
        from fastembed import TextEmbedding

        logger.info(f"Loading embedding model: {settings.embedding_model}")
        _embedding_model = TextEmbedding(model_name=settings.embedding_model)
        logger.info("Embedding model loaded successfully")
    return _embedding_model


def embed_text(text: str) -> list[float]:
    """
    Generate embedding for text using fastembed.

    Args:
        text: Text to embed

    Returns:
        Embedding vector as list of floats
    """
    model = get_embedding_model()
    # fastembed returns a generator of numpy arrays
    embeddings = list(model.embed([text]))
    if embeddings:
        return embeddings[0].tolist()
    raise ValueError(f"Failed to generate embedding for text: {text[:50]}...")


def serialize_vector(vector: list[float]) -> bytes:
    """
    Serialize a vector to bytes for sqlite-vec storage.

    Args:
        vector: List of float values

    Returns:
        Serialized bytes in little-endian float32 format
    """
    return struct.pack(f"{len(vector)}f", *vector)


def deserialize_vector(blob: bytes) -> list[float]:
    """
    Deserialize a vector from bytes.

    Args:
        blob: Serialized vector bytes

    Returns:
        List of float values
    """
    num_floats = len(blob) // 4
    return list(struct.unpack(f"{num_floats}f", blob))


def compute_text_hash(text: str) -> str:
    """
    Compute SHA-256 hash of text for deduplication.

    Args:
        text: Text to hash

    Returns:
        Hex string of hash
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def init_vector_table(db_path: str) -> None:
    """
    Initialize sqlite-vec virtual table for threat embeddings.

    Args:
        db_path: Path to SQLite database
    """
    logger.info("Initializing vector table")

    async with aiosqlite.connect(db_path) as db:
        # Load sqlite-vec extension
        await db.enable_load_extension(True)
        try:
            # Try loading from common locations
            await db.load_extension("vec0")
        except Exception as e:
            logger.warning(f"Could not load vec0 extension: {e}")
            try:
                await db.load_extension("sqlite-vec")
            except Exception as e2:
                logger.error(f"Could not load sqlite-vec extension: {e2}")
                raise

        # Create virtual table for 384-dimensional vectors (BAAI/bge-small-en-v1.5)
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS threat_vectors
            USING vec0(
                embedding float[384]
            );
        """)

        await db.commit()
        logger.info("Vector table initialized successfully")


async def upsert_threat_vector(
    db_path: str,
    threat_id: str,
    text: str,
    source: str = "llm",
) -> str:
    """
    Insert or update a threat vector.

    Args:
        db_path: Path to SQLite database
        threat_id: ID of the threat
        text: Text to embed (threat description)
        source: Source of the threat (llm, rule_engine, seed)

    Returns:
        ID of the vector record (threat_metadata.id)
    """
    # Generate embedding
    vector = embed_text(text)
    vector_blob = serialize_vector(vector)

    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # Check if vector already exists for this threat
        async with db.execute(
            "SELECT id FROM threat_metadata WHERE threat_id = ?", (threat_id,)
        ) as cursor:
            existing = await cursor.fetchone()

        if existing:
            # Update existing vector
            metadata_id = existing[0]
            await db.execute(
                """
                UPDATE threat_vectors
                SET embedding = ?
                WHERE rowid = (
                    SELECT rowid FROM threat_metadata WHERE id = ?
                )
                """,
                (vector_blob, metadata_id),
            )
            logger.debug(f"Updated vector for threat {threat_id}")
        else:
            # Insert new vector and metadata
            from backend.db.crud import generate_id, now_iso

            metadata_id = generate_id()
            now = now_iso()

            # Insert into threat_metadata
            await db.execute(
                """
                INSERT INTO threat_metadata (
                    id, threat_id, source, embedding_model, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (metadata_id, threat_id, source, settings.embedding_model, now),
            )

            # Insert into threat_vectors
            await db.execute(
                "INSERT INTO threat_vectors (rowid, embedding) VALUES (?, ?)",
                (hash(metadata_id) % (2**63), vector_blob),
            )
            logger.debug(f"Inserted vector for threat {threat_id}")

        await db.commit()
        return metadata_id


async def search_similar_threats(
    db_path: str,
    query_text: str,
    limit: int = 10,
    threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Search for similar threats using vector similarity.

    Args:
        db_path: Path to SQLite database
        query_text: Query text to find similar threats
        limit: Maximum number of results
        threshold: Similarity threshold (0-1, cosine similarity)

    Returns:
        List of similar threats with scores
    """
    # Generate query embedding
    query_vector = embed_text(query_text)
    query_blob = serialize_vector(query_vector)

    async with aiosqlite.connect(db_path) as db:
        await db.enable_load_extension(True)
        try:
            await db.load_extension("vec0")
        except Exception:
            try:
                await db.load_extension("sqlite-vec")
            except Exception as e:
                logger.error(f"Could not load vector extension for search: {e}")
                return []

        db.row_factory = aiosqlite.Row

        # Query for similar vectors using cosine distance
        query = """
            SELECT
                tm.threat_id,
                tm.source,
                t.name,
                t.description,
                t.stride_category,
                1 - vec_distance_cosine(tv.embedding, ?) as similarity
            FROM threat_vectors tv
            JOIN threat_metadata tm ON tv.rowid = (
                SELECT rowid FROM threat_metadata WHERE id = tm.id
            )
            JOIN threats t ON t.id = tm.threat_id
            WHERE similarity >= ?
            ORDER BY similarity DESC
            LIMIT ?
        """

        async with db.execute(query, (query_blob, threshold, limit)) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append(
                    {
                        "threat_id": row["threat_id"],
                        "source": row["source"],
                        "name": row["name"],
                        "description": row["description"],
                        "stride_category": row["stride_category"],
                        "similarity": row["similarity"],
                    }
                )
            return results


async def bulk_insert_seed_vectors(
    db_path: str,
    threats: list[dict[str, Any]],
) -> int:
    """
    Bulk insert seed threat vectors.

    Args:
        db_path: Path to SQLite database
        threats: List of threat dicts with 'text' and 'metadata' keys

    Returns:
        Number of vectors inserted
    """
    logger.info(f"Bulk inserting {len(threats)} seed vectors")

    count = 0
    for threat in threats:
        try:
            await upsert_threat_vector(
                db_path=db_path,
                threat_id=threat["id"],
                text=threat["text"],
                source="seed",
            )
            count += 1
        except Exception as e:
            logger.error(f"Failed to insert seed vector for {threat.get('id')}: {e}")

    logger.info(f"Inserted {count}/{len(threats)} seed vectors")
    return count


async def get_vector_stats(db_path: str) -> dict[str, Any]:
    """
    Get statistics about stored vectors.

    Args:
        db_path: Path to SQLite database

    Returns:
        Dictionary with vector counts by source
    """
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("""
            SELECT
                source,
                COUNT(*) as count
            FROM threat_metadata
            GROUP BY source
        """) as cursor:
            rows = await cursor.fetchall()
            stats = {row[0]: row[1] for row in rows}

        async with db.execute("SELECT COUNT(*) FROM threat_metadata") as cursor:
            total = await cursor.fetchone()
            stats["total"] = total[0] if total else 0

        return stats
