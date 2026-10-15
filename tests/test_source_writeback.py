"""Markdown App edits persist to source files without hiding cross-store failures."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.documents import save_document
from app.services.source_writeback import SourceWriteConflictError, drain_pending_source_writes, drain_source_write
from engine.database import DatabaseManager
from engine.retriever import get_memory_unit_payload
from scripts.sync_markdown_directory import sync_markdown_directory


class TinyEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0, 2.0] for text in texts]


class FakeVectors:
    def __init__(self):
        self.records = {}

    def add_vectors(self, ids, embeddings, metadatas, documents):
        for unit_id, document in zip(ids, documents):
            self.records[unit_id] = document

    def delete_vectors(self, ids):
        for unit_id in ids:
            self.records.pop(unit_id, None)


class SourceWritebackTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="selfindex-source-write-test-")
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.notes = root / "notes"
        self.notes.mkdir()
        self.path = self.notes / "note.md"
        self.path.write_text("Original\n", encoding="utf-8")
        self.db = DatabaseManager(root / "archive.db")
        self.vectors = FakeVectors()
        sync_markdown_directory(self.notes, sqlite_db=self.db, vector_db=None)
        self.raw_id = "markdown:note_file:note.md"
        self.unit_id = self.db.get_memory_units_by_raw_document_id(self.raw_id)[0]["memory_unit_id"]
        self.initial = get_memory_unit_payload(self.db, self.unit_id)["raw_document"]

    def _save(self, content):
        return save_document(
            self.db, self.vectors, self.unit_id,
            title="note", author="", content=content,
            expected_revision_id=self.initial["latest_revision_id"],
            expected_edit_version=self.initial["edit_version"],
            embedder=TinyEmbedder(),
        )

    def test_edit_writes_file_then_sync_does_not_revert_it(self):
        result = self._save("Changed\n")
        self.assertEqual(result["source_status"], "ready")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "Changed\n")
        self.assertEqual(self.db.get_raw_document(self.raw_id)["content"], "Changed\n")
        self.assertEqual(self.db.count_pending_source_writes(), 0)
        self.assertEqual(sync_markdown_directory(self.notes, sqlite_db=self.db, vector_db=None)["skipped"], 1)

    def test_external_edit_is_conflict_before_archive_changes(self):
        self.path.write_text("Changed outside App\n", encoding="utf-8")
        with self.assertRaises(SourceWriteConflictError):
            self._save("App draft\n")
        self.assertEqual(self.db.get_raw_document(self.raw_id)["content"], "Original\n")
        self.assertEqual(self.db.count_pending_source_writes(), 0)

    def test_failed_file_write_remains_replayable_and_blocks_sync(self):
        with patch("app.services.source_writeback._atomic_replace", side_effect=OSError("disk unavailable")):
            with self.assertLogs("app.services.documents", level="ERROR"):
                result = self._save("Changed\n")
        self.assertEqual(result["source_status"], "pending")
        self.assertEqual(self.db.get_raw_document(self.raw_id)["content"], "Changed\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), "Original\n")
        self.assertEqual(self.db.count_pending_source_writes(), 1)
        with self.assertRaisesRegex(RuntimeError, "pending App writes"):
            sync_markdown_directory(self.notes, sqlite_db=self.db, vector_db=None)
        self.assertTrue(drain_source_write(self.db, self.raw_id))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "Changed\n")
        self.assertEqual(self.db.count_pending_source_writes(), 0)

    def test_external_change_while_pending_is_not_overwritten(self):
        with patch("app.services.source_writeback._atomic_replace", side_effect=OSError("disk unavailable")):
            with self.assertLogs("app.services.documents", level="ERROR"):
                self._save("Changed\n")
        self.path.write_text("New external edit\n", encoding="utf-8")
        with self.assertRaises(SourceWriteConflictError):
            drain_source_write(self.db, self.raw_id)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "New external edit\n")
        self.assertEqual(self.db.count_pending_source_writes(), 1)

    def test_batch_replay_restores_file_after_transient_failure(self):
        with patch("app.services.source_writeback._atomic_replace", side_effect=OSError("disk unavailable")):
            with self.assertLogs("app.services.documents", level="ERROR"):
                self._save("Changed\n")
        self.assertEqual(drain_pending_source_writes(self.db), {"processed": 1, "failed": 0, "pending": 0})
        self.assertEqual(self.path.read_text(encoding="utf-8"), "Changed\n")

    def test_batch_replay_counts_external_conflict_without_overwrite(self):
        with patch("app.services.source_writeback._atomic_replace", side_effect=OSError("disk unavailable")):
            with self.assertLogs("app.services.documents", level="ERROR"):
                self._save("Changed\n")
        self.path.write_text("External\n", encoding="utf-8")
        self.assertEqual(drain_pending_source_writes(self.db), {"processed": 0, "failed": 1, "pending": 1})
        self.assertEqual(self.path.read_text(encoding="utf-8"), "External\n")


if __name__ == "__main__":
    unittest.main()
