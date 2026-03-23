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
        result = backfill_recall_domains(
            self.sqlite_db,
            protected_terms=["Alice"],
        )

        self.assertEqual(result["updated"], 2)
        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:doc-1")
        domains = {row["memory_unit_id"]: row["recall_domain"] for row in rows}
        self.assertEqual(domains["test:note:doc-1:0"], "sensitive")
        self.assertEqual(domains["test:note:doc-1:1"], "default")

    def test_dry_run_does_not_write_changes(self) -> None:
        result = backfill_recall_domains(
            self.sqlite_db,
            protected_terms=["Alice"],
            dry_run=True,
        )

        self.assertEqual(result["updated"], 2)
        rows = self.sqlite_db.get_memory_units_by_raw_document_id("test:note:doc-1")
        domains = {row["memory_unit_id"]: row["recall_domain"] for row in rows}
        self.assertEqual(domains["test:note:doc-1:0"], "default")
        self.assertEqual(domains["test:note:doc-1:1"], "sensitive")


if __name__ == "__main__":
    unittest.main()

