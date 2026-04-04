from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from engine.database import DatabaseManager
from scripts.backfill_recall_domains import backfill_recall_domains


class BackfillRecallDomainsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.sqlite_db = DatabaseManager(self.test_dir / "selfindex.db")
        raw_document_id = "test:note:doc-1"
        self.sqlite_db.upsert_raw_document(
            {
                "raw_document_id": raw_document_id,
                "source": "test",
                "source_type": "note",
                "external_id": "doc-1",
                "root_document_id": None,
                "title": "Test",
                "author": "me",
                "created_at": "2026-03-23 10:00:00",
                "content": "root",
                "content_hash": "x",
                "raw_payload": "{}",
                "metadata_json": "{}",
            }
        )
        self.sqlite_db.replace_memory_units(
            raw_document_id,
            [
                {
                    "memory_unit_id": f"{raw_document_id}:0",
                    "raw_document_id": raw_document_id,
                    "unit_index": 0,
                    "unit_type": "chunk",
                    "recall_domain": "default",
                    "content": "This contains Alice private detail",
                    "summary": "private",
                    "start_char": 0,
                    "end_char": 10,
                    "embedding_version": "test",
                    "metadata_json": "{}",
                    "is_embedded": 0,
                },
                {
                    "memory_unit_id": f"{raw_document_id}:1",
                    "raw_document_id": raw_document_id,
                    "unit_index": 1,
                    "unit_type": "chunk",
                    "recall_domain": "sensitive",
                    "content": "generic project note",
                    "summary": "generic",
                    "start_char": 10,
                    "end_char": 20,
                    "embedding_version": "test",
                    "metadata_json": "{}",
                    "is_embedded": 0,
                },
            ],
        )

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_backfill_marks_sensitive_and_resets_others(self) -> None:
        self.sqlite_db.seed_protected_terms(["Alice"])
        result = backfill_recall_domains(
            self.sqlite_db,
        )

        self.assertEqual(result["updated"], 2)
        self.assertEqual(result["marked_sensitive"], 1)
        self.assertEqual(result["marked_default"], 1)
        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:doc-1")
        domains = {row["memory_unit_id"]: row["recall_domain"] for row in rows}
        self.assertEqual(domains["test:note:doc-1:0"], "sensitive")
        self.assertEqual(domains["test:note:doc-1:1"], "default")

    def test_dry_run_does_not_write_changes(self) -> None:
        self.sqlite_db.seed_protected_terms(["Alice"])
        result = backfill_recall_domains(
            self.sqlite_db,
            dry_run=True,
        )

        self.assertEqual(result["updated"], 2)
        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:doc-1")
        domains = {row["memory_unit_id"]: row["recall_domain"] for row in rows}
        self.assertEqual(domains["test:note:doc-1:0"], "default")
        self.assertEqual(domains["test:note:doc-1:1"], "sensitive")

    def test_protected_terms_are_stored_encoded(self) -> None:
        self.sqlite_db.seed_protected_terms(["Alice"])

        with self.sqlite_db.get_connection() as conn:
            row = conn.execute(
                "SELECT term_encoded, encoding, domain FROM protected_terms LIMIT 1"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertNotEqual(row["term_encoded"], "Alice")
        self.assertEqual(row["encoding"], "base64")
        decoded = self.sqlite_db.list_protected_terms()
        self.assertIn("Alice", [item["term"] for item in decoded])

    def test_backfill_can_match_title_not_only_content(self) -> None:
        self.sqlite_db.upsert_raw_document(
            {
                "raw_document_id": "test:note:title-doc",
                "source": "test",
                "source_type": "note",
                "external_id": "title-doc",
                "root_document_id": None,
                "title": "Alice private notebook",
                "author": "me",
                "created_at": "2026-03-23 10:00:00",
                "content": "harmless content",
                "content_hash": "title-hash",
                "raw_payload": "{}",
                "metadata_json": "{}",
            }
        )
        self.sqlite_db.replace_memory_units(
            "test:note:title-doc",
            [
                {
                    "memory_unit_id": "test:note:title-doc:0",
                    "raw_document_id": "test:note:title-doc",
                    "unit_index": 0,
                    "unit_type": "chunk",
                    "recall_domain": "default",
                    "content": "harmless content",
                    "summary": "harmless",
                    "start_char": 0,
                    "end_char": 10,
                    "embedding_version": "test",
                    "metadata_json": "{}",
                    "is_embedded": 0,
                }
            ],
        )
        self.sqlite_db.seed_protected_terms(["Alice"])

        backfill_recall_domains(self.sqlite_db)

        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:title-doc")
        self.assertEqual(rows[0]["recall_domain"], "sensitive")

    def test_backfill_can_mark_identity_domain(self) -> None:
        self.sqlite_db.seed_protected_terms(["Alice"], domain="identity")

        result = backfill_recall_domains(self.sqlite_db)

        self.assertEqual(result["marked_identity"], 1)
        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:doc-1")
        domains = {row["memory_unit_id"]: row["recall_domain"] for row in rows}
        self.assertEqual(domains["test:note:doc-1:0"], "identity")
        self.assertEqual(domains["test:note:doc-1:1"], "default")


if __name__ == "__main__":
    unittest.main()
