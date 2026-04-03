"""Database schema initialization and lightweight migrations."""

from __future__ import annotations

from pathlib import Path

from engine.memory import get_revision_id
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
        current_content_hash TEXT,
        latest_revision_id TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        raw_payload TEXT,
        metadata_json TEXT,
        UNIQUE(source, external_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_document_revisions (
        revision_id TEXT PRIMARY KEY,
        raw_document_id TEXT NOT NULL,
        content TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        title TEXT,
        author TEXT,
        created_at TEXT,
        raw_payload TEXT,
        metadata_json TEXT,
        change_type TEXT NOT NULL DEFAULT 'updated',
        is_current INTEGER NOT NULL DEFAULT 1,
        captured_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (raw_document_id) REFERENCES raw_documents(raw_document_id) ON DELETE CASCADE,
        UNIQUE(raw_document_id, content_hash)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS memory_units (
        memory_unit_id TEXT PRIMARY KEY,
        revision_id TEXT,
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
        FOREIGN KEY (raw_document_id) REFERENCES raw_documents(raw_document_id) ON DELETE CASCADE,
        FOREIGN KEY (revision_id) REFERENCES raw_document_revisions(revision_id) ON DELETE CASCADE
    );
    """,
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
    """
    CREATE TABLE IF NOT EXISTS protected_terms (
        term_id INTEGER PRIMARY KEY AUTOINCREMENT,
        term_encoded TEXT NOT NULL,
        encoding TEXT NOT NULL DEFAULT 'base64',
        domain TEXT NOT NULL DEFAULT 'sensitive',
        is_active INTEGER NOT NULL DEFAULT 1,
        notes TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(term_encoded, domain)
    );
    """,
]

INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_source_external_id ON raw_documents(source, external_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_root_document_id ON raw_documents(root_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_latest_revision_id ON raw_documents(latest_revision_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_documents_is_active ON raw_documents(is_active);",
    "CREATE INDEX IF NOT EXISTS idx_raw_document_revisions_raw_document_id ON raw_document_revisions(raw_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_raw_document_revisions_current ON raw_document_revisions(raw_document_id, is_current);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_raw_document_id ON memory_units(raw_document_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_revision_id ON memory_units(revision_id);",
    "CREATE INDEX IF NOT EXISTS idx_memory_units_is_embedded ON memory_units(is_embedded);",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_started_at ON import_jobs(started_at);",
    "CREATE INDEX IF NOT EXISTS idx_import_jobs_status ON import_jobs(status);",
    "CREATE INDEX IF NOT EXISTS idx_protected_terms_active ON protected_terms(is_active);",
]


def _existing_columns(cursor, table_name: str) -> set[str]:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row["name"] for row in cursor.fetchall()}


def _ensure_column(cursor, table_name: str, column_name: str, sql: str) -> None:
    if column_name not in _existing_columns(cursor, table_name):
        cursor.execute(sql)


def _backfill_revisions(cursor) -> None:
    rows = cursor.execute(
        """
        SELECT raw_document_id, title, author, created_at, content, content_hash,
               raw_payload, metadata_json, latest_revision_id, current_content_hash
        FROM raw_documents
        """
    ).fetchall()

    for row in rows:
        revision_id = row["latest_revision_id"] or get_revision_id(
            row["raw_document_id"], row["content_hash"]
        )
        cursor.execute(
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', 1)
            """,
            (
                revision_id,
                row["raw_document_id"],
                row["content"],
                row["content_hash"],
                row["title"],
                row["author"],
                row["created_at"],
                row["raw_payload"],
                row["metadata_json"],
            ),
        )
        cursor.execute(
            """
            UPDATE raw_documents
            SET latest_revision_id = COALESCE(latest_revision_id, ?),
                current_content_hash = COALESCE(current_content_hash, content_hash)
            WHERE raw_document_id = ?
            """,
            (revision_id, row["raw_document_id"]),
        )
        cursor.execute(
            """
            UPDATE raw_document_revisions
            SET is_current = CASE WHEN revision_id = ? THEN 1 ELSE 0 END
            WHERE raw_document_id = ?
            """,
            (revision_id, row["raw_document_id"]),
        )
        cursor.execute(
            """
            UPDATE memory_units
            SET revision_id = COALESCE(revision_id, ?)
            WHERE raw_document_id = ? AND revision_id IS NULL
            """,
            (revision_id, row["raw_document_id"]),
        )


def init_database(db_path: str | Path) -> None:
    """Ensure tables, indexes, and lightweight migrations are in place."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with connect_database(db_path) as conn:
        cursor = conn.cursor()
        for sql in TABLE_SCHEMAS:
            cursor.execute(sql)

        _ensure_column(
            cursor,
            "raw_documents",
            "current_content_hash",
            "ALTER TABLE raw_documents ADD COLUMN current_content_hash TEXT",
        )
        _ensure_column(
            cursor,
            "raw_documents",
            "latest_revision_id",
            "ALTER TABLE raw_documents ADD COLUMN latest_revision_id TEXT",
        )
        _ensure_column(
            cursor,
            "raw_documents",
            "is_active",
            "ALTER TABLE raw_documents ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
        )
        _ensure_column(
            cursor,
            "memory_units",
            "recall_domain",
            "ALTER TABLE memory_units ADD COLUMN recall_domain TEXT NOT NULL DEFAULT 'default'",
        )
        _ensure_column(
            cursor,
            "memory_units",
            "revision_id",
            "ALTER TABLE memory_units ADD COLUMN revision_id TEXT",
        )

        _backfill_revisions(cursor)

        for idx_sql in INDEXES:
            cursor.execute(idx_sql)
