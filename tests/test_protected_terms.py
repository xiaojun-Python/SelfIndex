from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from engine.database import DatabaseManager


class ProtectedTermsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        self.sqlite_db = DatabaseManager(self.test_dir / "selfindex.db")

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_seed_and_list_protected_terms(self) -> None:
        self.sqlite_db.seed_protected_terms(["Alice", "Bob"], domain="sensitive")
        rows = self.sqlite_db.list_protected_terms()

        self.assertGreaterEqual(len(rows), 2)
        self.assertIn("Alice", [row["term"] for row in rows])
        self.assertIn("Bob", [row["term"] for row in rows])
        self.assertTrue(all(row["domain"] == "sensitive" for row in rows if row["term"] in {"Alice", "Bob"}))


if __name__ == "__main__":
    unittest.main()
