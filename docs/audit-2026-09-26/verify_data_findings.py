"""Audit observations using temporary databases/files and fake embeddings only.

Outputs reflect current behavior, including repaired findings. Never point these
fixtures at a user's data directory.
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.settings import settings
from app.services.documents import save_document
from engine.database import DatabaseManager
from engine.memory import build_memory_units, build_raw_document
from scripts.sync_markdown_directory import sync_markdown_directory


class Vectors:
    def __init__(self):
        self.records = {}
        self.fail_after_delete = False

    def add_vectors(self, ids, embeddings, metadatas, documents):
        self.records.update(zip(ids, documents))

    def delete_vectors(self, ids):
        for identity in ids:
            self.records.pop(identity, None)
        if self.fail_after_delete:
            raise RuntimeError("synthetic vector deletion failure")


class Embedder:
    def embed_documents(self, texts):
        return [[1.0] for _ in texts]


class BrokenEmbedder:
    def embed_documents(self, texts):
        raise RuntimeError("synthetic model failure")


def make_document(content="Original", root="notes"):
    return build_raw_document(
        source="markdown", source_type="note_file", external_id="same.md",
        root_document_id=root, title="Same", author="Author", created_at=None,
        content=content, raw_payload={}, metadata={},
    )


def seed(db, vectors):
    document = make_document()
    revision = db.upsert_raw_document(document)
    units = build_memory_units(
        document, revision_id=revision["revision_id"],
        embedding_version=settings.embedding_model,
    )
    db.insert_memory_units(units)
    ids = [unit["memory_unit_id"] for unit in units]
    vectors.add_vectors(ids, [[1.0]] * len(ids), [{}] * len(ids), [u["content"] for u in units])
    db.mark_memory_units_as_embedded(ids)
    return document, ids[0]


def emit(finding, **observed):
    print(json.dumps({"finding": finding, "observed": observed}, ensure_ascii=True))


def run():
    first = make_document(root="/synthetic/root-a")
    second = make_document(root="/synthetic/root-b")
    emit("DATA-01", different_roots_same_document_id=first["raw_document_id"] == second["raw_document_id"])

    with tempfile.TemporaryDirectory(prefix="selfindex-audit-") as directory:
        base = Path(directory)
        root = base / "notes"
        root.mkdir()
        note = root / "note.md"
        note.write_text("Original", encoding="utf-8")
        db = DatabaseManager(base / "sync.db")
        vectors = Vectors()
        sync_markdown_directory(root, sqlite_db=db, vector_db=vectors)
        rows = db.get_memory_units_needing_embeddings()
        identity = rows[0]["memory_unit_id"]
        raw_id = rows[0]["raw_document_id"]
        vectors.records[identity] = "Original"
        db.mark_memory_units_as_embedded([identity])
        note.write_text("Changed", encoding="utf-8")
        vectors.fail_after_delete = True
        try:
            sync_markdown_directory(root, sqlite_db=db, vector_db=vectors)
        except RuntimeError:
            pass
        emit("DATA-03", archive_committed=db.get_raw_document(raw_id)["content"] == "Changed",
             old_vector_missing=identity not in vectors.records,
             pending_units=len(db.get_memory_units_needing_embeddings()))
        vectors.fail_after_delete = False
        note.unlink()
        root.rmdir()
        missing_root_rejected = False
        try:
            sync_markdown_directory(root, sqlite_db=db, vector_db=vectors)
        except FileNotFoundError:
            missing_root_rejected = True
        emit("DATA-02", root_exists=root.exists(), missing_root_rejected=missing_root_rejected,
             document_still_active=bool(db.get_raw_document(raw_id)["is_active"]))

        db = DatabaseManager(base / "edits.db")
        vectors = Vectors()
        document, identity = seed(db, vectors)
        logger = logging.getLogger("app.services.documents")
        disabled = logger.disabled
        logger.disabled = True
        try:
            failed = save_document(db, vectors, identity, title="Same", author="Author",
                                   content="New", embedder=BrokenEmbedder())
        finally:
            logger.disabled = disabled
        repeated = save_document(db, vectors, failed["memory_unit_id"], title="Same", author="Author",
                                 content="New", embedder=Embedder())
        emit("DATA-04", first_status=failed["index_status"], repeated_status=repeated["index_status"],
             pending_units=len(db.get_memory_units_needing_embeddings()))
        save_document(db, vectors, identity, title="Same", author="Author",
                      content="Client A", embedder=Embedder())
        overwritten = save_document(db, vectors, identity, title="Same", author="Author",
                                    content="Client B stale draft", embedder=Embedder())
        emit("DATA-05", stale_id_accepted=overwritten["index_status"] == "ready",
             latest_is_stale_client_draft=db.get_raw_document(document["raw_document_id"])["content"] == "Client B stale draft")

        db = DatabaseManager(base / "revisions.db")
        for content in ("A", "B", "A"):
            db.upsert_raw_document(make_document(content))
        emit("DATA-06", transitions=3, stored_revision_rows=db.count_rows("raw_document_revisions"))


if __name__ == "__main__":
    run()
