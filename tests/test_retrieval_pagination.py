"""Filtered top-K results can expand within a fixed candidate budget."""

from __future__ import annotations

import unittest

from engine.retriever import search_memory


class FakeEmbedder:
    def embed_query(self, _text):
        return [1.0, 0.0]


class RankedVectors:
    def __init__(self, ids):
        self.ids = ids
        self.requests = []

    def search(self, _vector, n_results=5):
        self.requests.append(n_results)
        selected = self.ids[:n_results]
        return {"ids": [selected], "distances": [[float(i) for i in range(len(selected))]]}


class SqlDetails:
    def __init__(self, public_id):
        self.public_id = public_id

    def get_memory_unit_details(self, ids):
        details = {}
        for unit_id in ids:
            details[unit_id] = {
                "is_active": 1,
                "revision_is_current": 1,
                "recall_domain": "default" if unit_id == self.public_id else "identity",
                "memory_content": unit_id,
                "summary": unit_id,
                "source": "test",
                "source_type": "note",
                "title": unit_id,
                "author": "",
                "created_at": "2026-09-28T00:00:00",
                "raw_document_id": unit_id,
                "external_id": unit_id,
                "root_document_id": None,
                "start_char": 0,
                "end_char": len(unit_id),
            }
        return details


class RetrievalPaginationTests(unittest.TestCase):
    def test_public_result_behind_protected_top_100_is_found(self):
        vectors = RankedVectors([f"protected-{i}" for i in range(100)] + ["public"])
        results = search_memory(SqlDetails("public"), vectors, query="example", limit=10, embedder=FakeEmbedder())
        self.assertEqual([result["memory_unit_id"] for result in results], ["public"])
        self.assertEqual(vectors.requests, [100, 200])

    def test_expansion_stops_at_bounded_candidate_budget(self):
        vectors = RankedVectors([f"protected-{i}" for i in range(2500)] + ["public"])
        results = search_memory(SqlDetails("public"), vectors, query="example", limit=10, embedder=FakeEmbedder())
        self.assertEqual(results, [])
        self.assertEqual(vectors.requests, [100, 200, 400, 800])


if __name__ == "__main__":
    unittest.main()
