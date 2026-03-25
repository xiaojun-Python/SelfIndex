from __future__ import annotations

import shutil
import sqlite3
import unittest
from pathlib import Path

from sqlcipher3 import dbapi2 as sqlcipher_dbapi

from scripts.migrate_to_sqlcipher import export_to_sqlcipher


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


if __name__ == "__main__":
    unittest.main()

