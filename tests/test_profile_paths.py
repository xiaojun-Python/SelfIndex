"""Storage defaults follow DATA_DIR without silently abandoning an existing archive."""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

settings_module = importlib.import_module("app.core.settings")


class ProfilePathTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="selfindex-path-test-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name) / "project"
        self.root.mkdir()
        self.base_patch = patch.object(settings_module, "BASE_DIR", self.root)
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)

    def _settings(self, environment):
        with patch.dict(os.environ, environment, clear=True):
            return settings_module.Settings()

    def test_new_profile_uses_data_dir_with_spaces_and_unicode(self):
        data_root = self.root / "新资料 空格"
        current = self._settings({"DATA_DIR": str(data_root)})
        self.assertEqual(current.sqlite_db_path, data_root / "selfindex.db")
        self.assertEqual(current.chroma_db_path, data_root / "chroma_db")
        self.assertEqual(current.raw_exports_dir, data_root / "raw_exports")
        self.assertEqual(current.storage_layout, "unified")

    def test_existing_legacy_paths_remain_selected_until_explicit_migration(self):
        legacy = self.root / "data"
        legacy.mkdir()
        (legacy / "selfindex.db").touch()
        (legacy / "chroma_db").mkdir()
        (legacy / "raw_exports").mkdir()
        new_root = self.root / "new data"
        current = self._settings({"DATA_DIR": str(new_root)})
        self.assertEqual(current.sqlite_db_path, legacy / "selfindex.db")
        self.assertEqual(current.chroma_db_path, legacy / "chroma_db")
        self.assertEqual(current.raw_exports_dir, legacy / "raw_exports")
        self.assertEqual(current.storage_layout, "split")

    def test_explicit_overrides_win_and_relative_paths_are_project_relative(self):
        legacy = self.root / "data"
        legacy.mkdir()
        (legacy / "selfindex.db").touch()
        (legacy / "chroma_db").mkdir()
        (legacy / "raw_exports").mkdir()
        current = self._settings({
            "DATA_DIR": "profile root",
            "SQLITE_DB_PATH": "separate/archive.db",
            "CHROMA_DB_PATH": "separate/vectors",
            "RAW_EXPORTS_DIR": "separate/exports",
        })
        self.assertEqual(current.data_dir, self.root / "profile root")
        self.assertEqual(current.sqlite_db_path, self.root / "separate/archive.db")
        self.assertEqual(current.chroma_db_path, self.root / "separate/vectors")
        self.assertEqual(current.raw_exports_dir, self.root / "separate/exports")
        self.assertEqual(current.storage_layout, "split")

    def test_resolution_does_not_depend_on_current_working_directory(self):
        previous = Path.cwd()
        try:
            os.chdir(self.temp_dir.name)
            current = self._settings({"DATA_DIR": "relative profile"})
        finally:
            os.chdir(previous)
        self.assertEqual(current.data_dir, self.root / "relative profile")
        self.assertEqual(current.sqlite_db_path, current.data_dir / "selfindex.db")


if __name__ == "__main__":
    unittest.main()
