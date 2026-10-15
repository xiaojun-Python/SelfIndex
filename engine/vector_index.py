"""Write embeddings only for memory units still current at Chroma write time."""

from __future__ import annotations

from typing import Any

from app.core.settings import settings
from engine.database import IndexModelError


def vector_metadata_from_row(row: dict[str, Any]) -> dict[str, str]:
    return {
        "memory_unit_id": row["memory_unit_id"],
        "raw_document_id": row["raw_document_id"],
        "title": row["title"] or "Untitled document",
        "source": row["source"],
        "source_type": row["source_type"],
        "author": row["author"] or "",
        "created_at": row["created_at"] or "",
        "summary": row["summary"] or "",
        "recall_domain": row["recall_domain"] or "default",
    }


def write_current_vectors(
    sqlite_db: Any,
    vector_db: Any,
    *,
    ids: list[str],
    documents: list[str],
    versions: list[str | None],
    embeddings: list[list[float]],
    batch_size: int = 100,
) -> list[str]:
    if not (len(ids) == len(documents) == len(versions) == len(embeddings)):
        raise ValueError("Vector write inputs must have matching lengths")
    if len(set(ids)) != len(ids):
        raise ValueError("Vector write IDs must be unique")
    if not 1 <= batch_size <= 900:
        raise ValueError("batch_size must be between 1 and 900")

    written: list[str] = []
    for start in range(0, len(ids), batch_size):
        batch_ids = ids[start : start + batch_size]
        placeholders = ", ".join("?" for _ in batch_ids)
        conn = sqlite_db.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"""
                SELECT mu.memory_unit_id, mu.content, mu.summary, mu.recall_domain,
                       mu.embedding_version, mu.is_embedded,
                       rd.raw_document_id, rd.title, rd.source, rd.source_type,
                       rd.author, rd.created_at
                FROM memory_units mu
                JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
                JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
                WHERE mu.memory_unit_id IN ({placeholders})
                  AND rr.is_current = 1 AND rd.is_active = 1
                """,
                batch_ids,
            ).fetchall()
            current = {row["memory_unit_id"]: row for row in rows}

            eligible: list[tuple[dict[str, Any], list[float]]] = []
            for index, memory_unit_id in enumerate(batch_ids):
                row = current.get(memory_unit_id)
                if row is None or row["is_embedded"]:
                    continue
                offset = start + index
                if row["content"] != documents[offset] or row["embedding_version"] != versions[offset]:
                    continue
                eligible.append((row, embeddings[offset]))

            if eligible:
                models = {row["embedding_version"] for row, _embedding in eligible}
                if models != {settings.embedding_model}:
                    raise IndexModelError(
                        f"Pending units use embedding versions {sorted(str(model) for model in models)!r}; "
                        f"configured model is {settings.embedding_model!r}. Rebuild embeddings after migration."
                    )
                if hasattr(vector_db, "ensure_model_compatible"):
                    vector_db.ensure_model_compatible(settings.embedding_model, for_write=True)
                write_ids = [row["memory_unit_id"] for row, _embedding in eligible]
                vector_db.delete_vectors(write_ids)
                vector_db.add_vectors(
                    ids=write_ids,
                    embeddings=[embedding for _row, embedding in eligible],
                    documents=[row["content"] for row, _embedding in eligible],
                    metadatas=[vector_metadata_from_row(row) for row, _embedding in eligible],
                )
                sqlite_db.mark_memory_units_as_embedded(write_ids, conn=conn)
            conn.commit()
            written.extend(row["memory_unit_id"] for row, _embedding in eligible)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return written
