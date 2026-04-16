from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager
from engine.memory import build_memory_units, build_raw_document
from scripts.import_exports import import_export_file
from scripts.parsers.chatgpt_parser import parse_format_openai
from scripts.purge_source_documents import purge_source_documents


class FakeEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text))] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text))]


class FakeVectorManager:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def add_vectors(self, ids, embeddings, metadatas, documents) -> None:
        for record_id, embedding, metadata, document in zip(ids, embeddings, metadatas, documents):
            self.records[record_id] = {
                "embedding": embedding,
                "metadata": metadata,
                "document": document,
            }

    def delete_vectors(self, ids) -> None:
        for record_id in ids:
            self.records.pop(record_id, None)


class ChatGPTImportMaintenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.db_path = self.test_dir / "selfindex.db"
        self.sqlite_db = DatabaseManager(self.db_path)
        self.vector_db = FakeVectorManager()
        self.embedder = FakeEmbedder()

        self.export_path = self.test_dir / "chatgpt_export.json"
        self.export_path.write_text(
            json.dumps(
                [
                    {
                        "id": "conv-1",
                        "title": "Out of order mapping",
                        "create_time": "2026-04-10T10:00:00",
                        "mapping": {
                            "root": {
                                "id": "root",
                                "parent": None,
                                "children": ["node-user"],
                                "message": None,
                            },
                            "node-assistant": {
                                "id": "node-assistant",
                                "parent": "node-user",
                                "children": [],
                                "message": {
                                    "id": "msg-2",
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["第二条，助手回答。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T10:00:02",
                                },
                            },
                            "node-user": {
                                "id": "node-user",
                                "parent": "root",
                                "children": ["node-assistant"],
                                "message": {
                                    "id": "msg-1",
                                    "author": {"role": "user"},
                                    "content": {"parts": ["第一条，用户提问。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T10:00:01",
                                },
                            },
                        },
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _insert_markdown_note(self) -> None:
        raw_document = build_raw_document(
            source="markdown",
            source_type="note_file",
            external_id="note-1",
            root_document_id="vault",
            title="Note 1",
            author="user",
            created_at="2026-04-10 12:00:00",
            content="这是一条 markdown 笔记。",
            raw_payload={"path": "note-1.md"},
            metadata={"tags": ["note"]},
        )
        upsert_result = self.sqlite_db.upsert_raw_document(raw_document)
        memory_units = build_memory_units(
            raw_document,
            revision_id=upsert_result["revision_id"],
            embedding_version=settings.embedding_model,
            protected_rules=[],
        )
        self.sqlite_db.insert_memory_units(memory_units)

    def test_parser_rebuilds_linear_order_from_mapping_graph(self) -> None:
        _, messages = list(parse_format_openai(str(self.export_path)))[0]

        self.assertEqual([message["message_id"] for message in messages], ["msg-1", "msg-2"])
        self.assertEqual([message["sequence"] for message in messages], [0, 1])
        self.assertIsNone(messages[0]["parent_message_id"])
        self.assertEqual(messages[1]["parent_message_id"], "msg-1")

    def test_import_stores_parent_message_metadata(self) -> None:
        import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=None,
            skip_embedding=True,
        )

        raw_document = self.sqlite_db.get_raw_document("chatgpt:conversation_message:msg-2")
        self.assertIsNotNone(raw_document)

        metadata = json.loads(raw_document["metadata_json"])
        raw_payload = json.loads(raw_document["raw_payload"])

        self.assertEqual(raw_document["sequence"], 1)
        self.assertEqual(metadata["sequence"], 1)
        self.assertEqual(metadata["parent_message_id"], "msg-1")
        self.assertEqual(raw_payload["message"]["parent_message_id"], "msg-1")

    def test_purge_source_documents_removes_only_chatgpt_data(self) -> None:
        import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            embedder=self.embedder,
        )
        self._insert_markdown_note()

        self.assertTrue(self.vector_db.records)
        self.assertEqual(self.sqlite_db.count_rows("raw_documents"), 3)

        result = purge_source_documents(
            self.sqlite_db,
            source="ChatGPT",
            source_type="conversation_message",
            vector_db=self.vector_db,
        )

        self.assertTrue(result["deleted"])
        self.assertEqual(result["raw_documents_count"], 2)
        self.assertEqual(self.sqlite_db.count_rows("raw_documents"), 1)
        self.assertEqual(self.sqlite_db.count_rows("raw_document_revisions"), 1)
        self.assertGreaterEqual(self.sqlite_db.count_rows("memory_units"), 1)
        self.assertIsNone(self.sqlite_db.get_raw_document("chatgpt:conversation_message:msg-1"))
        self.assertIsNotNone(self.sqlite_db.get_raw_document("markdown:note_file:note-1"))
        self.assertEqual(self.vector_db.records, {})


if __name__ == "__main__":
    unittest.main()
