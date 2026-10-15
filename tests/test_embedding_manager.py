"""Cold concurrent requests load one model without serializing later inference."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import patch

from engine import embedder


class EmbeddingManagerTests(unittest.TestCase):
    def test_cold_concurrent_access_constructs_once(self):
        manager = embedder.EmbeddingManager("test-model", "cpu")
        entered, release = Event(), Event()
        calls = []
        calls_lock = Lock()
        model = object()

        def construct(**_kwargs):
            with calls_lock:
                calls.append(1)
            entered.set()
            self.assertTrue(release.wait(timeout=5))
            return model

        with patch.object(embedder, "HuggingFaceEmbeddings", side_effect=construct):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(lambda: manager.model)
                self.assertTrue(entered.wait(timeout=5))
                second = pool.submit(lambda: manager.model)
                release.set()
                self.assertIs(first.result(timeout=5), model)
                self.assertIs(second.result(timeout=5), model)
        self.assertEqual(len(calls), 1)

    def test_failed_initialization_can_retry(self):
        manager = embedder.EmbeddingManager("test-model", "cpu")
        model = object()
        with patch.object(
            embedder, "HuggingFaceEmbeddings",
            side_effect=[RuntimeError("synthetic load failure"), model],
        ) as constructor:
            with self.assertRaisesRegex(RuntimeError, "synthetic load failure"):
                _ = manager.model
            self.assertIs(manager.model, model)
        self.assertEqual(constructor.call_count, 2)


if __name__ == "__main__":
    unittest.main()
