"""Replay durable vector deletions after the archive transaction commits."""

from __future__ import annotations

from typing import Any


def drain_vector_deletions(
    sqlite_db: Any,
    vector_db: Any,
    *,
    batch_size: int = 100,
    max_batches: int | None = None,
) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if batch_size > 900:
        raise ValueError("batch_size must not exceed 900 SQLite parameters")

    processed = 0
    delete_requested = 0
    batches = 0
    while max_batches is None or batches < max_batches:
        conn = sqlite_db.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT memory_unit_id FROM vector_deletion_outbox ORDER BY queued_at, memory_unit_id LIMIT ?",
                (batch_size,),
            ).fetchall()
            if not rows:
                conn.commit()
                break

            ids = [row["memory_unit_id"] for row in rows]
            placeholders = ", ".join("?" for _ in ids)
            current_rows = conn.execute(
                f"""
                SELECT mu.memory_unit_id
                FROM memory_units mu
                JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
                JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
                WHERE mu.memory_unit_id IN ({placeholders})
                  AND rr.is_current = 1 AND rd.is_active = 1
                """,
                ids,
            ).fetchall()
            current_ids = {row["memory_unit_id"] for row in current_rows}
            stale_ids = [memory_unit_id for memory_unit_id in ids if memory_unit_id not in current_ids]
            if stale_ids:
                vector_db.delete_vectors(stale_ids)

            conn.executemany(
                "DELETE FROM vector_deletion_outbox WHERE memory_unit_id = ?",
                [(memory_unit_id,) for memory_unit_id in ids],
            )
            conn.commit()
            processed += len(ids)
            delete_requested += len(stale_ids)
            batches += 1
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    return {"processed": processed, "delete_requested": delete_requested}
