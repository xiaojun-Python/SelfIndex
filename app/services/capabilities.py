"""Low-cost service capability snapshot; health remains a liveness probe."""

from __future__ import annotations

import os
import sys
from typing import Any

from engine.database import INDEX_MODEL_KEY


def collect_capabilities(
    sqlite_db: Any, vector_db: Any, settings: Any, *, instance_id: str
) -> dict[str, Any]:
    vector_count = int(vector_db.collection.count())
    index_model = (vector_db.collection.metadata or {}).get(INDEX_MODEL_KEY)
    if index_model == settings.embedding_model:
        index_state = "ready"
    elif vector_count == 0 and not index_model:
        index_state = "empty"
    elif not index_model:
        index_state = "unlabelled"
    else:
        index_state = "model_mismatch"

    embedder_module = sys.modules.get("engine.embedder")
    manager = getattr(embedder_module, "embedding_manager", None)
    model_loaded = getattr(manager, "_model", None) is not None
    archive_writable = os.access(sqlite_db.db_path, os.W_OK) and os.access(
        sqlite_db.db_path.parent, os.W_OK
    )
    index_writable = os.access(vector_db.persist_directory, os.W_OK)
    index_compatible = index_state in {"ready", "empty"}

    return {
        "ok": index_compatible,
        "service": "selfindex",
        "version": "0.1.0",
        "instance_id": instance_id,
        "profile_id": sqlite_db.profile_id(vector_db.persist_directory),
        "storage_layout": getattr(settings, "storage_layout", "unknown"),
        "index": {
            "state": index_state,
            "vectors": vector_count,
            "model": index_model,
            "configured_model": settings.embedding_model,
            "model_loaded": model_loaded,
        },
        "pending": {
            "embeddings": sqlite_db.count_pending_embeddings(),
            "vector_deletions": sqlite_db.count_pending_vector_deletions(),
            "source_writes": sqlite_db.count_pending_source_writes(),
        },
        "capabilities": {
            "archive_read": True,
            "archive_write": bool(archive_writable),
            "search": index_compatible,
            "index_write": bool(index_compatible and archive_writable and index_writable),
        },
    }
