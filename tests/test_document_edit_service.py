"""Document edits keep committed content recoverable when indexing fails."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.settings import settings
from app.services.documents import DocumentConflictError, save_document
from engine.database import DatabaseManager
from engine.memory import build_memory_units, build_raw_document
from engine.retriever import get_memory_unit_payload
from scripts.build_embeddings import build_missing_embeddings


class FakeEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text))] for text in texts]


class FailingEmbedder:
    def embed_documents(self, texts):
        raise RuntimeError("embedding unavailable")


class FakeVectors:
    def __init__(self):
        self.records = {}

    def add_vectors(self, ids, embeddings, metadatas, documents):
        for index, unit_id in enumerate(ids):
            self.records[unit_id] = {
                "embedding": embeddings[index],
                "metadata": metadatas[index],
                "document": documents[index],
            }

    def delete_vectors(self, ids):
        for unit_id in ids:
            self.records.pop(unit_id, None)


class DocumentEditTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path.cwd() / ".tmp_tests")
        self.addCleanup(self.temp_dir.cleanup)
        self.db = DatabaseManager(Path(self.temp_dir.name) / "documents.db")
        self.vectors = FakeVectors()
        self.embedder = FakeEmbedder()
        original = build_raw_document(
            source="test",
            source_type="note",
            external_id="one",
            root_document_id="notes",
            title="First title",
            author="Author",
            created_at="2026-01-01T00:00:00",
            content="First body text",
            raw_payload={},
            metadata={},
        )
        upsert = self.db.upsert_raw_document(original)
        units = build_memory_units(
            original,
            revision_id=upsert["revision_id"],
            embedding_version=settings.embedding_model,
        )
        self.db.insert_memory_units(units)
        self.old_id = units[0]["memory_unit_id"]
        self.vectors.add_vectors(
            [self.old_id],
            self.embedder.embed_documents([units[0]["content"]]),
            [{"title": original["title"]}],
            [units[0]["content"]],
        )
        self.db.mark_memory_units_as_embedded([self.old_id])

    def test_edit_rebuilds_current_vectors_and_removes_old_ones(self):
        result = save_document(
            self.db,
            self.vectors,
            self.old_id,
            title="Second title",
            author="Author",
            content="Second body text",
            embedder=self.embedder,
        )

        self.assertTrue(result["revision_changed"])
        self.assertEqual(result["index_status"], "ready")
        self.assertNotIn(self.old_id, self.vectors.records)
        self.assertIn(result["memory_unit_id"], self.vectors.records)
        self.assertEqual(
            self.db.get_memory_units_by_raw_document_id(result["raw_document_id"])[0]["is_embedded"],
            1,
        )

    def test_failed_embedding_leaves_rebuildable_pending_units(self):
        with self.assertLogs("app.services.documents", level="ERROR"):
            result = save_document(
                self.db,
                self.vectors,
                self.old_id,
                title="Second title",
                author="Author",
                content="Second body text",
                embedder=FailingEmbedder(),
            )

        self.assertEqual(result["index_status"], "pending")
        self.assertNotEqual(result["memory_unit_id"], self.old_id)
        self.assertEqual(
            self.db.get_memory_units_by_raw_document_id(result["raw_document_id"])[0]["is_embedded"],
            0,
        )
        rebuilt = build_missing_embeddings(
            sqlite_db=self.db,
            vector_db=self.vectors,
            embedder=self.embedder,
        )
        self.assertEqual(rebuilt, {"processed": 1, "has_remaining": 0})
        self.assertIn(result["memory_unit_id"], self.vectors.records)

    def test_unchanged_save_reports_pending_until_rebuilt(self):
        with self.assertLogs("app.services.documents", level="ERROR"):
            first = save_document(
                self.db, self.vectors, self.old_id,
                title="First title", author="Author", content="New content",
                embedder=FailingEmbedder(),
            )
        self.assertEqual(first["index_status"], "pending")

        repeated = save_document(
            self.db, self.vectors, first["memory_unit_id"],
            title="First title", author="Author", content="New content",
            embedder=self.embedder,
        )
        self.assertEqual(repeated["index_status"], "pending")
        self.assertEqual(len(self.db.get_memory_units_needing_embeddings()), 1)

        build_missing_embeddings(
            sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
        )
        ready = save_document(
            self.db, self.vectors, first["memory_unit_id"],
            title="First title", author="Author", content="New content",
            embedder=self.embedder,
        )
        self.assertEqual(ready["index_status"], "ready")

    def test_title_change_reindexes_existing_memory_id(self):
        result = save_document(
            self.db,
            self.vectors,
            self.old_id,
            title="Renamed title",
            author="Author",
            content="First body text",
            embedder=self.embedder,
        )

        self.assertFalse(result["revision_changed"])
        self.assertEqual(result["memory_unit_id"], self.old_id)
        self.assertEqual(result["index_status"], "ready")
        self.assertEqual(self.vectors.records[self.old_id]["metadata"]["title"], "Renamed title")

    def test_save_returns_server_normalized_document(self):
        result = save_document(
            self.db, self.vectors, self.old_id,
            title="  Name  ", author="  ", content="  body  ",
            embedder=self.embedder,
        )

        self.assertEqual(result["document"], {
            "title": "Name", "author": "unknown", "content": "body",
        })

    def test_failed_old_vector_cleanup_does_not_mark_new_index_pending(self):
        original_delete = self.vectors.delete_vectors

        def fail_only_old_ids(ids):
            if self.old_id in ids:
                raise RuntimeError("old vector cleanup unavailable")
            original_delete(ids)

        self.vectors.delete_vectors = fail_only_old_ids
        with self.assertLogs("app.services.documents", level="ERROR"):
            result = save_document(
                self.db,
                self.vectors,
                self.old_id,
                title="Second title",
                author="Author",
                content="Second body text",
                embedder=self.embedder,
            )

        self.assertEqual(result["index_status"], "ready")
        self.assertEqual(
            self.db.get_memory_units_by_raw_document_id(result["raw_document_id"])[0]["is_embedded"],
            1,
        )

    def test_stale_revision_and_aba_edit_version_are_rejected(self):
        initial = get_memory_unit_payload(self.db, self.old_id)["raw_document"]
        first = save_document(
            self.db, self.vectors, self.old_id,
            title="First title", author="Author", content="Second body text",
            expected_revision_id=initial["latest_revision_id"],
            expected_edit_version=initial["edit_version"], embedder=self.embedder,
        )
        historical = get_memory_unit_payload(self.db, self.old_id)
        self.assertTrue(historical["raw_document"]["historical"])
        self.assertEqual(historical["raw_document"]["content"], "First body text")
        with self.assertRaises(DocumentConflictError):
            save_document(
                self.db, self.vectors, self.old_id,
                title="Stale", author="Author", content="Stale overwrite",
                expected_revision_id=initial["latest_revision_id"],
                expected_edit_version=initial["edit_version"], embedder=self.embedder,
            )

        second = save_document(
            self.db, self.vectors, first["memory_unit_id"],
            title="First title", author="Author", content="First body text",
            expected_revision_id=first["revision_id"],
            expected_edit_version=first["edit_version"], embedder=self.embedder,
        )
        self.assertGreater(second["edit_version"], initial["edit_version"])
        with self.assertRaises(DocumentConflictError):
            save_document(
                self.db, self.vectors, self.old_id,
                title="Stale", author="Author", content="Stale overwrite",
                expected_revision_id=initial["latest_revision_id"],
                expected_edit_version=initial["edit_version"], embedder=self.embedder,
            )

    def test_metadata_only_edit_advances_version_without_new_revision(self):
        initial = get_memory_unit_payload(self.db, self.old_id)["raw_document"]
        result = save_document(
            self.db, self.vectors, self.old_id,
            title="Renamed", author="Author", content="First body text",
            expected_revision_id=initial["latest_revision_id"],
            expected_edit_version=initial["edit_version"], embedder=self.embedder,
        )
        self.assertFalse(result["revision_changed"])
        self.assertGreater(result["edit_version"], initial["edit_version"])
        with self.assertRaises(DocumentConflictError):
            save_document(
                self.db, self.vectors, self.old_id,
                title="Other rename", author="Author", content="First body text",
                expected_revision_id=initial["latest_revision_id"],
                expected_edit_version=initial["edit_version"], embedder=self.embedder,
            )


if __name__ == "__main__":
    unittest.main()
