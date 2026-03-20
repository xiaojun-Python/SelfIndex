"""最小记忆链路测试。

这些测试不依赖真实 embedding 模型和 Chroma，
目的是快速验证链路行为是否正确。
"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from engine.database import DatabaseManager
from engine.retriever import get_memory_unit_payload, search_memory
from scripts.import_legacy_data import import_export_file


class FakeEmbedder:
    """用简单词频向量代替真实 embedding，方便做稳定测试。"""

    TOKENS = ["记忆", "向量", "数据库", "检索", "问题", "助手", "项目"]

    def _embed(self, text: str) -> list[float]:
        lowered = text.lower()
        vector = [float(lowered.count(token.lower())) for token in self.TOKENS]
        vector.append(float(len(text)))
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FakeVectorManager:
    """在内存里模拟一个极简向量库。"""

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

    def search(self, query_vector, n_results=5) -> dict:
        ranked = sorted(
            self.records.items(),
            key=lambda item: self._distance(query_vector, item[1]["embedding"]),
        )[:n_results]
        return {
            "ids": [[record_id for record_id, _ in ranked]],
            "documents": [[item["document"] for _, item in ranked]],
            "metadatas": [[item["metadata"] for _, item in ranked]],
            "distances": [[self._distance(query_vector, item["embedding"]) for _, item in ranked]],
        }

    @staticmethod
    def _distance(left: list[float], right: list[float]) -> float:
        return sum(abs(a - b) for a, b in zip(left, right))


class MemoryPipelineTests(unittest.TestCase):
    """覆盖导入、检索和回溯这条最小链路。"""

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
                        "title": "SelfIndex 第一阶段",
                        "create_time": "2026-03-18T08:30:00",
                        "mapping": {
                            "node-1": {
                                "message": {
                                    "id": "msg-1",
                                    "author": {"role": "user"},
                                    "content": {
                                        "parts": [
                                            "我想先把记忆链路做通，让原始文档和向量检索可以关联起来。"
                                        ]
                                    },
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-03-18T08:31:00",
                                }
                            },
                            "node-2": {
                                "message": {
                                    "id": "msg-2",
                                    "author": {"role": "assistant"},
                                    "content": {
                                        "parts": [
                                            "可以先建立原始文档层，再生成记忆单元，并把向量索引指回原始数据库记录。"
                                        ]
                                    },
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-03-18T08:32:00",
                                }
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

    def test_import_creates_archive_and_memory_layers(self) -> None:
        result = import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            embedder=self.embedder,
        )

        self.assertEqual(result["raw_documents"], 2)
        self.assertGreaterEqual(result["memory_units"], 2)

        raw_document = self.sqlite_db.get_raw_document("chatgpt:conversation_message:msg-1")
        self.assertIsNotNone(raw_document)
        self.assertIn("记忆链路", raw_document["content"])

        memory_units = self.sqlite_db.get_memory_units_by_raw_document_id(
            "chatgpt:conversation_message:msg-2"
        )
        self.assertGreaterEqual(len(memory_units), 1)
        self.assertTrue(memory_units[0]["summary"])

    def test_search_results_can_trace_back_to_raw_document(self) -> None:
        import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            embedder=self.embedder,
        )

        results = search_memory(
            self.sqlite_db,
            self.vector_db,
            query="向量 数据库",
            limit=5,
            embedder=self.embedder,
        )

        self.assertTrue(results)
        top_result = results[0]
        self.assertEqual(top_result["raw_document_id"], top_result["trace"]["raw_document_id"])

        payload = get_memory_unit_payload(self.sqlite_db, top_result["memory_unit_id"])
        self.assertIsNotNone(payload)
        self.assertIn("向量", payload["raw_document"]["content"])

    def test_reimport_replaces_memory_units_without_vector_duplicates(self) -> None:
        first = import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            embedder=self.embedder,
        )
        second = import_export_file(
            self.export_path,
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            embedder=self.embedder,
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.vector_db.records), second["memory_units"])


if __name__ == "__main__":
    unittest.main()
