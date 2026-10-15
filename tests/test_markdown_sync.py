from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from engine.database import DatabaseManager, ReadOnlyDatabase
from scripts.sync_markdown_directory import (
    discover_markdown_files,
    load_ignore_patterns,
    preview_markdown_directory,
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
            allow_empty_source=True,
        )

        self.assertEqual(result["inactivated"], 1)
        raw_document = self.sqlite_db.get_raw_document("markdown:note_file:keep.md")
        self.assertEqual(raw_document["is_active"], 0)
        self.assertEqual(self.sqlite_db.count_rows("raw_document_revisions"), 2)

    def test_missing_source_root_does_not_inactivate_documents(self) -> None:
        sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)
        original = self.sqlite_db.get_raw_document("markdown:note_file:keep.md")
        shutil.rmtree(self.notes_dir)

        with self.assertRaises(FileNotFoundError):
            sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)

        current = self.sqlite_db.get_raw_document("markdown:note_file:keep.md")
        self.assertEqual(current["is_active"], 1)
        self.assertEqual(current["latest_revision_id"], original["latest_revision_id"])

    def test_scan_failure_does_not_inactivate_documents(self) -> None:
        from unittest.mock import patch

        sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)

        def fail_scan(_root, *, onerror):
            onerror(PermissionError("synthetic scan failure"))
            yield from ()

        with patch("scripts.sync_markdown_directory.os.walk", side_effect=fail_scan):
            with self.assertRaises(PermissionError):
                sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)

        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["is_active"], 1)

    def test_replaced_source_root_does_not_inactivate_documents(self) -> None:
        from unittest.mock import patch

        sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)

        def replace_root(_root, **_kwargs):
            self.notes_dir.rename(self.test_dir / "old-notes")
            self.notes_dir.mkdir()
            return []

        with patch("scripts.sync_markdown_directory.discover_markdown_files", side_effect=replace_root):
            with self.assertRaises(OSError):
                sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)

        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["is_active"], 1)

    def test_empty_source_requires_explicit_clear(self) -> None:
        sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)
        for note in self.notes_dir.rglob("*.md"):
            note.unlink()

        with self.assertRaisesRegex(RuntimeError, "no files"):
            sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)
        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["is_active"], 1)

        result = sync_markdown_directory(
            self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None, allow_empty_source=True,
        )
        self.assertGreater(result["inactivated"], 0)
        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["is_active"], 0)

    def test_two_roots_with_same_relative_name_do_not_overwrite(self) -> None:
        first = sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)
        other_root = self.test_dir / "other-notes"
        other_root.mkdir()
        (other_root / "keep.md").write_text("other content", encoding="utf-8")
        second = sync_markdown_directory(other_root, sqlite_db=self.sqlite_db, vector_db=None)

        self.assertEqual(first["identity_mode"], "legacy")
        self.assertEqual(second["identity_mode"], "scoped")
        self.assertNotEqual(first["source_id"], second["source_id"])
        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["content"], "# Keep\n\nhello")
        scoped_id = f"markdown:note_file:@{second['source_id']}/keep.md"
        self.assertEqual(self.sqlite_db.get_raw_document(scoped_id)["content"], "other content")
        self.assertEqual(self.sqlite_db.count_rows("raw_documents"), 4)
        self.assertEqual(
            sync_markdown_directory(other_root, sqlite_db=self.sqlite_db, vector_db=None)["skipped"], 1
        )

    def test_preview_reports_deletions_without_registering_or_inactivating(self) -> None:
        sync_markdown_directory(self.notes_dir, sqlite_db=self.sqlite_db, vector_db=None)
        (self.notes_dir / "keep.md").unlink()
        before_sources = self.sqlite_db.count_rows("markdown_sources")
        preview = preview_markdown_directory(
            self.notes_dir, sqlite_db=ReadOnlyDatabase(self.sqlite_db.db_path)
        )
        self.assertEqual(preview["would_inactivate"], 1)
        self.assertEqual(preview["inactivation_sample"], ["keep.md"])
        self.assertEqual(self.sqlite_db.count_rows("markdown_sources"), before_sources)
        self.assertEqual(self.sqlite_db.get_raw_document("markdown:note_file:keep.md")["is_active"], 1)


if __name__ == "__main__":
    unittest.main()
