"""应用启动自举逻辑。

这里处理两件事：
1. 如果本地还是旧版数据库结构，就把旧数据投影到新的记忆链路里。
2. 尝试提前预热 embedding 模型，减少首次搜索的冷启动体感。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from app.core.settings import settings
from engine.memory import build_summary


def bootstrap_legacy_memory_layer(sqlite_db: Any) -> dict[str, int | bool]:
    """把旧版 `messages/chunks` 投影成新版 `raw_documents/memory_units`。

    这不是一次性离线迁移脚本，而是启动时的兜底自举：
    只有当新表为空时才会执行。
    """
    try:
        raw_count = sqlite_db.count_rows("raw_documents")
        memory_count = sqlite_db.count_rows("memory_units")
    except Exception:
        return {"migrated": False, "raw_documents": 0, "memory_units": 0}

    if raw_count > 0 or memory_count > 0:
        return {"migrated": False, "raw_documents": raw_count, "memory_units": memory_count}

    legacy_messages = sqlite_db.get_legacy_messages()
    legacy_chunks = sqlite_db.get_legacy_chunks()
    if not legacy_messages or not legacy_chunks:
        return {"migrated": False, "raw_documents": 0, "memory_units": 0}

    chunks_by_message_id: dict[str, list[Any]] = defaultdict(list)
    for chunk in legacy_chunks:
        chunks_by_message_id[chunk["message_id"]].append(chunk)

    migrated_documents = 0
    migrated_memory_units = 0

    for message in legacy_messages:
        raw_document_id = f"legacy:message:{message['message_id']}"
        sqlite_db.upsert_raw_document(
            {
                "raw_document_id": raw_document_id,
                "source": message["source"] or "legacy",
                "source_type": "legacy_message",
                "external_id": str(message["message_id"]),
                "root_document_id": message["conversation_id"],
                "title": message["title"],
                "author": message["sender_type"],
                "created_at": message["timestamp"] or message["conversation_created_at"],
                "content": message["content"] or "",
                "content_hash": message["content_hash"] or "",
                "raw_payload": message["raw_meta"] or json.dumps({}, ensure_ascii=False),
                "metadata_json": json.dumps(
                    {
                        "model": message["model"],
                        "sequence": message["sequence"],
                        "sub_title": message["sub_title"],
                        "migrated_from": "legacy_messages",
                    },
                    ensure_ascii=False,
                ),
            }
        )

        memory_units = [
            {
                # 这里沿用旧 chunk_id，这样现有 Chroma 向量仍可直接复用。
                "memory_unit_id": str(chunk["chunk_id"]),
                "raw_document_id": raw_document_id,
                "unit_index": chunk["chunk_index"],
                "unit_type": "legacy_chunk",
                "content": chunk["content"],
                "summary": build_summary(chunk["content"]),
                "start_char": chunk["start_char"],
                "end_char": chunk["end_char"],
                "embedding_version": chunk["embedding_version"] or settings.embedding_model,
                "metadata_json": json.dumps(
                    {
                        "migrated_from": "legacy_chunks",
                        "legacy_message_id": message["message_id"],
                    },
                    ensure_ascii=False,
                ),
                "is_embedded": chunk["is_embedded"],
            }
            for chunk in chunks_by_message_id.get(message["message_id"], [])
        ]
        sqlite_db.replace_memory_units(raw_document_id, memory_units)

        migrated_documents += 1
        migrated_memory_units += len(memory_units)

    return {
        "migrated": True,
        "raw_documents": migrated_documents,
        "memory_units": migrated_memory_units,
    }


def warm_up_search_stack() -> None:
    """尽量在应用启动时加载 embedding 模型，减少首次搜索延迟。"""
    try:
        from engine.embedder import embedding_manager

        _ = embedding_manager.model
    except Exception:
        # 预热失败不应该阻止应用启动。
        return
