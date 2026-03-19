import sqlite3
from pathlib import Path
from typing import Any

import chromadb

from engine.init_db import init_database


class VectorManager:
    def __init__(self, persist_directory: str | Path) -> None:
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_directory))
        self.collection = self.client.get_or_create_collection(
            name="my_knowledge_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def add_vectors(self, ids: list[str], embeddings: list[list[float]], metadatas: list[dict[str, Any]], documents: list[str]) -> None:
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
        )


class DatabaseManager:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        if not self.db_path.exists():
            init_database(self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_full_conversation(self, conv_meta_tuple: tuple[Any, ...], messages_tuples: list[tuple[Any, ...]]) -> None:
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
        query = "SELECT 1 FROM chunks WHERE hash = ? LIMIT 1"
        with self.get_connection() as conn:
            return conn.execute(query, (content_hash,)).fetchone() is not None

    def mark_chunks_as_processed(self, chunk_ids: list[int]) -> None:
        if not chunk_ids:
            return
        query = "UPDATE chunks SET is_embedded = 1, updated_at = CURRENT_TIMESTAMP WHERE chunk_id = ?"
        with self.get_connection() as conn:
            conn.executemany(query, [(chunk_id,) for chunk_id in chunk_ids])

    def get_messages_needing_chunks(self) -> list[sqlite3.Row]:
        query = """
            SELECT m.message_id, m.content, c.title, m.sender_type
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.conversation_id
            LEFT JOIN chunks ch ON m.message_id = ch.message_id
            WHERE ch.chunk_id IS NULL
        """
        with self.get_connection() as conn:
            return conn.execute(query).fetchall()

    def get_unprocessed_chunks(self, limit: int = 100) -> list[dict[str, Any]]:
        query = """
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
        """
        with self.get_connection() as conn:
            return [dict(row) for row in conn.execute(query, (limit,)).fetchall()]

    def get_message_detail_by_chunk(self, chunk_id: str | int) -> sqlite3.Row | None:
        query = """
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
        """
        with self.get_connection() as conn:
            return conn.execute(query, (chunk_id,)).fetchone()

    def get_chunks_by_message_id(self, message_id: str) -> list[sqlite3.Row]:
        query = """
            SELECT chunk_id, message_id, chunk_index, start_char, end_char, content, hash,
                   embedding_version, created_at, updated_at, is_embedded
            FROM chunks
            WHERE message_id = ?
            ORDER BY chunk_index, chunk_id
        """
        with self.get_connection() as conn:
            return conn.execute(query, (message_id,)).fetchall()

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

            new_chunk_rows = []
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
            cursor.execute("DELETE FROM chunks WHERE message_id = ?", (snapshot["message"]["message_id"],))

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
