from __future__ import annotations

import shutil
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from sqlcipher3 import dbapi2 as sqlcipher_dbapi

from scripts.migrate_to_sqlcipher import export_to_sqlcipher
from app.core.settings import settings
from engine.sqlite_backend import connect_database


class SqlcipherMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_export_plaintext_db_to_sqlcipher(self) -> None:
        source_db = self.test_dir / "plain.db"
        target_db = self.test_dir / "encrypted.db"

        conn = sqlite3.connect(source_db)
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO notes (title) VALUES ('hello')")
        conn.commit()
        conn.close()

        export_to_sqlcipher(source_db, target_db, key="test-passphrase")

        encrypted = sqlcipher_dbapi.connect(str(target_db))
        encrypted.execute("PRAGMA key = 'test-passphrase'")
        row = encrypted.execute("SELECT title FROM notes").fetchone()
        encrypted.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "hello")

        with patch("engine.sqlite_backend.settings", replace(settings, sqlite_cipher_key="test-passphrase")):
            with connect_database(target_db, read_only=True) as read_only:
                self.assertEqual(read_only.execute("SELECT title FROM notes").fetchone()["title"], "hello")
                with self.assertRaises(Exception):
                    read_only.execute("DELETE FROM notes")


if __name__ == "__main__":
    unittest.main()
