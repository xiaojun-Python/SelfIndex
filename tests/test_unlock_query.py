from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager
from engine.retriever import search_memory


class TinyEmbedder:
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        lowered = (text or "").lower()
        return [float(lowered.count("alice")), float(len(lowered))]


class InMemoryVector:
    def __init__(self) -> None:
        self._rows: dict[str, dict] = {}

    def add_vectors(self, ids, embeddings, metadatas, documents) -> None:
        for record_id, embedding, metadata, document in zip(ids, embeddings, metadatas, documents):
            self._rows[record_id] = {
                "embedding": embedding,
                "metadata": metadata,
                "document": document,
            }

    def search(self, query_vector, n_results=5) -> dict:
        ranked = sorted(
            self._rows.items(),
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


class UnlockQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.sqlite_db = DatabaseManager(self.test_dir / "selfindex.db")
        self.vector_db = InMemoryVector()
        self.embedder = TinyEmbedder()

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
                "created_at": "2026-03-22 10:00:00",
                "content": "root",
                "content_hash": "x",
                "raw_payload": "{}",
                "metadata_json": "{}",
            }
        )

        memory_units = [
            {
                "memory_unit_id": f"{raw_document_id}:0",
                "raw_document_id": raw_document_id,
                "unit_index": 0,
                "unit_type": "chunk",
                "recall_domain": "identity",
                "content": "Alice phone is 123",
                "summary": "Alice phone",
                "start_char": 0,
                "end_char": 10,
                "embedding_version": "tiny",
                "metadata_json": "{}",
                "is_embedded": 1,
            }
        ]
        self.sqlite_db.replace_memory_units(raw_document_id, memory_units)

        embeddings = self.embedder.embed_documents([memory_units[0]["content"]])
        self.vector_db.add_vectors(
            ids=[memory_units[0]["memory_unit_id"]],
            embeddings=embeddings,
            metadatas=[{"recall_domain": "identity"}],
            documents=[memory_units[0]["content"]],
        )

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_query_does_not_recall_identity_domain(self) -> None:
        results = search_memory(
            self.sqlite_db,
            self.vector_db,
            query="Alice",
            limit=5,
            embedder=self.embedder,
        )
        self.assertEqual(results, [])

    def test_unlock_prefix_recalls_identity_domain(self) -> None:
        results = search_memory(
            self.sqlite_db,
            self.vector_db,
            query=f"{settings.unlock_prefix_identity} Alice",
            limit=5,
            embedder=self.embedder,
        )
        self.assertTrue(results)
        self.assertEqual(results[0]["recall_domain"], "identity")


if __name__ == "__main__":
    unittest.main()
