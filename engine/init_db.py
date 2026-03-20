"""数据库 schema 初始化。

这里集中定义当前项目会用到的表和索引。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


TABLE_SCHEMAS = [
    """
    CREATE TABLE IF NOT EXISTS raw_documents (
        raw_document_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        source_type TEXT NOT NULL,
        external_id TEXT NOT NULL,
        root_document_id TEXT,
        title TEXT,
        author TEXT,
        created_at TEXT,
        imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        raw_payload TEXT,
        metadata_json TEXT,
        UNIQUE(source, external_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_units (
        memory_unit_id TEXT PRIMARY KEY,
        raw_document_id TEXT NOT NULL,
        unit_index INTEGER NOT NULL,
        unit_type TEXT NOT NULL DEFAULT 'chunk',
        content TEXT NOT NULL,
        summary TEXT,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        embedding_version TEXT,
        metadata_json TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_embedded INTEGER DEFAULT 0,
        FOREIGN KEY (raw_document_id) REFERENCES raw_documents(raw_document_id) ON DELETE CASCADE
    );
    """,
    # 下面三张表属于旧版兼容层，暂时保留给现有 Web 与历史数据使用。
    """
    CREATE TABLE IF NOT EXISTS conversations (
        conversation_id TEXT PRIMARY KEY,
        title TEXT,
        created_at TEXT,
        source TEXT,
        raw_meta TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        message_id TEXT PRIMARY KEY,
        conversation_id TEXT,
        sub_title TEXT,
        sender_type TEXT,
        content TEXT,
        content_length INTEGER,
        model TEXT,
        content_hash TEXT,
        sequence INTEGER,
        timestamp TEXT,
        FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        chunk_index INTEGER NOT NULL,
        start_char INTEGER NOT NULL,
        end_char INTEGER NOT NULL,
        content TEXT NOT NULL,
        hash TEXT,
        embedding_version TEXT DEFAULT 'bge-small-zh-v1.5',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        is_embedded INTEGER DEFAULT 0,
        FOREIGN KEY (message_id) REFERENCES messages(message_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS import_logs (
        import_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        file_name TEXT,
        import_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        records_count INTEGER,
        status TEXT DEFAULT 'success',
        error_message TEXT,
        notes TEXT
    );
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_source_external_id ON raw_documents(source, external_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_root_document_id ON raw_documents(root_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_raw_document_id ON memory_units(raw_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_is_embedded ON memory_units(is_embedded);",
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_import_logs_import_time ON import_logs(import_time);",
    "CREATE INDEX IF NOT EXISTS idx_content_hash ON messages(content_hash);",
]


def init_database(db_path: str | Path) -> None:
    """确保数据库文件存在且所有表、索引都已创建。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for sql in TABLE_SCHEMAS:
            cursor.execute(sql)
        for idx_sql in INDEXES:
            cursor.execute(idx_sql)
