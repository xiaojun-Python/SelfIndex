"""Export a plaintext SQLite database into a SQLCipher-encrypted database."""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher_dbapi


def export_to_sqlcipher(
    source_db: str | Path,
    target_db: str | Path,
    *,
    key: str,
) -> None:
    if not key:
        raise ValueError("A non-empty SQLCipher key is required.")

    source_db = Path(source_db)
    target_db = Path(target_db)

    if not source_db.exists():
        raise FileNotFoundError(f"Source database not found: {source_db}")
    if target_db.exists():
        raise FileExistsError(f"Target database already exists: {target_db}")

    target_db.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlcipher_dbapi.connect(str(source_db))
    try:
        escaped_key = key.replace("'", "''")
        conn.execute(f"ATTACH DATABASE ? AS encrypted KEY '{escaped_key}'", (str(target_db),))
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute("DETACH DATABASE encrypted")
    finally:
        conn.close()


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export a plaintext SQLite database into a SQLCipher-encrypted database."
    )
    parser.add_argument("--source", required=True, help="Path to the existing plaintext SQLite database.")
    parser.add_argument("--target", required=True, help="Path to the output encrypted database.")
    parser.add_argument("--key", required=True, help="SQLCipher key to apply to the encrypted database.")
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    export_to_sqlcipher(args.source, args.target, key=args.key)
    print(f"Exported encrypted database to: {args.target}")
