"""Cross-store recovery checks using temporary SQLite and real Chroma."""

from __future__ import annotations

import json
import io
import gc
import multiprocessing
import tempfile
import unittest
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Barrier, Event, Lock
from time import sleep
from types import SimpleNamespace
from unittest.mock import patch

from engine.database import INDEX_MODEL_KEY, IndexModelError, DatabaseManager, VectorManager
from engine.memory import build_memory_units, build_raw_document
from engine.vector_index import write_current_vectors
from engine.vector_outbox import drain_vector_deletions
from app.core.settings import settings
from app.services.documents import save_document
from scripts import sync_markdown_directory as markdown_sync
from scripts.build_embeddings import build_missing_embeddings
from scripts.import_exports import import_export_file
from scripts.purge_documents_by_created_date import purge_documents_by_created_date
from scripts.purge_source_documents import purge_source_documents
from scripts import repair_chroma_consistency as repair_cli
from scripts.repair_chroma_consistency import audit_consistency


def _process_vector_write(db_path, chroma_path, unit_id, document, version, added, release, results):
    try:
        db = DatabaseManager(db_path)
        vectors = VectorManager(chroma_path)
        original_add = vectors.add_vectors

        def add_and_wait(ids, embeddings, metadatas, documents):
            original_add(ids, embeddings, metadatas, documents)
            added.set()
            if not release.wait(timeout=15):
                raise TimeoutError("writer release timed out")

        vectors.add_vectors = add_and_wait
        written = write_current_vectors(
            db, vectors, ids=[unit_id], documents=[document],
            versions=[version], embeddings=[[1.0, 2.0, 3.0]],
        )
        results.put(("writer", written))
    except Exception as exc:
        results.put(("writer_error", repr(exc)))


def _process_vector_replay(db_path, chroma_path, ready, go, attempted, results):
    try:
        db = DatabaseManager(db_path)
        vectors = VectorManager(chroma_path)
        ready.set()
        if not go.wait(timeout=15):
            raise TimeoutError("replay start timed out")
        attempted.set()
        results.put(("replay", drain_vector_deletions(db, vectors)))
    except Exception as exc:
        results.put(("replay_error", repr(exc)))


class TinyEmbedder:
    def embed_documents(self, texts):
        return [[float(len(text)), 1.0, 2.0] for text in texts]


class IndexRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="selfindex-index-test-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.db = DatabaseManager(self.root / "archive.db")
        self.vectors = VectorManager(self.root / "chroma")
        self.embedder = TinyEmbedder()

    def _seed_markdown(self, names=("a.md",)):
        source = self.root / "notes"
        source.mkdir()
        for name in names:
            (source / name).write_text("Original " + name, encoding="utf-8")
        markdown_sync.sync_markdown_directory(source, sqlite_db=self.db, vector_db=self.vectors)
        build_missing_embeddings(
            sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
        )
        return source

    def _seed_note(self):
        document = build_raw_document(
            source="test", source_type="note", external_id="one",
            root_document_id="notes", title="Note", author="Author",
            created_at="2026-09-01T12:00:00", content="Synthetic note",
            raw_payload={}, metadata={},
        )
        revision = self.db.upsert_raw_document(document)
        units = build_memory_units(
            document, revision_id=revision["revision_id"],
            embedding_version=settings.embedding_model,
        )
        self.db.insert_memory_units(units)
        build_missing_embeddings(
            sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
        )
        return document, units[0]["memory_unit_id"]

    def test_failed_sync_transaction_preserves_previous_real_vector(self):
        source = self._seed_markdown(("a.md", "b.md"))
        old_id = self.db.get_memory_units_by_raw_document_id(
            "markdown:note_file:a.md"
        )[0]["memory_unit_id"]
        (source / "a.md").write_text("Changed a", encoding="utf-8")
        original_builder = markdown_sync._build_markdown_raw_document

        def fail_second(root, path):
            if path.name == "b.md":
                raise RuntimeError("synthetic read failure")
            return original_builder(root, path)

        with patch.object(markdown_sync, "_build_markdown_raw_document", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "synthetic read failure"):
                markdown_sync.sync_markdown_directory(
                    source, sqlite_db=self.db, vector_db=self.vectors,
                )

        self.assertEqual(
            self.db.get_raw_document("markdown:note_file:a.md")["content"], "Original a.md",
        )
        self.assertEqual(self.vectors.collection.get(ids=[old_id], include=[])["ids"], [old_id])

    def test_committed_sync_rebuilds_after_vector_cleanup_failure(self):
        source = self._seed_markdown()
        raw_id = "markdown:note_file:a.md"
        old_id = self.db.get_memory_units_by_raw_document_id(raw_id)[0]["memory_unit_id"]
        (source / "a.md").write_text("Changed a", encoding="utf-8")
        old_delete = self.vectors.delete_vectors

        def fail_after_delete(ids):
            old_delete(ids)
            raise RuntimeError("synthetic cleanup failure")

        with patch.object(self.vectors, "delete_vectors", side_effect=fail_after_delete):
            with self.assertRaisesRegex(RuntimeError, "archive was committed"):
                markdown_sync.sync_markdown_directory(
                    source, sqlite_db=self.db, vector_db=self.vectors,
                )

        self.assertEqual(self.db.get_raw_document(raw_id)["content"], "Changed a")
        self.assertEqual(self.vectors.collection.get(ids=[old_id], include=[])["ids"], [])
        self.assertEqual(len(self.db.get_memory_units_needing_embeddings()), 1)
        self.assertEqual(self.db.count_pending_vector_deletions(), 1)
        self.assertEqual(
            build_missing_embeddings(
                sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
            ),
            {"processed": 1, "has_remaining": 0},
        )
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["missing_vector_ids"], [])
        self.assertEqual(report["orphan_vector_ids"], [])
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)

    def test_committed_cleanup_intent_survives_reopen(self):
        source = self._seed_markdown()
        old_id = self.db.get_memory_units_by_raw_document_id("markdown:note_file:a.md")[0]["memory_unit_id"]
        (source / "a.md").write_text("Changed a", encoding="utf-8")

        with patch.object(markdown_sync, "drain_vector_deletions", side_effect=RuntimeError("synthetic crash")):
            with self.assertRaisesRegex(RuntimeError, "archive was committed"):
                markdown_sync.sync_markdown_directory(source, sqlite_db=self.db, vector_db=self.vectors)

        self.assertEqual(self.db.count_pending_vector_deletions(), 1)
        self.assertEqual(self.vectors.collection.get(ids=[old_id], include=[])["ids"], [old_id])
        reopened_db = DatabaseManager(self.root / "archive.db")
        reopened_vectors = VectorManager(self.root / "chroma")
        self.assertEqual(drain_vector_deletions(reopened_db, reopened_vectors)["delete_requested"], 1)
        self.assertEqual(reopened_db.count_pending_vector_deletions(), 0)
        self.assertEqual(reopened_vectors.collection.get(ids=[old_id], include=[])["ids"], [])
        build_missing_embeddings(
            sqlite_db=reopened_db, vector_db=reopened_vectors, embedder=self.embedder,
        )
        report = audit_consistency(sqlite_db=reopened_db, vector_db=reopened_vectors, batch_size=10)
        self.assertEqual(report["missing_vector_ids"], [])
        self.assertEqual(report["orphan_vector_ids"], [])

    def test_replay_keeps_id_that_is_current_again(self):
        _document, current_id = self._seed_note()
        with self.db.transaction() as conn:
            self.db.queue_vector_deletions([current_id], conn=conn)

        result = drain_vector_deletions(self.db, self.vectors)
        self.assertEqual(result, {"processed": 1, "delete_requested": 0})
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)
        self.assertEqual(self.vectors.collection.get(ids=[current_id], include=[])["ids"], [current_id])

    def test_replay_workers_serialize_same_delete(self):
        with self.db.transaction() as conn:
            self.db.queue_vector_deletions(["stale-unit"], conn=conn)

        barrier = Barrier(2)
        calls = []
        calls_lock = Lock()

        class SlowVectors:
            def delete_vectors(self, ids):
                with calls_lock:
                    calls.append(list(ids))
                sleep(0.1)

        def replay():
            barrier.wait(timeout=5)
            return drain_vector_deletions(self.db, SlowVectors())

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=10) for future in (pool.submit(replay), pool.submit(replay))]

        self.assertEqual(sum(result["delete_requested"] for result in results), 1)
        self.assertEqual(calls, [["stale-unit"]])
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)

    def test_vector_write_and_delete_replay_share_sql_writer_lock(self):
        _document, current_id = self._seed_note()
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (current_id,))
            self.db.queue_vector_deletions(["stale-unit"], conn=conn)

        add_started = Event()
        resume_add = Event()
        replay_attempted = Event()
        delete_started = Event()
        calls = []

        class BlockingVectors:
            def delete_vectors(self, ids):
                calls.append(("delete", tuple(ids)))
                if "stale-unit" in ids:
                    delete_started.set()

            def add_vectors(self, ids, embeddings, metadatas, documents):
                add_started.set()
                if not resume_add.wait(timeout=10):
                    raise TimeoutError("synthetic vector write wait timed out")
                calls.append(("add", tuple(ids)))

        vectors = BlockingVectors()
        unit = self.db.get_memory_unit(current_id)

        def replay():
            replay_attempted.set()
            return drain_vector_deletions(self.db, vectors)

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(
                write_current_vectors, self.db, vectors,
                ids=[current_id], documents=[unit["content"]],
                versions=[unit["embedding_version"]], embeddings=[[1.0, 2.0, 3.0]],
            )
            self.assertTrue(add_started.wait(timeout=10))
            replayer = pool.submit(replay)
            try:
                self.assertTrue(replay_attempted.wait(timeout=10))
                self.assertFalse(delete_started.wait(timeout=0.1))
            finally:
                resume_add.set()
            self.assertEqual(writer.result(timeout=10), [current_id])
            self.assertEqual(replayer.result(timeout=10)["delete_requested"], 1)

        self.assertLess(calls.index(("add", (current_id,))), calls.index(("delete", ("stale-unit",))))
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)

    def test_vector_write_failure_before_sql_mark_is_rebuildable(self):
        _document, unit_id = self._seed_note()
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (unit_id,))

        def fail_mark(ids, *, conn=None):
            raise RuntimeError("synthetic SQL mark failure")

        with patch.object(self.db, "mark_memory_units_as_embedded", side_effect=fail_mark):
            with self.assertRaisesRegex(RuntimeError, "synthetic SQL mark failure"):
                build_missing_embeddings(
                    sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
                )

        self.assertEqual(self.db.get_memory_unit(unit_id)["is_embedded"], 0)
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [unit_id])
        self.assertEqual(
            build_missing_embeddings(sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder),
            {"processed": 1, "has_remaining": 0},
        )
        self.assertEqual(self.vectors.collection.count(), 1)

    def test_vector_write_rejects_changed_model_version(self):
        _document, unit_id = self._seed_note()
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (unit_id,))
        unit = self.db.get_memory_unit(unit_id)

        written = write_current_vectors(
            self.db, self.vectors, ids=[unit_id], documents=[unit["content"]],
            versions=["synthetic-old-model"], embeddings=[[1.0, 2.0, 3.0]],
        )
        self.assertEqual(written, [])
        self.assertEqual(self.db.get_memory_unit(unit_id)["is_embedded"], 0)

    def test_manifest_blocks_changed_configured_model(self):
        _document, unit_id = self._seed_note()
        self.assertEqual(
            VectorManager(self.root / "chroma").collection.metadata[INDEX_MODEL_KEY],
            settings.embedding_model,
        )
        changed_settings = replace(settings, embedding_model="synthetic-other-model")
        with patch("engine.database.settings", changed_settings), patch(
            "engine.vector_index.settings", changed_settings
        ):
            with self.assertRaises(IndexModelError):
                self.vectors.search([1.0, 2.0, 3.0])
            with self.db.transaction() as conn:
                conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (unit_id,))
            unit = self.db.get_memory_unit(unit_id)
            with self.assertRaises(IndexModelError):
                write_current_vectors(
                    self.db, self.vectors, ids=[unit_id], documents=[unit["content"]],
                    versions=[unit["embedding_version"]], embeddings=[[1.0, 2.0, 3.0]],
                )
        self.assertEqual(self.db.get_memory_unit(unit_id)["is_embedded"], 0)

    def test_unlabelled_index_requires_clean_explicit_adoption(self):
        _document, unit_id = self._seed_note()
        self.vectors.collection.modify(metadata={"legacy": "yes"})
        with self.assertRaises(IndexModelError):
            self.vectors.search([1.0, 2.0, 3.0])
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertIsNone(report["index_model"])
        test_settings = SimpleNamespace(
            sqlite_db_path=self.root / "archive.db", chroma_db_path=self.root / "chroma",
            embedding_model=settings.embedding_model,
        )
        with patch.object(repair_cli, "settings", test_settings), patch(
            "sys.argv", ["repair_chroma_consistency", "--adopt-index-model", settings.embedding_model,
                         "--confirm-offline-adoption"],
        ), redirect_stdout(io.StringIO()):
            repair_cli.main()
        self.assertEqual(
            VectorManager(self.root / "chroma").collection.metadata[INDEX_MODEL_KEY],
            settings.embedding_model,
        )
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [unit_id])
        distance = self.vectors.collection.query(
            query_embeddings=[[float(len("Synthetic note")) * 10, 10.0, 20.0]],
            n_results=1, include=["distances"],
        )["distances"][0][0]
        self.assertAlmostEqual(distance, 0.0, places=5)

    def test_adoption_rejects_content_drift(self):
        _document, unit_id = self._seed_note()
        self.vectors.collection.modify(metadata={"legacy": "yes"})
        self.vectors.collection.update(
            ids=[unit_id], documents=["wrong content"], embeddings=[[1.0, 2.0, 3.0]],
        )
        test_settings = SimpleNamespace(
            sqlite_db_path=self.root / "archive.db", chroma_db_path=self.root / "chroma",
            embedding_model=settings.embedding_model,
        )
        with patch.object(repair_cli, "settings", test_settings), patch(
            "sys.argv", ["repair_chroma_consistency", "--adopt-index-model", settings.embedding_model,
                         "--confirm-offline-adoption"],
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            repair_cli.main()
        self.assertNotIn(INDEX_MODEL_KEY, VectorManager(self.root / "chroma").collection.metadata)

    def test_audit_detects_document_and_metadata_drift_without_writes(self):
        _document, unit_id = self._seed_note()
        self.vectors.collection.update(
            ids=[unit_id], documents=["stale content"], metadatas=[{"source": "wrong"}],
            embeddings=[[1.0, 2.0, 3.0]],
        )
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["content_mismatch_ids"], [unit_id])
        self.assertEqual(report["metadata_mismatch_ids"], [unit_id])
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=["documents"])["documents"], ["stale content"])
        read_only = repair_cli.ReadOnlyDatabase(self.root / "archive.db")
        with read_only.get_connection() as conn:
            with self.assertRaises(Exception):
                conn.execute("DELETE FROM memory_units")

    def test_explicit_offline_metadata_repair_preserves_embedding(self):
        _document, unit_id = self._seed_note()
        before = self.vectors.collection.get(ids=[unit_id], include=["embeddings"])
        self.vectors.collection.update(ids=[unit_id], metadatas=[{"source": "old"}])
        test_settings = SimpleNamespace(
            sqlite_db_path=self.root / "archive.db", chroma_db_path=self.root / "chroma",
            embedding_model=settings.embedding_model,
        )
        with patch.object(repair_cli, "settings", test_settings), patch(
            "sys.argv", ["repair_chroma_consistency", "--repair-metadata"],
        ), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            repair_cli.main()
        with patch.object(repair_cli, "settings", test_settings), patch(
            "sys.argv", ["repair_chroma_consistency", "--repair-metadata", "--confirm-offline-repair"],
        ), redirect_stdout(io.StringIO()):
            repair_cli.main()
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["metadata_mismatch_ids"], [])
        after = self.vectors.collection.get(ids=[unit_id], include=["embeddings"])
        self.assertEqual(before["embeddings"].tolist(), after["embeddings"].tolist())

    def test_write_and_replay_require_single_writer_across_processes(self):
        _document, unit_id = self._seed_note()
        self.vectors.collection.add(
            ids=["stale-unit"], embeddings=[[2.0, 2.0, 3.0]],
            documents=["stale"], metadatas=[{"source": "test"}],
        )
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (unit_id,))
            self.db.queue_vector_deletions(["stale-unit"], conn=conn)
        unit = self.db.get_memory_unit(unit_id)
        db_path = self.db.db_path
        chroma_path = self.vectors.persist_directory
        self.db = None
        gc.collect()
        ctx = multiprocessing.get_context("spawn")
        added, release, ready, go, attempted = (
            ctx.Event(), ctx.Event(), ctx.Event(), ctx.Event(), ctx.Event()
        )
        results = ctx.Queue()
        writer = ctx.Process(
            target=_process_vector_write,
            args=(db_path, chroma_path, unit_id,
                  unit["content"], unit["embedding_version"], added, release, results),
        )
        replay = ctx.Process(
            target=_process_vector_replay,
            args=(db_path, chroma_path, ready, go, attempted, results),
        )
        recovered = None
        try:
            writer.start()
            self.assertTrue(added.wait(timeout=15))
            replay.start()
            replay.join(timeout=15)
            self.assertEqual(replay.exitcode, 0)
            self.assertFalse(ready.is_set())
            self.assertIn("ProfileWriterBusyError", dict(results.get(timeout=5) for _ in range(1))["replay_error"])
            release.set()
            writer.join(timeout=15)
            self.assertEqual(writer.exitcode, 0)
            self.assertEqual(dict(results.get(timeout=5) for _ in range(1))["writer"], [unit_id])
            recovered = ctx.Process(
                target=_process_vector_replay,
                args=(db_path, chroma_path, ready, go, attempted, results),
            )
            go.set()
            recovered.start()
            recovered.join(timeout=15)
            self.assertEqual(recovered.exitcode, 0)
            self.assertTrue(ready.is_set())
            self.assertTrue(attempted.is_set())
        finally:
            release.set()
            go.set()
            for process in (writer, replay, recovered):
                if process is None:
                    continue
                if process.pid:
                    process.join(timeout=15)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=5)
        self.assertEqual(dict(results.get(timeout=5) for _ in range(1))["replay"], {"processed": 1, "delete_requested": 1})
        self.assertEqual(self.vectors.collection.get(include=[])["ids"], [unit_id])
        self.db = DatabaseManager(db_path)
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)

    def test_repair_cli_orphan_delete_replays_outbox(self):
        _document, unit_id = self._seed_note()
        purge_source_documents(
            self.db, source="test", source_type="note", vector_db=None,
        )
        self.assertEqual(self.db.count_pending_vector_deletions(), 1)
        test_settings = SimpleNamespace(
            sqlite_db_path=self.root / "archive.db",
            chroma_db_path=self.root / "chroma",
        )
        with patch.object(repair_cli, "settings", test_settings), patch(
            "sys.argv", ["repair_chroma_consistency", "--delete-orphans"]
        ), redirect_stdout(io.StringIO()):
            repair_cli.main()

        self.assertEqual(self.db.count_pending_vector_deletions(), 0)
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [])

    def test_rebuild_replaces_existing_chroma_id(self):
        self._seed_markdown()
        unit = self.db.get_memory_units_by_raw_document_id("markdown:note_file:a.md")[0]
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (unit["memory_unit_id"],))

        build_missing_embeddings(
            sqlite_db=self.db, vector_db=self.vectors, embedder=self.embedder,
        )
        self.assertEqual(self.vectors.collection.count(), 1)
        self.assertEqual(
            self.vectors.collection.get(ids=[unit["memory_unit_id"]], include=["documents"])["documents"],
            [unit["content"]],
        )

    def test_old_edit_embedding_cannot_restore_historical_vector(self):
        _document, old_id = self._seed_note()
        embedding_started = Event()
        resume_embedding = Event()

        class SlowEmbedder:
            def embed_documents(self, texts):
                embedding_started.set()
                if not resume_embedding.wait(timeout=10):
                    raise TimeoutError("synthetic embedding wait timed out")
                return TinyEmbedder().embed_documents(texts)

        with ThreadPoolExecutor(max_workers=1) as pool:
            older = pool.submit(
                save_document, self.db, self.vectors, old_id,
                title="Note", author="Author", content="Second note",
                embedder=SlowEmbedder(),
            )
            self.assertTrue(embedding_started.wait(timeout=10))
            try:
                middle_id = self.db.get_memory_units_by_raw_document_id(
                    "test:note:one"
                )[0]["memory_unit_id"]
                latest = save_document(
                    self.db, self.vectors, middle_id,
                    title="Note", author="Author", content="Third note",
                    embedder=self.embedder,
                )
            finally:
                resume_embedding.set()
            older_result = older.result(timeout=10)

        self.assertEqual(older_result["index_status"], "pending")
        self.assertEqual(latest["index_status"], "ready")
        self.assertEqual(self.vectors.collection.get(include=[])["ids"], [latest["memory_unit_id"]])
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["orphan_vector_ids"], [])
        self.assertEqual(report["missing_vector_ids"], [])

    def test_old_rebuild_cannot_restore_historical_vector(self):
        _document, old_id = self._seed_note()
        with self.db.transaction() as conn:
            conn.execute("UPDATE memory_units SET is_embedded = 0 WHERE memory_unit_id = ?", (old_id,))
        embedding_started = Event()
        resume_embedding = Event()

        class SlowEmbedder:
            def embed_documents(self, texts):
                embedding_started.set()
                if not resume_embedding.wait(timeout=10):
                    raise TimeoutError("synthetic embedding wait timed out")
                return TinyEmbedder().embed_documents(texts)

        with ThreadPoolExecutor(max_workers=1) as pool:
            older = pool.submit(
                build_missing_embeddings,
                sqlite_db=self.db, vector_db=self.vectors, embedder=SlowEmbedder(),
            )
            self.assertTrue(embedding_started.wait(timeout=10))
            try:
                latest = save_document(
                    self.db, self.vectors, old_id,
                    title="Note", author="Author", content="Changed note",
                    embedder=self.embedder,
                )
            finally:
                resume_embedding.set()
            older_result = older.result(timeout=10)

        self.assertEqual(older_result["processed"], 0)
        self.assertEqual(latest["index_status"], "ready")
        self.assertEqual(self.vectors.collection.get(include=[])["ids"], [latest["memory_unit_id"]])

    def test_old_import_embedding_cannot_restore_historical_vector(self):
        export_path = self.root / "chatgpt_export.json"
        conversation = [{
            "id": "conv-1", "title": "Test", "create_time": "2026-09-01T12:00:00",
            "mapping": {"node-1": {"message": {
                "id": "msg-1", "author": {"role": "user"},
                "content": {"parts": ["First content"]},
                "create_time": "2026-09-01T12:01:00",
            }}},
        }]
        export_path.write_text(json.dumps(conversation), encoding="utf-8")
        embedding_started = Event()
        resume_embedding = Event()

        class SlowEmbedder:
            def embed_documents(self, texts):
                embedding_started.set()
                if not resume_embedding.wait(timeout=10):
                    raise TimeoutError("synthetic embedding wait timed out")
                return TinyEmbedder().embed_documents(texts)

        with ThreadPoolExecutor(max_workers=1) as pool:
            older = pool.submit(
                import_export_file, export_path,
                sqlite_db=self.db, vector_db=self.vectors, embedder=SlowEmbedder(),
            )
            self.assertTrue(embedding_started.wait(timeout=10))
            try:
                conversation[0]["mapping"]["node-1"]["message"]["content"]["parts"] = ["Updated content"]
                export_path.write_text(json.dumps(conversation), encoding="utf-8")
                latest = import_export_file(
                    export_path, sqlite_db=self.db, vector_db=self.vectors,
                    embedder=self.embedder,
                )
            finally:
                resume_embedding.set()
            older_result = older.result(timeout=10)

        self.assertEqual(older_result["index_status"], "pending")
        self.assertEqual(latest["index_status"], "ready")
        self.assertEqual(self.vectors.collection.count(), 1)
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["orphan_vector_ids"], [])
        self.assertEqual(report["missing_vector_ids"], [])

    def test_purge_sql_failure_preserves_real_vector(self):
        document, unit_id = self._seed_note()
        for purge in (purge_source_documents, purge_documents_by_created_date):
            arguments = {"source": "test", "source_type": "note", "vector_db": self.vectors}
            if purge is purge_documents_by_created_date:
                arguments["created_date"] = "2026-09-01"
            with patch.object(self.db, "transaction", side_effect=RuntimeError("synthetic SQL failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic SQL failure"):
                    purge(self.db, **arguments)
            self.assertIsNotNone(self.db.get_raw_document(document["raw_document_id"]))
            self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [unit_id])

    def test_purge_sql_rollback_discards_queued_delete(self):
        document, unit_id = self._seed_note()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                CREATE TRIGGER reject_note_delete BEFORE DELETE ON raw_documents
                BEGIN SELECT RAISE(ABORT, 'synthetic SQL failure'); END
                """
            )
        with self.assertRaisesRegex(Exception, "synthetic SQL failure"):
            purge_source_documents(
                self.db, source="test", source_type="note", vector_db=self.vectors,
            )
        self.assertIsNotNone(self.db.get_raw_document(document["raw_document_id"]))
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [unit_id])
        self.assertEqual(self.db.count_pending_vector_deletions(), 0)

    def test_purge_vector_failure_reports_committed_archive_deletion(self):
        document, unit_id = self._seed_note()
        with patch.object(self.vectors, "delete_vectors", side_effect=RuntimeError("synthetic vector failure")):
            with self.assertRaisesRegex(RuntimeError, "Archive deletion committed"):
                purge_source_documents(
                    self.db, source="test", source_type="note", vector_db=self.vectors,
                )
        self.assertIsNone(self.db.get_raw_document(document["raw_document_id"]))
        self.assertEqual(self.vectors.collection.get(ids=[unit_id], include=[])["ids"], [unit_id])
        self.assertEqual(self.db.count_pending_vector_deletions(), 1)
        report = audit_consistency(sqlite_db=self.db, vector_db=self.vectors, batch_size=10)
        self.assertEqual(report["orphan_vector_ids"], [unit_id])


if __name__ == "__main__":
    unittest.main()
