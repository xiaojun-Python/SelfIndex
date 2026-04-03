"""Manage protected terms stored in the database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage protected terms stored in the SelfIndex database."
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(settings.sqlite_db_path),
        help="Path to the SQLite / SQLCipher database.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add one or more protected terms.")
    add_parser.add_argument("terms", nargs="+", help="Protected term text to add.")
    add_parser.add_argument(
        "--domain",
        default="sensitive",
        help="Recall domain to assign when this term matches. Default: sensitive.",
    )

    list_parser = subparsers.add_parser("list", help="List protected terms.")
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="Include inactive terms.",
    )

    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(Path(args.db))

    if args.command == "add":
        added = sqlite_db.seed_protected_terms(args.terms, domain=args.domain)
        print(
            json.dumps(
                {
                    "added_or_ignored": added,
                    "domain": args.domain,
                    "terms": args.terms,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "list":
        rows = sqlite_db.list_protected_terms(active_only=not args.all)
        print(json.dumps(rows, ensure_ascii=False, indent=2))
