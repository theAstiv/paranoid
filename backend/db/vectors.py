"""Vector operations using sqlite-vec and fastembed for embeddings."""

import hashlib
import logging
import struct
from typing import Any

from backend.config import settings
from backend.db.connection import db


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


async def upsert_threat_vector(
    threat_id: str,
    text: str,
    source: str = "llm",
) -> str:
    """
    Insert or update a threat vector.

    Args:
        threat_id: ID of the threat
        text: Text to embed (threat description)
        source: Source of the threat (llm, rule_engine, seed)

    Returns:
        ID of the vector record (threat_metadata.id)
    """
    # Generate embedding
    vector = embed_text(text)
    vector_blob = serialize_vector(vector)

    conn = await db.get()

    # Check if vector already exists for this threat
    async with conn.execute(
        "SELECT id, vector_rowid FROM threat_metadata WHERE threat_id = ?", (threat_id,)
    ) as cursor:
        existing = await cursor.fetchone()

    if existing:
        # Update existing vector using the stored vector_rowid
        metadata_id = existing[0]
        vector_rowid = existing[1]
        if vector_rowid is not None:
            await conn.execute(
                "UPDATE threat_vectors SET embedding = ? WHERE rowid = ?",
                (vector_blob, vector_rowid),
            )
            logger.debug(f"Updated vector for threat {threat_id}")
        else:
            # Pre-migration row: vector_rowid was NULL before schema v1 migration.
            # The vector cannot be updated without the rowid; log so it's visible.
            logger.warning(
                f"Cannot update vector for threat {threat_id}: "
                "threat_metadata.vector_rowid is NULL (pre-migration row). "
                "Re-seed or delete and re-insert this threat to backfill."
            )
    else:
        # Insert new vector and metadata
        from backend.db.crud import generate_id, now_iso

        metadata_id = generate_id()
        now = now_iso()
        # Derive a stable integer rowid from the metadata UUID
        vector_rowid = hash(metadata_id) % (2**63)

        # Insert into threat_metadata (including the vector_rowid for future joins)
        await conn.execute(
            """
            INSERT INTO threat_metadata (
                id, threat_id, source, embedding_model, vector_rowid, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (metadata_id, threat_id, source, settings.embedding_model, vector_rowid, now),
        )

        # Insert into threat_vectors with matching rowid
        await conn.execute(
            "INSERT INTO threat_vectors (rowid, embedding) VALUES (?, ?)",
            (vector_rowid, vector_blob),
        )
        logger.debug(f"Inserted vector for threat {threat_id} (rowid={vector_rowid})")

    await conn.commit()
    return metadata_id


async def search_similar_threats(
    query_text: str,
    limit: int = 10,
    threshold: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Search for similar threats using vector similarity.

    Args:
        query_text: Query text to find similar threats
        limit: Maximum number of results
        threshold: Similarity threshold (0-1, cosine similarity)

    Returns:
        List of similar threats with scores
    """
    # Generate query embedding
    query_vector = embed_text(query_text)
    query_blob = serialize_vector(query_vector)

    conn = await db.get()

    # Query for similar vectors using cosine distance.
    # threat_metadata.vector_rowid is the stable integer key written at insert time,
    # matching the explicit rowid used when inserting into threat_vectors.
    query = """
        SELECT
            tm.threat_id,
            tm.source,
            t.name,
            t.description,
            t.stride_category,
            1 - vec_distance_cosine(tv.embedding, ?) as similarity
        FROM threat_vectors tv
        JOIN threat_metadata tm ON tv.rowid = tm.vector_rowid
        JOIN threats t ON t.id = tm.threat_id
        WHERE similarity >= ?
        ORDER BY similarity DESC
        LIMIT ?
    """

    async with conn.execute(query, (query_blob, threshold, limit)) as cursor:
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
    threats: list[dict[str, Any]],
) -> int:
    """
    Bulk insert seed threat vectors.

    Args:
        threats: List of threat dicts with 'text' and 'metadata' keys

    Returns:
        Number of vectors inserted
    """
    logger.info(f"Bulk inserting {len(threats)} seed vectors")

    count = 0
    for threat in threats:
        try:
            await upsert_threat_vector(
                threat_id=threat["id"],
                text=threat["text"],
                source="seed",
            )
            count += 1
        except Exception as e:
            logger.error(f"Failed to insert seed vector for {threat.get('id')}: {e}")

    logger.info(f"Inserted {count}/{len(threats)} seed vectors")
    return count


async def get_vector_stats() -> dict[str, Any]:
    """
    Get statistics about stored vectors.

    Returns:
        Dictionary with vector counts by source
    """
    conn = await db.get()
    async with conn.execute("""
        SELECT
            source,
            COUNT(*) as count
        FROM threat_metadata
        GROUP BY source
    """) as cursor:
        rows = await cursor.fetchall()
        stats = {row[0]: row[1] for row in rows}

    async with conn.execute("SELECT COUNT(*) FROM threat_metadata") as cursor:
        total = await cursor.fetchone()
        stats["total"] = total[0] if total else 0

    return stats
