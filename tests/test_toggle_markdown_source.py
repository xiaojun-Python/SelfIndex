"""Disabling an old Markdown source hides it without deleting its archive or files."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from engine.database import DatabaseManager, ReadOnlyDatabase
from engine.retriever import get_memory_unit_payload
from scripts.sync_markdown_directory import sync_markdown_directory
from scripts.toggle_markdown_source import inspect_source, set_source_enabled


class FakeVectors:
    def __init__(self, ids):
        self.ids = set(ids)

    def delete_vectors(self, ids):
        self.ids.difference_update(ids)


class ToggleMarkdownSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="selfindex-toggle-source-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "notes"
        self.root.mkdir()
        self.source_root = str(self.root.resolve())
        (self.root / "a.md").write_text("# A\n\nOriginal text", encoding="utf-8")
        (self.root / "b.md").write_text("# B\n\nAnother note", encoding="utf-8")
        self.db = DatabaseManager(Path(temporary.name) / "archive.db")
        sync_markdown_directory(self.root, sqlite_db=self.db, vector_db=None)
        with self.db.transaction() as conn:
            ids = [row["memory_unit_id"] for row in conn.execute("SELECT memory_unit_id FROM memory_units")]
            conn.execute("UPDATE memory_units SET is_embedded = 1")
        self.vectors = FakeVectors(ids)

    def test_disable_preserves_documents_revisions_and_files(self):
        before_revisions = self.db.count_rows("raw_document_revisions")
        before = inspect_source(ReadOnlyDatabase(self.db.db_path), self.source_root)
        self.assertEqual(before["documents"], 2)
        self.assertEqual(before["active_documents"], 2)
        unit_id = next(iter(self.vectors.ids))

        result = set_source_enabled(
            self.db, self.source_root, enabled=False, expected_documents=2, vector_db=self.vectors,
        )
        self.assertEqual(result["changed_documents"], 2)
        self.assertEqual(result["pending_vector_deletions"], 0)
        self.assertEqual(self.vectors.ids, set())
        self.assertEqual(self.db.count_rows("raw_documents"), 2)
        self.assertEqual(self.db.count_rows("raw_document_revisions"), before_revisions)
        self.assertEqual(self.db.get_raw_document("markdown:note_file:a.md")["content"], "# A\n\nOriginal text")
        self.assertEqual((self.root / "a.md").read_text(encoding="utf-8"), "# A\n\nOriginal text")
        self.assertIsNone(get_memory_unit_payload(self.db, unit_id))
        self.assertEqual(inspect_source(self.db, self.source_root)["active_documents"], 0)

        restored = set_source_enabled(self.db, self.source_root, enabled=True, expected_documents=2)
        self.assertEqual(restored["changed_documents"], 2)
        self.assertEqual(inspect_source(self.db, self.source_root)["active_documents"], 2)
        self.assertEqual(self.db.count_pending_embeddings(), restored["current_units"])

    def test_wrong_expected_count_changes_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "Expected 3 documents"):
            set_source_enabled(self.db, self.source_root, enabled=False, expected_documents=3)
        self.assertEqual(inspect_source(self.db, self.source_root)["active_documents"], 2)
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)


if __name__ == "__main__":
    unittest.main()
