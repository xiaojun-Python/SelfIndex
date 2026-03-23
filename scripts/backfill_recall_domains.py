"""Backfill `memory_units.recall_domain` using configured protected terms."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager


def _matches_protected_terms(content: str, protected_terms: list[str]) -> bool:
    lowered = (content or "").lower()
    return any(term.lower() in lowered for term in protected_terms if term.strip())


def backfill_recall_domains(
    sqlite_db: DatabaseManager,
    *,
    protected_terms: list[str],
    protected_domain: str = "sensitive",
    default_domain: str = "default",
    dry_run: bool = False,
) -> dict[str, int]:
    protected_terms = [term.strip() for term in protected_terms if term.strip()]

    with sqlite_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT memory_unit_id, content, recall_domain FROM memory_units"
        ).fetchall()

        updates: list[tuple[str, str]] = []
        protected_count = 0
        default_count = 0
        unchanged_count = 0

        for row in rows:
            target_domain = (
                protected_domain
                if _matches_protected_terms(row["content"], protected_terms)
                else default_domain
            )

            if row["recall_domain"] == target_domain:
                unchanged_count += 1
                continue

            updates.append((target_domain, row["memory_unit_id"]))
            if target_domain == protected_domain:
                protected_count += 1
            else:
                default_count += 1

        if updates and not dry_run:
            conn.executemany(
                """
                UPDATE memory_units
                SET recall_domain = ?, updated_at = CURRENT_TIMESTAMP
                WHERE memory_unit_id = ?
                """,
                updates,
            )

    return {
        "total": len(rows),
        "updated": len(updates),
        "marked_protected": protected_count,
        "marked_default": default_count,
        "unchanged": unchanged_count,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill memory_units.recall_domain using PROTECTED_TERMS."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.sqlite_db_path),
        help="Path to the SQLite database. Defaults to SQLITE_DB_PATH.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many rows would change without writing to the database.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(Path(args.db))
    result = backfill_recall_domains(
        sqlite_db,
        protected_terms=settings.protected_terms,
        dry_run=args.dry_run,
    )

    print(
      "扫描了 {total} 个内存单元，更新了 {updated} 个，"
      "标记为敏感 {marked_protected} 个，标记为默认 {marked_default} 个，"
      "未更改 {unchanged} 个。".format(**result)
    )

