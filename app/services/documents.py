"""Document edits with recoverable SQLite and vector-index updates."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.settings import settings
from app.services.source_writeback import SourceWriteConflictError, drain_source_write, prepare_source_write
from engine.memory import build_memory_units, get_content_hash
from engine.retriever import get_memory_unit_payload
from engine.vector_index import write_current_vectors
from engine.vector_outbox import drain_vector_deletions

logger = logging.getLogger(__name__)


class DocumentNotFoundError(LookupError):
    pass


class InvalidDocumentError(ValueError):
    pass


class DocumentConflictError(RuntimeError):
    pass


def save_document(
    sqlite_db: Any,
    vector_db: Any,
    memory_unit_id: str,
    *,
    title: str,
    author: str,
    content: str,
    expected_revision_id: str | None = None,
    expected_edit_version: int | None = None,
    embedder: Any = None,
) -> dict[str, Any]:
    payload = get_memory_unit_payload(sqlite_db, memory_unit_id)
    if payload is None:
        raise DocumentNotFoundError(memory_unit_id)
    if payload["raw_document"]["historical"]:
        raise DocumentConflictError("This detail belongs to an older revision. Reload the current document before editing.")

    original = payload["raw_document"]
    if (expected_revision_id is None) != (expected_edit_version is None):
        raise InvalidDocumentError("Expected revision and edit version must be provided together.")
    if expected_revision_id is not None and not expected_revision_id:
        raise InvalidDocumentError("Expected revision cannot be empty.")
    expected_revision_id = (
        original["latest_revision_id"] if expected_revision_id is None else expected_revision_id
    )
    expected_edit_version = (
        original["edit_version"] if expected_edit_version is None else expected_edit_version
    )
    source_backed = original["source"] == "markdown" and original["source_type"] == "note_file"
    if source_backed:
        if (title or "").strip() != (original.get("title") or "") or (author or "").strip() != (original.get("author") or ""):
            raise InvalidDocumentError("Source-backed Markdown title and author are managed by the file; edit its content only.")
        title = original.get("title") or ""
        author = original.get("author") or ""
        content = content or ""
    else:
        title = (title or "").strip() or "Untitled document"
        author = (author or "").strip() or "unknown"
        content = (content or "").strip()
    if not content.strip():
        raise InvalidDocumentError("Content cannot be empty.")

    source_intent = prepare_source_write(original, content) if source_backed else None

    document = {
        "raw_document_id": original["raw_document_id"],
        "source": original["source"],
        "source_type": original["source_type"],
        "external_id": original["external_id"],
        "root_document_id": original["root_document_id"],
        "sequence": original.get("sequence"),
        "title": title,
        "author": author,
        "created_at": original["created_at"],
        "content": content,
        "content_hash": get_content_hash(content),
        "raw_payload": json.dumps(original.get("raw_payload") or {}, ensure_ascii=False),
        "metadata_json": json.dumps(original.get("metadata") or {}, ensure_ascii=False),
    }
    metadata_changed = title != (original.get("title") or "") or author != (original.get("author") or "")
    protected_rules = sqlite_db.list_protected_terms()
    previous_ids: list[str] = []
    memory_units: list[dict[str, Any]] = []

    with sqlite_db.transaction(immediate=True) as conn:
        current = conn.execute(
            "SELECT latest_revision_id, edit_version, is_active FROM raw_documents WHERE raw_document_id = ?",
            (document["raw_document_id"],),
        ).fetchone()
        if not current or not current["is_active"]:
            raise DocumentNotFoundError(memory_unit_id)
        if (
            current["latest_revision_id"] != expected_revision_id
            or current["edit_version"] != expected_edit_version
        ):
            raise DocumentConflictError("The document changed since it was opened. Reload before saving.")
        if source_backed and conn.execute(
            "SELECT 1 FROM source_write_outbox WHERE raw_document_id = ?",
            (document["raw_document_id"],),
        ).fetchone():
            raise DocumentConflictError("A previous source-file write is still pending; resolve it before editing again.")
        upsert = sqlite_db.upsert_raw_document(document, conn=conn)
        revision_id = upsert["revision_id"]
        reindex = upsert["revision_changed"] or metadata_changed
        if reindex:
            memory_units = build_memory_units(
                document,
                revision_id=revision_id,
                embedding_version=settings.embedding_model,
                protected_rules=protected_rules,
            )
            sqlite_db.insert_memory_units(memory_units, conn=conn)
            previous_revision_id = upsert.get("previous_revision_id")
            if previous_revision_id and previous_revision_id != revision_id:
                previous_ids = sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id, conn=conn)
                sqlite_db.queue_vector_deletions(previous_ids, conn=conn)
            if metadata_changed and not upsert["revision_changed"]:
                conn.execute(
                    "UPDATE raw_document_revisions SET title = ?, author = ? WHERE revision_id = ?",
                    (title, author, revision_id),
                )

        if source_intent and upsert["revision_changed"]:
            conn.execute(
                """
                INSERT INTO source_write_outbox (
                    raw_document_id, root_path, relative_path, expected_content_hash, content
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (document["raw_document_id"], source_intent["root_path"],
                 source_intent["relative_path"], source_intent["expected_content_hash"], content),
            )

        new_edit_version = conn.execute(
            "SELECT edit_version FROM raw_documents WHERE raw_document_id = ?",
            (document["raw_document_id"],),
        ).fetchone()["edit_version"]

    source_status = "not_applicable"
    if source_backed:
        source_status = "ready"
        try:
            drain_source_write(sqlite_db, document["raw_document_id"])
        except Exception:
            logger.exception("Document archived, but Markdown source write is pending: %s", document["raw_document_id"])
            source_status = "pending"

    if not reindex:
        current_units = sqlite_db.get_memory_units_by_raw_document_id(document["raw_document_id"])
        first_id = current_units[0]["memory_unit_id"] if current_units else memory_unit_id
        index_status = (
            "ready" if current_units and all(unit["is_embedded"] for unit in current_units)
            else "pending"
        )
        return {
            "raw_document_id": document["raw_document_id"],
            "memory_unit_id": first_id,
            "revision_changed": False,
            "revision_id": revision_id,
            "edit_version": new_edit_version,
            "index_status": index_status,
            "source_status": source_status,
            "document": {"title": title, "author": author, "content": content},
        }

    new_ids = [unit["memory_unit_id"] for unit in memory_units]
    try:
        if new_ids:
            if embedder is None:
                from engine.embedder import embedding_manager

                embedder = embedding_manager
            embeddings = embedder.embed_documents([unit["content"] for unit in memory_units])
            written = write_current_vectors(
                sqlite_db,
                vector_db,
                ids=new_ids,
                documents=[unit["content"] for unit in memory_units],
                versions=[unit["embedding_version"] for unit in memory_units],
                embeddings=embeddings,
            )
    except Exception:
        logger.exception("Document saved, but its search index is pending: %s", document["raw_document_id"])
        index_status = "pending"
    else:
        index_status = "ready" if new_ids and len(written) == len(new_ids) else "pending"

    try:
        drain_vector_deletions(sqlite_db, vector_db)
    except Exception:
        logger.exception("Old vectors remain queued for cleanup: %s", document["raw_document_id"])

    return {
        "raw_document_id": document["raw_document_id"],
        "memory_unit_id": new_ids[0] if new_ids else memory_unit_id,
        "revision_changed": upsert["revision_changed"],
        "revision_id": revision_id,
        "edit_version": new_edit_version,
        "index_status": index_status,
        "source_status": source_status,
        "document": {"title": title, "author": author, "content": content},
    }
