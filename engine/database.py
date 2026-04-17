"""SQLite and vector database access for the current SelfIndex memory pipeline."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.settings import settings
from engine.init_db import init_database
from engine.memory import build_raw_document_revision, get_revision_id
from engine.protected_terms import decode_term, encode_term
from engine.sqlite_backend import connect_database


class VectorManager:
    """Thin wrapper around the Chroma collection used by SelfIndex."""

    def __init__(self, persist_directory: str | Path) -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        try:
            import chromadb
        except Exception as exc:  # pragma: no cover - depends on local runtime
            raise RuntimeError("VectorManager requires a working chromadb installation.") from exc
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.collection = self.client.get_or_create_collection(
            name="my_knowledge_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add_vectors(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
        documents: list[str],
    ) -> None:
        if not ids:
            return
        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

    def get_vectors(self, ids: list[str]) -> dict[str, Any]:
        if not ids:
            return {"ids": [], "embeddings": [], "metadatas": [], "documents": []}
        return self.collection.get(
            ids=ids,
            include=["embeddings", "metadatas", "documents"],
        )

    def delete_vectors(self, ids: list[str]) -> None:
        if ids:
            self.collection.delete(ids=ids)

    def search(self, query_vector: list[float], n_results: int = 5) -> dict[str, Any]:
        return self.collection.query(
            query_embeddings=[query_vector],
            n_results=n_results,
            include=["distances", "documents", "metadatas"],
        )


class DatabaseManager:
    """Central access layer for the current archive + memory schema."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        init_database(self.db_path)
        if settings.protected_terms:
            self.seed_protected_terms(settings.protected_terms)

    def get_connection(self):
        return connect_database(self.db_path)

    @contextmanager
    def transaction(self):
        conn = self.get_connection()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count_rows(self, table_name: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"]) if row else 0

    def seed_protected_terms(
        self,
        terms: list[str],
        *,
        domain: str = "sensitive",
        encoding: str = "base64",
        conn=None,
    ) -> int:
        normalized_terms = [term.strip() for term in terms if term and term.strip()]
        if not normalized_terms:
            return 0

        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            conn.executemany(
                """
                INSERT OR IGNORE INTO protected_terms (
                    term_encoded,
                    encoding,
                    domain,
                    is_active
                ) VALUES (?, ?, ?, 1)
                """,
                [(encode_term(term, encoding), encoding, domain) for term in normalized_terms],
            )
            changed = int(conn.total_changes)
            if owns_connection:
                conn.commit()
            return changed
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def list_protected_terms(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            if active_only:
                rows = conn.execute(
                    """
                    SELECT term_id, term_encoded, encoding, domain, is_active, notes,
                           created_at, updated_at
                    FROM protected_terms
                    WHERE is_active = 1
                    ORDER BY term_id
                    """
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT term_id, term_encoded, encoding, domain, is_active, notes,
                           created_at, updated_at
                    FROM protected_terms
                    ORDER BY term_id
                    """
                ).fetchall()

        decoded_rows: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["term"] = decode_term(item["term_encoded"], item["encoding"])
            decoded_rows.append(item)
        return decoded_rows

    def upsert_raw_document(self, raw_document: dict[str, Any], *, conn=None) -> dict[str, Any]:
        """Store the latest document state and append a revision when content changes."""
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            existing = conn.execute(
                """
                SELECT raw_document_id, latest_revision_id, current_content_hash
                FROM raw_documents
                WHERE raw_document_id = ?
                """,
                (raw_document["raw_document_id"],),
            ).fetchone()

            revision_id = get_revision_id(raw_document["raw_document_id"], raw_document["content_hash"])
            previous_revision_id = existing.get("latest_revision_id") if existing else None
            revision_changed = existing is None or (
                existing.get("current_content_hash") != raw_document["content_hash"]
            )

            conn.execute(
                """
                INSERT INTO raw_documents (
                    raw_document_id,
                    source,
                    source_type,
                    external_id,
                    root_document_id,
                    sequence,
                    title,
                    author,
                    created_at,
                    content,
                    content_hash,
                    current_content_hash,
                    latest_revision_id,
                    is_active,
                    raw_payload,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_document_id) DO UPDATE SET
                    source = excluded.source,
                    source_type = excluded.source_type,
                    external_id = excluded.external_id,
                    root_document_id = excluded.root_document_id,
                    sequence = excluded.sequence,
                    title = excluded.title,
                    author = excluded.author,
                    created_at = excluded.created_at,
                    imported_at = CURRENT_TIMESTAMP,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    current_content_hash = excluded.current_content_hash,
                    latest_revision_id = excluded.latest_revision_id,
                    is_active = excluded.is_active,
                    raw_payload = excluded.raw_payload,
                    metadata_json = excluded.metadata_json
                """,
                (
                    raw_document["raw_document_id"],
                    raw_document["source"],
                    raw_document["source_type"],
                    raw_document["external_id"],
                    raw_document.get("root_document_id"),
                    raw_document.get("sequence"),
                    raw_document.get("title"),
                    raw_document.get("author"),
                    raw_document.get("created_at"),
                    raw_document["content"],
                    raw_document["content_hash"],
                    raw_document["content_hash"],
                    revision_id,
                    1,
                    raw_document.get("raw_payload"),
                    raw_document.get("metadata_json"),
                ),
            )

            if revision_changed:
                if previous_revision_id:
                    conn.execute(
                        """
                        UPDATE raw_document_revisions
                        SET is_current = 0
                        WHERE raw_document_id = ?
                        """,
                        (raw_document["raw_document_id"],),
                    )
                revision = build_raw_document_revision(
                    raw_document,
                    change_type="created" if existing is None else "updated",
                    is_current=1,
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO raw_document_revisions (
                        revision_id,
                        raw_document_id,
                        content,
                        content_hash,
                        title,
                        author,
                        created_at,
                        raw_payload,
                        metadata_json,
                        change_type,
                        is_current
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        revision["revision_id"],
                        revision["raw_document_id"],
                        revision["content"],
                        revision["content_hash"],
                        revision.get("title"),
                        revision.get("author"),
                        revision.get("created_at"),
                        revision.get("raw_payload"),
                        revision.get("metadata_json"),
                        revision["change_type"],
                        revision["is_current"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO raw_document_revisions (
                        revision_id,
                        raw_document_id,
                        content,
                        content_hash,
                        title,
                        author,
                        created_at,
                        raw_payload,
                        metadata_json,
                        change_type,
                        is_current
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'updated', 1)
                    """,
                    (
                        revision_id,
                        raw_document["raw_document_id"],
                        raw_document["content"],
                        raw_document["content_hash"],
                        raw_document.get("title"),
                        raw_document.get("author"),
                        raw_document.get("created_at"),
                        raw_document.get("raw_payload"),
                        raw_document.get("metadata_json"),
                    ),
                )
                conn.execute(
                    """
                    UPDATE raw_document_revisions
                    SET is_current = CASE WHEN revision_id = ? THEN 1 ELSE 0 END
                    WHERE raw_document_id = ?
                    """,
                    (revision_id, raw_document["raw_document_id"]),
                )

            if owns_connection:
                conn.commit()
            return {
                "revision_id": revision_id,
                "revision_changed": revision_changed,
                "previous_revision_id": previous_revision_id,
            }
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def insert_memory_units(self, memory_units: list[dict[str, Any]], *, conn=None) -> None:
        if not memory_units:
            return
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            conn.executemany(
                """
                INSERT OR REPLACE INTO memory_units (
                    memory_unit_id,
                    revision_id,
                    raw_document_id,
                    unit_index,
                    unit_type,
                    recall_domain,
                    content,
                    summary,
                    start_char,
                    end_char,
                    embedding_version,
                    metadata_json,
                    is_embedded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        unit["memory_unit_id"],
                        unit["revision_id"],
                        unit["raw_document_id"],
                        unit["unit_index"],
                        unit["unit_type"],
                        unit.get("recall_domain") or "default",
                        unit["content"],
                        unit.get("summary"),
                        unit["start_char"],
                        unit["end_char"],
                        unit.get("embedding_version"),
                        unit.get("metadata_json"),
                        unit.get("is_embedded", 0),
                    )
                    for unit in memory_units
                ],
            )
            if owns_connection:
                conn.commit()
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def replace_memory_units(
        self,
        raw_document_id: str,
        memory_units: list[dict[str, Any]],
        *,
        conn=None,
    ) -> list[str]:
        """Compatibility helper for callers that still expect a current-only replace."""
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            row = conn.execute(
                """
                SELECT latest_revision_id, current_content_hash
                FROM raw_documents
                WHERE raw_document_id = ?
                """,
                (raw_document_id,),
            ).fetchone()
            revision_id = None
            if row:
                revision_id = row.get("latest_revision_id")
                if not revision_id and row.get("current_content_hash"):
                    revision_id = get_revision_id(raw_document_id, row["current_content_hash"])

            old_ids = self.get_memory_units_by_raw_document_id(raw_document_id)
            old_memory_unit_ids = [item["memory_unit_id"] for item in old_ids]
            if revision_id:
                conn.execute(
                    "DELETE FROM memory_units WHERE revision_id = ?",
                    (revision_id,),
                )
            else:
                conn.execute(
                    "DELETE FROM memory_units WHERE raw_document_id = ?",
                    (raw_document_id,),
                )

            normalized_units = []
            for unit in memory_units:
                normalized = dict(unit)
                normalized["revision_id"] = normalized.get("revision_id") or revision_id
                normalized_units.append(normalized)

            self.insert_memory_units(normalized_units, conn=conn)
            if owns_connection:
                conn.commit()
            return old_memory_unit_ids
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def get_memory_unit_ids_by_revision(self, revision_id: str) -> list[str]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT memory_unit_id
                FROM memory_units
                WHERE revision_id = ?
                ORDER BY unit_index
                """,
                (revision_id,),
            ).fetchall()
        return [row["memory_unit_id"] for row in rows]

    def list_active_raw_documents(
        self,
        *,
        source: str,
        source_type: str,
        root_document_id: str | None = None,
    ) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            if root_document_id is None:
                return conn.execute(
                    """
                    SELECT raw_document_id, external_id, latest_revision_id
                    FROM raw_documents
                    WHERE source = ? AND source_type = ? AND is_active = 1
                    """,
                    (source, source_type),
                ).fetchall()
            return conn.execute(
                """
                SELECT raw_document_id, external_id, latest_revision_id
                FROM raw_documents
                WHERE source = ? AND source_type = ? AND root_document_id = ? AND is_active = 1
                """,
                (source, source_type, root_document_id),
            ).fetchall()

    def list_conversation_raw_documents(
        self,
        *,
        source: str,
        source_type: str,
        root_document_id: str,
        conn=None,
    ) -> list[dict[str, Any]]:
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            rows = conn.execute(
                """
                SELECT raw_document_id, external_id, root_document_id, sequence,
                       raw_payload, metadata_json, latest_revision_id, is_active
                FROM raw_documents
                WHERE source = ? AND source_type = ? AND root_document_id = ? AND is_active = 1
                ORDER BY
                    CASE WHEN sequence IS NULL THEN 1 ELSE 0 END,
                    sequence,
                    external_id
                """,
                (source, source_type, root_document_id),
            ).fetchall()
            return rows
        finally:
            if owns_connection:
                conn.close()

    def update_raw_document_sequence_fields(
        self,
        updates: list[dict[str, Any]],
        *,
        conn=None,
    ) -> None:
        if not updates:
            return
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            conn.executemany(
                """
                UPDATE raw_documents
                SET sequence = ?,
                    raw_payload = ?,
                    metadata_json = ?
                WHERE raw_document_id = ?
                """,
                [
                    (
                        update["sequence"],
                        update.get("raw_payload"),
                        update.get("metadata_json"),
                        update["raw_document_id"],
                    )
                    for update in updates
                ],
            )
            conn.executemany(
                """
                UPDATE raw_document_revisions
                SET raw_payload = ?,
                    metadata_json = ?
                WHERE revision_id = ?
                """,
                [
                    (
                        update.get("raw_payload"),
                        update.get("metadata_json"),
                        update["latest_revision_id"],
                    )
                    for update in updates
                    if update.get("latest_revision_id")
                ],
            )
            if owns_connection:
                conn.commit()
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def mark_raw_document_inactive(self, raw_document_id: str, *, conn=None) -> dict[str, Any] | None:
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            document = conn.execute(
                """
                SELECT raw_document_id, sequence, title, author, created_at, content, content_hash,
                       latest_revision_id, raw_payload, metadata_json, is_active
                FROM raw_documents
                WHERE raw_document_id = ?
                """,
                (raw_document_id,),
            ).fetchone()
            if document is None:
                return None

            previous_revision_id = document.get("latest_revision_id")
            deleted_content_hash = f"{document['content_hash']}:deleted"
            deleted_revision_id = f"{raw_document_id}:deleted:{document['content_hash'][:12]}"

            if previous_revision_id:
                conn.execute(
                    """
                    UPDATE raw_document_revisions
                    SET is_current = 0
                    WHERE raw_document_id = ?
                    """,
                    (raw_document_id,),
                )

            conn.execute(
                """
                INSERT OR REPLACE INTO raw_document_revisions (
                    revision_id,
                    raw_document_id,
                    content,
                    content_hash,
                    title,
                    author,
                    created_at,
                    raw_payload,
                    metadata_json,
                    change_type,
                    is_current
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'deleted', 1)
                """,
                (
                    deleted_revision_id,
                    raw_document_id,
                    document["content"],
                    deleted_content_hash,
                    document.get("title"),
                    document.get("author"),
                    document.get("created_at"),
                    document.get("raw_payload"),
                    document.get("metadata_json"),
                ),
            )
            conn.execute(
                """
                UPDATE raw_documents
                SET is_active = 0,
                    latest_revision_id = ?,
                    imported_at = CURRENT_TIMESTAMP
                WHERE raw_document_id = ?
                """,
                (deleted_revision_id, raw_document_id),
            )
            if owns_connection:
                conn.commit()
            return {
                "previous_revision_id": previous_revision_id,
                "deleted_revision_id": deleted_revision_id,
            }
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def get_memory_units_by_raw_document_id(self, raw_document_id: str) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT mu.memory_unit_id, mu.revision_id, mu.raw_document_id, mu.unit_index,
                       mu.unit_type, mu.content, mu.recall_domain, mu.summary,
                       mu.start_char, mu.end_char, mu.embedding_version, mu.metadata_json,
                       mu.created_at, mu.updated_at, mu.is_embedded
                FROM memory_units mu
                JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
                JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
                WHERE mu.raw_document_id = ? AND rr.is_current = 1 AND rd.is_active = 1
                ORDER BY mu.unit_index
                """,
                (raw_document_id,),
            ).fetchall()

    def mark_memory_units_as_embedded(self, memory_unit_ids: list[str], *, conn=None) -> None:
        if not memory_unit_ids:
            return
        owns_connection = conn is None
        if owns_connection:
            conn = self.get_connection()
        try:
            conn.executemany(
                """
                UPDATE memory_units
                SET is_embedded = 1, updated_at = CURRENT_TIMESTAMP
                WHERE memory_unit_id = ?
                """,
                [(memory_unit_id,) for memory_unit_id in memory_unit_ids],
            )
            if owns_connection:
                conn.commit()
        except Exception:
            if owns_connection:
                conn.rollback()
            raise
        finally:
            if owns_connection:
                conn.close()

    def create_import_job(
        self,
        *,
        source: str,
        file_name: str,
        file_path: str,
        file_hash: str,
        import_config_json: str | None = None,
        notes: str | None = None,
    ) -> int:
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO import_jobs (
                    source,
                    file_name,
                    file_path,
                    file_hash,
                    import_config_json,
                    notes,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, 'running')
                """,
                (source, file_name, file_path, file_hash, import_config_json, notes),
            )
            return int(cursor.lastrowid)

    def finish_import_job(
        self,
        import_id: int,
        *,
        status: str,
        raw_documents_count: int,
        memory_units_count: int,
        skipped_count: int = 0,
        error_message: str | None = None,
        notes: str | None = None,
    ) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE import_jobs
                SET finished_at = CURRENT_TIMESTAMP,
                    status = ?,
                    raw_documents_count = ?,
                    memory_units_count = ?,
                    skipped_count = ?,
                    error_message = ?,
                    notes = COALESCE(?, notes)
                WHERE import_id = ?
                """,
                (
                    status,
                    raw_documents_count,
                    memory_units_count,
                    skipped_count,
                    error_message,
                    notes,
                    import_id,
                ),
            )

    def get_import_job(self, import_id: int) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT import_id, source, file_name, file_path, file_hash,
                       started_at, finished_at, raw_documents_count, memory_units_count,
                       skipped_count, status, error_message, import_config_json, notes
                FROM import_jobs
                WHERE import_id = ?
                """,
                (import_id,),
            ).fetchone()

    def get_raw_document(self, raw_document_id: str) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT raw_document_id, source, source_type, external_id, root_document_id,
                       sequence, title, author, created_at, imported_at, content, content_hash,
                       current_content_hash, latest_revision_id, is_active, raw_payload, metadata_json
                FROM raw_documents
                WHERE raw_document_id = ?
                """,
                (raw_document_id,),
            ).fetchone()

    def get_memory_unit(self, memory_unit_id: str) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT memory_unit_id, revision_id, raw_document_id, unit_index, unit_type, content,
                       recall_domain, summary, start_char, end_char, embedding_version, metadata_json,
                       created_at, updated_at, is_embedded
                FROM memory_units
                WHERE memory_unit_id = ?
                """,
                (memory_unit_id,),
            ).fetchone()

    def _memory_unit_detail_query(self, where_sql: str) -> str:
        return f"""
            SELECT
                mu.memory_unit_id,
                mu.revision_id,
                mu.raw_document_id,
                mu.unit_index,
                mu.unit_type,
                mu.recall_domain,
                mu.content AS memory_content,
                mu.summary,
                mu.start_char,
                mu.end_char,
                mu.embedding_version,
                mu.metadata_json AS memory_metadata_json,
                rr.is_current AS revision_is_current,
                rr.content AS raw_content,
                rr.content_hash,
                rr.raw_payload,
                rr.metadata_json AS raw_metadata_json,
                rd.source,
                rd.source_type,
                rd.external_id,
                rd.root_document_id,
                rd.sequence,
                rd.title,
                rd.author,
                rd.created_at,
                rd.imported_at,
                rd.latest_revision_id,
                rd.is_active
            FROM memory_units mu
            JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
            JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
            {where_sql}
        """

    def get_memory_unit_detail(self, memory_unit_id: str) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                self._memory_unit_detail_query("WHERE mu.memory_unit_id = ?"),
                (memory_unit_id,),
            ).fetchone()

    def get_memory_unit_details(self, memory_unit_ids: list[str]) -> dict[str, sqlite3.Row]:
        if not memory_unit_ids:
            return {}
        placeholders = ", ".join("?" for _ in memory_unit_ids)
        with self.get_connection() as conn:
            rows = conn.execute(
                self._memory_unit_detail_query(f"WHERE mu.memory_unit_id IN ({placeholders})"),
                memory_unit_ids,
            ).fetchall()
        return {row["memory_unit_id"]: row for row in rows}

    def get_memory_units_needing_embeddings(self, limit: int = 100) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    mu.memory_unit_id,
                    mu.revision_id,
                    mu.raw_document_id,
                    mu.content,
                    mu.summary,
                    mu.recall_domain,
                    rd.title,
                    rd.source,
                    rd.source_type,
                    rd.author,
                    rd.created_at
                FROM memory_units mu
                JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
                JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
                WHERE mu.is_embedded = 0 AND rr.is_current = 1 AND rd.is_active = 1
                ORDER BY rd.created_at, mu.memory_unit_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
