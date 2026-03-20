"""数据库与向量库访问层。

这个模块是项目的数据中枢，负责两件事：
1. 访问 SQLite，保存结构化的原始文档、记忆单元和旧版兼容数据。
2. 访问 Chroma，保存记忆单元对应的向量索引。

如果你想理解 SelfIndex 目前的“落盘方式”，这个文件是最核心的入口之一。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import chromadb

from engine.init_db import init_database


class VectorManager:
    """对 Chroma 的一个很薄的封装。"""

    def __init__(self, persist_directory: str | Path) -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
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
    """集中管理 SQLite 的读写。

    当前同时维护两套模型：
    - 新模型：`raw_documents` / `memory_units`
    - 旧模型：`conversations` / `messages` / `chunks`

    这样做是为了在重构期间，既能推进新架构，也不直接打断旧 UI。
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        """每次启动都补齐缺失表，兼容旧数据库的渐进式迁移。"""
        init_database(self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        """返回一个开启了行名访问和外键约束的连接。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def count_rows(self, table_name: str) -> int:
        with self.get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
        return int(row["count"]) if row else 0

    def upsert_raw_document(self, raw_document: dict[str, Any]) -> None:
        """插入或更新一条原始文档记录。"""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO raw_documents (
                    raw_document_id,
                    source,
                    source_type,
                    external_id,
                    root_document_id,
                    title,
                    author,
                    created_at,
                    content,
                    content_hash,
                    raw_payload,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(raw_document_id) DO UPDATE SET
                    source = excluded.source,
                    source_type = excluded.source_type,
                    external_id = excluded.external_id,
                    root_document_id = excluded.root_document_id,
                    title = excluded.title,
                    author = excluded.author,
                    created_at = excluded.created_at,
                    imported_at = CURRENT_TIMESTAMP,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    raw_payload = excluded.raw_payload,
                    metadata_json = excluded.metadata_json
                """,
                (
                    raw_document["raw_document_id"],
                    raw_document["source"],
                    raw_document["source_type"],
                    raw_document["external_id"],
                    raw_document.get("root_document_id"),
                    raw_document.get("title"),
                    raw_document.get("author"),
                    raw_document.get("created_at"),
                    raw_document["content"],
                    raw_document["content_hash"],
                    raw_document.get("raw_payload"),
                    raw_document.get("metadata_json"),
                ),
            )

    def replace_memory_units(
        self,
        raw_document_id: str,
        memory_units: list[dict[str, Any]],
    ) -> list[str]:
        """替换某个原始文档下的全部记忆单元，并返回旧 ID。"""
        with self.get_connection() as conn:
            old_ids = [
                row["memory_unit_id"]
                for row in conn.execute(
                    "SELECT memory_unit_id FROM memory_units WHERE raw_document_id = ?",
                    (raw_document_id,),
                ).fetchall()
            ]
            conn.execute("DELETE FROM memory_units WHERE raw_document_id = ?", (raw_document_id,))
            conn.executemany(
                """
                INSERT INTO memory_units (
                    memory_unit_id,
                    raw_document_id,
                    unit_index,
                    unit_type,
                    content,
                    summary,
                    start_char,
                    end_char,
                    embedding_version,
                    metadata_json,
                    is_embedded
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        unit["memory_unit_id"],
                        unit["raw_document_id"],
                        unit["unit_index"],
                        unit["unit_type"],
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
            return old_ids

    def mark_memory_units_as_embedded(self, memory_unit_ids: list[str]) -> None:
        if not memory_unit_ids:
            return
        with self.get_connection() as conn:
            conn.executemany(
                """
                UPDATE memory_units
                SET is_embedded = 1, updated_at = CURRENT_TIMESTAMP
                WHERE memory_unit_id = ?
                """,
                [(memory_unit_id,) for memory_unit_id in memory_unit_ids],
            )

    def get_raw_document(self, raw_document_id: str) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT raw_document_id, source, source_type, external_id, root_document_id,
                       title, author, created_at, imported_at, content, content_hash,
                       raw_payload, metadata_json
                FROM raw_documents
                WHERE raw_document_id = ?
                """,
                (raw_document_id,),
            ).fetchone()

    def get_memory_unit(self, memory_unit_id: str) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT memory_unit_id, raw_document_id, unit_index, unit_type, content,
                       summary, start_char, end_char, embedding_version, metadata_json,
                       created_at, updated_at, is_embedded
                FROM memory_units
                WHERE memory_unit_id = ?
                """,
                (memory_unit_id,),
            ).fetchone()

    def get_memory_unit_detail(self, memory_unit_id: str) -> sqlite3.Row | None:
        """返回记忆单元和它关联的原始文档详情。"""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    mu.memory_unit_id,
                    mu.raw_document_id,
                    mu.unit_index,
                    mu.unit_type,
                    mu.content AS memory_content,
                    mu.summary,
                    mu.start_char,
                    mu.end_char,
                    mu.embedding_version,
                    mu.metadata_json AS memory_metadata_json,
                    rd.source,
                    rd.source_type,
                    rd.external_id,
                    rd.root_document_id,
                    rd.title,
                    rd.author,
                    rd.created_at,
                    rd.imported_at,
                    rd.content AS raw_content,
                    rd.content_hash,
                    rd.raw_payload,
                    rd.metadata_json AS raw_metadata_json
                FROM memory_units mu
                JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
                WHERE mu.memory_unit_id = ?
                """,
                (memory_unit_id,),
            ).fetchone()

    def get_memory_units_by_raw_document_id(self, raw_document_id: str) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT memory_unit_id, raw_document_id, unit_index, unit_type, content,
                       summary, start_char, end_char, embedding_version, metadata_json,
                       created_at, updated_at, is_embedded
                FROM memory_units
                WHERE raw_document_id = ?
                ORDER BY unit_index
                """,
                (raw_document_id,),
            ).fetchall()

    def get_legacy_messages(self) -> list[sqlite3.Row]:
        """为旧版数据自举到新模型提供读取入口。"""
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    m.message_id,
                    m.sub_title,
                    m.sender_type,
                    m.content,
                    m.content_length,
                    m.model,
                    m.content_hash,
                    m.sequence,
                    m.timestamp,
                    c.conversation_id,
                    c.title,
                    c.created_at AS conversation_created_at,
                    c.source,
                    c.raw_meta
                FROM messages m
                JOIN conversations c ON c.conversation_id = m.conversation_id
                ORDER BY c.conversation_id, m.sequence, m.message_id
                """
            ).fetchall()

    def get_legacy_chunks(self) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    chunk_id,
                    message_id,
                    chunk_index,
                    start_char,
                    end_char,
                    content,
                    hash,
                    embedding_version,
                    is_embedded
                FROM chunks
                ORDER BY message_id, chunk_index, chunk_id
                """
            ).fetchall()

    def save_full_conversation(
        self,
        conv_meta_tuple: tuple[Any, ...],
        messages_tuples: list[tuple[Any, ...]],
    ) -> None:
        """旧版导入链路仍在使用的 conversation/message 存储接口。"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO conversations
                (conversation_id, title, created_at, source, raw_meta)
                VALUES (?, ?, ?, ?, ?)
                """,
                conv_meta_tuple,
            )
            cursor.executemany(
                """
                INSERT OR REPLACE INTO messages
                (message_id, conversation_id, sub_title, sender_type, content,
                 content_length, model, content_hash, sequence, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                messages_tuples,
            )

    def save_chunks(self, chunk_tuples: list[tuple[Any, ...]]) -> None:
        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO chunks
                (message_id, chunk_index, start_char, end_char, content, hash, embedding_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                chunk_tuples,
            )

    def chunk_exists(self, content_hash: str) -> bool:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT 1 FROM chunks WHERE hash = ? LIMIT 1",
                (content_hash,),
            ).fetchone() is not None

    def mark_chunks_as_processed(self, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        with self.get_connection() as conn:
            conn.executemany(
                """
                UPDATE chunks
                SET is_embedded = 1, updated_at = CURRENT_TIMESTAMP
                WHERE chunk_id = ?
                """,
                [(chunk_id,) for chunk_id in chunk_ids],
            )

    def get_messages_needing_chunks(self) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT m.message_id, m.content, c.title, m.sender_type
                FROM messages m
                JOIN conversations c ON m.conversation_id = c.conversation_id
                LEFT JOIN chunks ch ON m.message_id = ch.message_id
                WHERE ch.chunk_id IS NULL
                """
            ).fetchall()

    def get_unprocessed_chunks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT
                    ch.chunk_id,
                    ch.message_id,
                    ch.content,
                    m.sub_title,
                    m.timestamp,
                    m.model,
                    c.title,
                    c.source
                FROM chunks ch
                JOIN messages m ON ch.message_id = m.message_id
                JOIN conversations c ON m.conversation_id = c.conversation_id
                WHERE ch.is_embedded = 0
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_message_detail_by_chunk(self, chunk_id: str | int) -> sqlite3.Row | None:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT
                    ch.chunk_id,
                    ch.message_id,
                    m.content,
                    m.content_length,
                    m.content_hash,
                    m.sender_type,
                    m.timestamp,
                    m.model,
                    c.conversation_id,
                    c.title,
                    c.source,
                    c.raw_meta
                FROM chunks ch
                JOIN messages m ON ch.message_id = m.message_id
                JOIN conversations c ON m.conversation_id = c.conversation_id
                WHERE ch.chunk_id = ?
                """,
                (chunk_id,),
            ).fetchone()

    def get_chunks_by_message_id(self, message_id: str) -> list[sqlite3.Row]:
        with self.get_connection() as conn:
            return conn.execute(
                """
                SELECT chunk_id, message_id, chunk_index, start_char, end_char, content, hash,
                       embedding_version, created_at, updated_at, is_embedded
                FROM chunks
                WHERE message_id = ?
                ORDER BY chunk_index, chunk_id
                """,
                (message_id,),
            ).fetchall()

    def replace_message_and_chunks(
        self,
        message_id: str,
        conversation_id: str,
        title: str,
        sender: str,
        content: str,
        content_hash: str,
        chunk_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """旧 UI 编辑消息时使用的事务性更新接口。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                (title, conversation_id),
            )
            cursor.execute(
                """
                UPDATE messages
                SET sender_type = ?, content = ?, content_length = ?, content_hash = ?
                WHERE message_id = ?
                """,
                (sender, content, len(content), content_hash, message_id),
            )
            cursor.execute("DELETE FROM chunks WHERE message_id = ?", (message_id,))

            new_chunk_rows: list[dict[str, Any]] = []
            for chunk in chunk_rows:
                cursor.execute(
                    """
                    INSERT INTO chunks
                    (message_id, chunk_index, start_char, end_char, content, hash, embedding_version, is_embedded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        chunk["chunk_index"],
                        chunk["start_char"],
                        chunk["end_char"],
                        chunk["content"],
                        chunk["hash"],
                        chunk["embedding_version"],
                        0,
                    ),
                )
                row = dict(chunk)
                row["chunk_id"] = cursor.lastrowid
                new_chunk_rows.append(row)

            conn.commit()
            return new_chunk_rows
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def restore_message_snapshot(self, snapshot: dict[str, Any]) -> None:
        """旧 UI 编辑失败时，用快照恢复消息和 chunk。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                (snapshot["conversation"]["title"], snapshot["conversation"]["conversation_id"]),
            )
            cursor.execute(
                """
                UPDATE messages
                SET sender_type = ?, content = ?, content_length = ?, content_hash = ?
                WHERE message_id = ?
                """,
                (
                    snapshot["message"]["sender_type"],
                    snapshot["message"]["content"],
                    snapshot["message"]["content_length"],
                    snapshot["message"]["content_hash"],
                    snapshot["message"]["message_id"],
                ),
            )
            cursor.execute(
                "DELETE FROM chunks WHERE message_id = ?",
                (snapshot["message"]["message_id"],),
            )

            for chunk in snapshot["chunks"]:
                cursor.execute(
                    """
                    INSERT INTO chunks
                    (chunk_id, message_id, chunk_index, start_char, end_char, content, hash,
                     embedding_version, created_at, updated_at, is_embedded)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk["chunk_id"],
                        chunk["message_id"],
                        chunk["chunk_index"],
                        chunk["start_char"],
                        chunk["end_char"],
                        chunk["content"],
                        chunk["hash"],
                        chunk["embedding_version"],
                        chunk["created_at"],
                        chunk["updated_at"],
                        chunk["is_embedded"],
                    ),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
