from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from engine.database import DatabaseManager
from scripts.sync_markdown_directory import (
    discover_markdown_files,
    load_ignore_patterns,
    sync_markdown_directory,
)


class MarkdownSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.notes_dir = self.test_dir / "notes"
        self.notes_dir.mkdir()
        (self.notes_dir / "daily").mkdir()
        (self.notes_dir / "keep.md").write_text("# Keep\n\nhello", encoding="utf-8")
        (self.notes_dir / "daily" / "today.md").write_text("today note", encoding="utf-8")
        (self.notes_dir / "skip.md").write_text("skip me", encoding="utf-8")
        (self.notes_dir / ".selfindexignore").write_text("skip.md\ndaily/\n", encoding="utf-8")

        self.sqlite_db = DatabaseManager(self.test_dir / "selfindex.db")

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_discover_markdown_files_respects_ignore_rules(self) -> None:
        patterns = load_ignore_patterns(self.notes_dir / ".selfindexignore")
        files = discover_markdown_files(self.notes_dir, ignore_patterns=patterns)
        relative_paths = [path.relative_to(self.notes_dir).as_posix() for path in files]
        self.assertEqual(relative_paths, ["keep.md"])

    def test_sync_markdown_directory_imports_and_skips_unchanged_files(self) -> None:
        first = sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )
        second = sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )

        self.assertEqual(first["files_seen"], 1)
        self.assertEqual(first["synced"], 1)
        self.assertEqual(second["synced"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(self.sqlite_db.count_rows("raw_documents"), 1)
        self.assertEqual(self.sqlite_db.count_rows("raw_document_revisions"), 1)

    def test_sync_markdown_directory_creates_new_revision_on_change(self) -> None:
        sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )
        (self.notes_dir / "keep.md").write_text("# Keep\n\nupdated text", encoding="utf-8")

        result = sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )

        self.assertEqual(result["synced"], 1)
        self.assertEqual(self.sqlite_db.count_rows("raw_documents"), 1)
        self.assertEqual(self.sqlite_db.count_rows("raw_document_revisions"), 2)

    def test_sync_markdown_directory_marks_missing_file_inactive(self) -> None:
        sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )
        (self.notes_dir / "keep.md").unlink()

        result = sync_markdown_directory(
            self.notes_dir,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            ignore_file=self.notes_dir / ".selfindexignore",
        )

        self.assertEqual(result["inactivated"], 1)
        raw_document = self.sqlite_db.get_raw_document("markdown:note_file:keep.md")
        self.assertEqual(raw_document["is_active"], 0)
        self.assertEqual(self.sqlite_db.count_rows("raw_document_revisions"), 2)


if __name__ == "__main__":
    unittest.main()
