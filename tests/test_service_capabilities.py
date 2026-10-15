"""Status distinguishes process liveness from archive and search capability."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from app.api.v1 import bp
from engine.database import INDEX_MODEL_KEY, DatabaseManager


class FakeCollection:
    def __init__(self):
        self.metadata = {}
        self.vector_count = 0

    def count(self):
        return self.vector_count


class ServiceCapabilitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="selfindex-status-test-")
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.db = DatabaseManager(root / "archive.db")
        self.collection = FakeCollection()
        self.vector_path = root / "chroma"
        self.vector_path.mkdir()
        self.vectors = SimpleNamespace(collection=self.collection, persist_directory=self.vector_path)
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLITE_DB=self.db,
            VECTOR_DB=self.vectors,
            SETTINGS=SimpleNamespace(embedding_model="test-model"),
            INSTANCE_ID="test-instance",
        )
        self.app.register_blueprint(bp)
        self.client = self.app.test_client()

    def test_status_is_lightweight_and_profile_identity_survives_reopen(self):
        with patch.dict(sys.modules, {"engine.embedder": SimpleNamespace(
            embedding_manager=SimpleNamespace(_model=None)
        )}):
            response = self.client.get("/api/v1/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["instance_id"], "test-instance")
        self.assertEqual(payload["index"]["state"], "empty")
        self.assertFalse(payload["index"]["model_loaded"])
        self.assertEqual(payload["pending"], {"embeddings": 0, "vector_deletions": 0, "source_writes": 0})
        self.assertTrue(payload["capabilities"]["search"])
        reopened = DatabaseManager(self.db.db_path)
        self.assertEqual(payload["profile_id"], reopened.profile_id(self.vector_path))
        other_path = self.vector_path.parent / "other-chroma"
        self.assertNotEqual(payload["profile_id"], reopened.profile_id(other_path))

    def test_status_reports_unlabelled_or_mismatched_index_without_changing_health(self):
        self.collection.vector_count = 2
        unlabelled = self.client.get("/api/v1/status").get_json()
        self.assertFalse(unlabelled["ok"])
        self.assertEqual(unlabelled["index"]["state"], "unlabelled")
        self.assertFalse(unlabelled["capabilities"]["search"])
        self.assertFalse(unlabelled["capabilities"]["index_write"])
        self.assertTrue(self.client.get("/api/v1/health").get_json()["ok"])

        self.collection.metadata = {INDEX_MODEL_KEY: "old-model"}
        mismatch = self.client.get("/api/v1/status").get_json()
        self.assertEqual(mismatch["index"]["state"], "model_mismatch")

        self.collection.metadata[INDEX_MODEL_KEY] = "test-model"
        ready = self.client.get("/api/v1/status").get_json()
        self.assertEqual(ready["index"]["state"], "ready")
        self.assertTrue(ready["capabilities"]["search"])

    def test_new_database_gets_different_profile_identity(self):
        other = DatabaseManager(self.db.db_path.parent / "other.db")
        self.assertNotEqual(self.db.profile_id(self.vector_path), other.profile_id(self.vector_path))


if __name__ == "__main__":
    unittest.main()
