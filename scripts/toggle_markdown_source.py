"""Disable or re-enable one Markdown source without deleting its archived documents."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.settings import settings
from engine.database import DatabaseManager, ReadOnlyDatabase, VectorManager
from engine.vector_outbox import drain_vector_deletions


def inspect_source(sqlite_db: Any, root_document_id: str) -> dict[str, int]:
    with sqlite_db.get_connection() as conn:
        documents = conn.execute(
            """
            SELECT COUNT(*) AS total, COALESCE(SUM(is_active), 0) AS active
            FROM raw_documents
            WHERE source = 'markdown' AND source_type = 'note_file' AND root_document_id = ?
            """,
            (root_document_id,),
        ).fetchone()
        units = conn.execute(
            """
            SELECT COUNT(*) AS count FROM memory_units mu
            JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
            JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
            WHERE rr.is_current = 1 AND rd.source = 'markdown'
              AND rd.source_type = 'note_file' AND rd.root_document_id = ?
            """,
            (root_document_id,),
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) AS count FROM source_write_outbox WHERE root_path = ?",
            (root_document_id,),
        ).fetchone()["count"]
    return {
        "documents": int(documents["total"]),
        "active_documents": int(documents["active"]),
        "current_units": int(units["count"]),
        "pending_source_writes": int(pending),
    }


def set_source_enabled(
    sqlite_db: DatabaseManager,
    root_document_id: str,
    *,
    enabled: bool,
    expected_documents: int,
    vector_db: Any = None,
) -> dict[str, int | bool]:
    if expected_documents < 1:
        raise ValueError("Expected document count must be positive.")
    with sqlite_db.transaction(immediate=True) as conn:
        rows = conn.execute(
            """
            SELECT rd.raw_document_id, rd.is_active, rr.change_type
            FROM raw_documents rd
            LEFT JOIN raw_document_revisions rr ON rr.revision_id = rd.latest_revision_id
            WHERE rd.source = 'markdown' AND rd.source_type = 'note_file'
              AND rd.root_document_id = ?
            ORDER BY rd.raw_document_id
            """,
            (root_document_id,),
        ).fetchall()
        if len(rows) != expected_documents:
            raise RuntimeError(f"Expected {expected_documents} documents; found {len(rows)}. No changes made.")
        if conn.execute(
            "SELECT 1 FROM source_write_outbox WHERE root_path = ? LIMIT 1",
            (root_document_id,),
        ).fetchone():
            raise RuntimeError("Source has pending App writes; resolve them before changing its state.")
        if enabled and any(row["change_type"] == "deleted" for row in rows):
            raise RuntimeError("A document has a deletion revision; re-enable requires manual review.")

        changing = [row["raw_document_id"] for row in rows if bool(row["is_active"]) != enabled]
        current_unit_ids: list[str] = []
        if changing:
            placeholders = ", ".join("?" for _ in changing)
            current_unit_ids = [row["memory_unit_id"] for row in conn.execute(
                f"""
                SELECT mu.memory_unit_id FROM memory_units mu
                JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
                WHERE rr.is_current = 1 AND mu.raw_document_id IN ({placeholders})
                """,
                changing,
            ).fetchall()]
            conn.executemany(
                "UPDATE raw_documents SET is_active = ?, edit_version = edit_version + 1 WHERE raw_document_id = ?",
                [(int(enabled), raw_id) for raw_id in changing],
            )
            conn.executemany(
                "UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?",
                [(unit_id,) for unit_id in current_unit_ids],
            )
            if not enabled:
                sqlite_db.queue_vector_deletions(current_unit_ids, conn=conn)

    if not enabled and vector_db is not None:
        drain_vector_deletions(sqlite_db, vector_db)
    return {
        "documents": len(rows),
        "changed_documents": len(changing),
        "current_units": len(current_unit_ids),
        "enabled": enabled,
        "pending_vector_deletions": sqlite_db.count_pending_vector_deletions(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="Exact root_document_id stored in the archive.")
    parser.add_argument("--expected-documents", type=int, required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--disable", action="store_true")
    actions.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    if not args.disable and not args.enable:
        result = inspect_source(ReadOnlyDatabase(settings.sqlite_db_path), args.root)
        if result["documents"] != args.expected_documents:
            parser.error(
                f"Expected {args.expected_documents} documents; found {result['documents']}."
            )
    else:
        sqlite_db = DatabaseManager(settings.sqlite_db_path)
        vector_db = VectorManager(settings.chroma_db_path, create_if_missing=False) if args.disable else None
        result = set_source_enabled(
            sqlite_db, args.root, enabled=args.enable,
            expected_documents=args.expected_documents, vector_db=vector_db,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
