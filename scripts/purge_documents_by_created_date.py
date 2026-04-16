"""Delete documents, revisions, memory units, and vectors by created_at date."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.core.settings import settings


def collect_created_date_stats(
    sqlite_db: Any,
    *,
    source: str,
    source_type: str,
    created_date: str,
) -> dict[str, Any]:
    with sqlite_db.get_connection() as conn:
        raw_document_rows = conn.execute(
            """
            SELECT raw_document_id, root_document_id, external_id, created_at
            FROM raw_documents
            WHERE source = ?
              AND source_type = ?
              AND substr(COALESCE(created_at, ''), 1, 10) = ?
            ORDER BY created_at, raw_document_id
            """,
            (source, source_type, created_date),
        ).fetchall()

        raw_document_ids = [row["raw_document_id"] for row in raw_document_rows]
        if not raw_document_ids:
            return {
                "source": source,
                "source_type": source_type,
                "created_date": created_date,
                "raw_documents_count": 0,
                "raw_document_revisions_count": 0,
                "memory_units_count": 0,
                "memory_unit_ids": [],
                "raw_document_ids": [],
                "conversation_ids": [],
            }

        placeholders = ", ".join("?" for _ in raw_document_ids)
        raw_document_revisions_count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM raw_document_revisions
            WHERE raw_document_id IN ({placeholders})
            """,
            raw_document_ids,
        ).fetchone()["count"]

        memory_unit_rows = conn.execute(
            f"""
            SELECT memory_unit_id
            FROM memory_units
            WHERE raw_document_id IN ({placeholders})
            ORDER BY memory_unit_id
            """,
            raw_document_ids,
        ).fetchall()

    memory_unit_ids = [row["memory_unit_id"] for row in memory_unit_rows]
    conversation_ids = sorted(
        {
            row["root_document_id"]
            for row in raw_document_rows
            if row.get("root_document_id")
        }
    )
    return {
        "source": source,
        "source_type": source_type,
        "created_date": created_date,
        "raw_documents_count": len(raw_document_ids),
        "raw_document_revisions_count": int(raw_document_revisions_count),
        "memory_units_count": len(memory_unit_ids),
        "memory_unit_ids": memory_unit_ids,
        "raw_document_ids": raw_document_ids,
        "conversation_ids": conversation_ids,
    }


def purge_documents_by_created_date(
    sqlite_db: Any,
    *,
    source: str,
    source_type: str,
    created_date: str,
    vector_db: Any = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    stats = collect_created_date_stats(
        sqlite_db,
        source=source,
        source_type=source_type,
        created_date=created_date,
    )
    if dry_run or stats["raw_documents_count"] == 0:
        return {
            **stats,
            "deleted": False,
            "dry_run": dry_run,
        }

    if vector_db is not None and stats["memory_unit_ids"]:
        vector_db.delete_vectors(stats["memory_unit_ids"])

    with sqlite_db.transaction() as conn:
        conn.execute(
            """
            DELETE FROM raw_documents
            WHERE source = ?
              AND source_type = ?
              AND substr(COALESCE(created_at, ''), 1, 10) = ?
            """,
            (source, source_type, created_date),
        )

    return {
        **stats,
        "deleted": True,
        "dry_run": False,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Delete raw documents, revisions, memory units, and vectors by created_at date."
    )
    parser.add_argument(
        "--created-date",
        required=True,
        type=str,
        help="Date prefix in YYYY-MM-DD format, matched against raw_documents.created_at.",
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
    result = purge_documents_by_created_date(
        sqlite_db,
        source=args.source,
        source_type=args.source_type,
        created_date=args.created_date,
        vector_db=vector_db,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
