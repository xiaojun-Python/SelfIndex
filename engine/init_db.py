"""数据库 schema 初始化。

这里集中定义当前项目会用到的表和索引。
"""

from __future__ import annotations

from pathlib import Path

from engine.sqlite_backend import connect_database


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
        recall_domain TEXT NOT NULL DEFAULT 'default',
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
    CREATE TABLE IF NOT EXISTS import_jobs (
        import_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT,
        file_name TEXT,
        file_path TEXT,
        file_hash TEXT,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        finished_at DATETIME,
        raw_documents_count INTEGER DEFAULT 0,
        memory_units_count INTEGER DEFAULT 0,
        skipped_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running',
        error_message TEXT,
        import_config_json TEXT,
        notes TEXT
    );
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_source_external_id ON raw_documents(source, external_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_root_document_id ON raw_documents(root_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_raw_document_id ON memory_units(raw_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_is_embedded ON memory_units(is_embedded);",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_started_at ON import_jobs(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);",
]


def init_database(db_path: str | Path) -> None:
    """确保数据库文件存在且所有表、索引都已创建。"""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(db_path) as conn:
        cursor = conn.cursor()
        for sql in TABLE_SCHEMAS:
            cursor.execute(sql)
        for idx_sql in INDEXES:
            cursor.execute(idx_sql)

        # Lightweight migrations for existing DBs.
        cursor.execute("PRAGMA table_info(memory_units)")
        existing_columns = {row["name"] for row in cursor.fetchall()}
        if "recall_domain" not in existing_columns:
            cursor.execute(
                "ALTER TABLE memory_units ADD COLUMN recall_domain TEXT NOT NULL DEFAULT 'default'"
            )
