"""Backfill raw_documents.sequence from metadata_json.sequence."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.settings import settings
from engine.init_db import init_database
from engine.sqlite_backend import connect_database


def _has_sequence_column(db_path: Path) -> bool:
    with connect_database(db_path) as conn:
        rows = conn.execute("PRAGMA table_info(raw_documents)").fetchall()
    return any(row["name"] == "sequence" for row in rows)


def _count_total_documents(db_path: Path) -> int:
    with connect_database(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count
            FROM raw_documents
            """
        ).fetchone()
    return int(row["total_count"] or 0)


def _count_sequence_state(db_path: Path) -> tuple[int, int]:
    with connect_database(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN sequence IS NULL THEN 1 ELSE 0 END) AS missing_count
            FROM raw_documents
            """
        ).fetchone()
    return int(row["total_count"] or 0), int(row["missing_count"] or 0)


def backfill_raw_document_sequence(db_path: str | Path) -> dict[str, int | str]:
    db_path = Path(db_path)
    had_sequence_column = _has_sequence_column(db_path)
    if had_sequence_column:
        before_total, before_missing = _count_sequence_state(db_path)
    else:
        before_total = _count_total_documents(db_path)
        before_missing = before_total

    init_database(db_path)
    after_total, after_missing = _count_sequence_state(db_path)
    return {
        "db_path": str(db_path),
        "total_count": after_total,
        "column_added": int(not had_sequence_column),
        "missing_before": before_missing,
        "missing_after": after_missing,
        "backfilled_count": max(0, before_missing - after_missing),
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill raw_documents.sequence from existing metadata_json.sequence values."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.sqlite_db_path),
        help="Optional database path override. Defaults to SQLITE_DB_PATH.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    result = backfill_raw_document_sequence(args.db)
    print(
        "Sequence backfill finished. "
        f"Backfilled: {result['backfilled_count']}, "
        f"missing_before: {result['missing_before']}, "
        f"missing_after: {result['missing_after']}. "
        f"Database: {result['db_path']}"
    )
