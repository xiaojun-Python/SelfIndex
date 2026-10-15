"""Delete all archive/memory data for a specific source + source_type pair."""

from __future__ import annotations

import argparse
import json
from contextlib import closing, nullcontext
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

from app.core.settings import settings
from engine.vector_outbox import drain_vector_deletions

if TYPE_CHECKING:
    from engine.database import DatabaseManager, VectorManager


def collect_source_stats(
    sqlite_db: Any,
    *,
    source: str,
    source_type: str,
    conn=None,
) -> dict[str, Any]:
    connection_context = nullcontext(conn) if conn is not None else closing(sqlite_db.get_connection())
    with connection_context as conn:
        raw_documents_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM raw_documents
            WHERE source = ? AND source_type = ?
            """,
            (source, source_type),
        ).fetchone()["count"]
        raw_document_revisions_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM raw_document_revisions rr
            JOIN raw_documents rd ON rd.raw_document_id = rr.raw_document_id
            WHERE rd.source = ? AND rd.source_type = ?
            """,
            (source, source_type),
        ).fetchone()["count"]
        memory_unit_rows = conn.execute(
            """
            SELECT mu.memory_unit_id
            FROM memory_units mu
            JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
            WHERE rd.source = ? AND rd.source_type = ?
            ORDER BY mu.memory_unit_id
            """,
            (source, source_type),
        ).fetchall()

    memory_unit_ids = [row["memory_unit_id"] for row in memory_unit_rows]
    return {
        "source": source,
        "source_type": source_type,
        "raw_documents_count": int(raw_documents_count),
        "raw_document_revisions_count": int(raw_document_revisions_count),
        "memory_units_count": len(memory_unit_ids),
        "memory_unit_ids": memory_unit_ids,
    }


def purge_source_documents(
    sqlite_db: Any,
    *,
    source: str,
    source_type: str,
    vector_db: Any = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if dry_run:
        stats = collect_source_stats(sqlite_db, source=source, source_type=source_type)
        return {
            **stats,
            "deleted": False,
            "dry_run": True,
        }

    with sqlite_db.transaction() as conn:
        stats = collect_source_stats(sqlite_db, source=source, source_type=source_type, conn=conn)
        if stats["raw_documents_count"]:
            sqlite_db.queue_vector_deletions(stats["memory_unit_ids"], conn=conn)
            conn.execute(
                """
                DELETE FROM raw_documents
                WHERE source = ? AND source_type = ?
                """,
                (source, source_type),
            )

    if vector_db is not None and stats["raw_documents_count"]:
        try:
            drain_vector_deletions(sqlite_db, vector_db)
        except Exception as exc:
            raise RuntimeError(
                "Archive deletion committed, but vector cleanup is queued. "
                "Retry index recovery after checking the error."
            ) from exc

    return {
        **stats,
        "deleted": bool(stats["raw_documents_count"]),
        "dry_run": False,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete all raw documents, revisions, memory units, and vectors for a source."
    )
    parser.add_argument(
        "--source",
        type=str,
        default="ChatGPT",
        help="Source name in raw_documents.source. Defaults to ChatGPT.",
    )
    parser.add_argument(
        "--source-type",
        type=str,
        default="conversation_message",
        help="Source type in raw_documents.source_type. Defaults to conversation_message.",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.sqlite_db_path),
        help="Path to the SQLite / SQLCipher database. Defaults to SQLITE_DB_PATH.",
    )
    parser.add_argument(
        "--chroma",
        type=str,
        default=str(settings.chroma_db_path),
        help="Path to the Chroma directory. Defaults to CHROMA_DB_PATH.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only report how many rows/vectors would be removed.",
    )
    return parser


if __name__ == "__main__":
    from engine.database import DatabaseManager, VectorManager

    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(Path(args.db))
    vector_db = None if args.dry_run else VectorManager(Path(args.chroma))
    result = purge_source_documents(
        sqlite_db,
        source=args.source,
        source_type=args.source_type,
        vector_db=vector_db,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
