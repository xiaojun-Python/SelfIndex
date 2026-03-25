"""SQLite backend helpers with optional SQLCipher support."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.settings import settings

try:
    from sqlcipher3 import dbapi2 as sqlcipher_dbapi
except ImportError:  # pragma: no cover - optional dependency
    sqlcipher_dbapi = None


def _dict_row_factory(cursor, row):
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def using_sqlcipher() -> bool:
    return bool(settings.sqlite_cipher_key)


def connect_database(db_path: str | Path):
    path = str(Path(db_path))

    if using_sqlcipher():
        if sqlcipher_dbapi is None:
            raise RuntimeError("SQLCipher key is configured, but sqlcipher3 is not installed.")

        conn = sqlcipher_dbapi.connect(path)
        escaped_key = settings.sqlite_cipher_key.replace("'", "''")
        conn.execute(f"PRAGMA key = '{escaped_key}'")
    else:
        conn = sqlite3.connect(path)

    conn.row_factory = _dict_row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
