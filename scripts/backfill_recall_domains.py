"""Backfill ``memory_units.recall_domain`` using protected term rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager
from engine.memory import build_protected_match_text

DOMAIN_PRIORITY = {
    "default": 0,
    "identity": 1,
    "sensitive": 2,
}


def _matches_protected_terms(match_text: str, protected_terms: list[str]) -> bool:
    lowered = (match_text or "").lower()
    return any(term.lower() in lowered for term in protected_terms if term.strip())


def backfill_recall_domains(
    sqlite_db: DatabaseManager,
    *,
    protected_terms: list[str] | None = None,
    protected_rules: list[dict] | None = None,
    protected_domain: str = "sensitive",
    default_domain: str = "default",
    dry_run: bool = False,
) -> dict[str, int]:
    if protected_rules is None:
        if protected_terms is None:
            protected_rules = sqlite_db.list_protected_terms()
        else:
            protected_rules = [
                {"term": term.strip(), "domain": protected_domain}
                for term in protected_terms
                if term.strip()
            ]

    with sqlite_db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT mu.memory_unit_id, mu.content, mu.recall_domain, rd.title, rd.author
            FROM memory_units mu
            JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
            """
        ).fetchall()

        updates: list[tuple[str, str]] = []
        unchanged_count = 0
        updated_by_domain: dict[str, int] = {}

        for row in rows:
            target_domain = default_domain
            match_text = build_protected_match_text(
                content=row["content"],
                title=row.get("title"),
                author=row.get("author"),
            )
            matched_domains: list[str] = []

            for rule in protected_rules:
                term = (rule.get("term") or "").strip()
                if not term:
                    continue
                if _matches_protected_terms(match_text, [term]):
                    matched_domains.append(rule.get("domain") or protected_domain)

            if matched_domains:
                target_domain = max(
                    matched_domains,
                    key=lambda domain: DOMAIN_PRIORITY.get(domain, DOMAIN_PRIORITY[protected_domain]),
                )

            if row["recall_domain"] == target_domain:
                unchanged_count += 1
                continue

            updates.append((target_domain, row["memory_unit_id"]))
            updated_by_domain[target_domain] = updated_by_domain.get(target_domain, 0) + 1

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
        "unchanged": unchanged_count,
        "marked_default": updated_by_domain.get(default_domain, 0),
        "marked_identity": updated_by_domain.get("identity", 0),
        "marked_sensitive": updated_by_domain.get("sensitive", 0),
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill memory_units.recall_domain using protected_terms rules."
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
        dry_run=args.dry_run,
    )

    print(
        "Scanned {total} memory units; updated {updated}. "
        "Marked default={marked_default}, identity={marked_identity}, "
        "sensitive={marked_sensitive}; unchanged={unchanged}.".format(**result)
    )
