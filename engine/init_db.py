import sqlite3
from pathlib import Path


TABLE_SCHEMAS = [
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
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);",
    "CREATE INDEX IF NOT EXISTS idx_import_logs_import_time ON import_logs(import_time);",
    "CREATE INDEX IF NOT EXISTS idx_content_hash ON messages(content_hash);",
]


def init_database(db_path: str | Path) -> None:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        for sql in TABLE_SCHEMAS:
            cursor.execute(sql)
        for idx_sql in INDEXES:
            cursor.execute(idx_sql)
