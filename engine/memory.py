"""记忆层构建工具。

这里的职责是把“原始文档”转换成“记忆单元”。
原始文档强调完整保存，记忆单元强调便于检索与回溯。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from engine.chunker import smart_chunking


def get_content_hash(text: str) -> str:
    """为内容生成稳定哈希，用于去重和变更判断。"""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def build_summary(text: str, limit: int = 120) -> str:
    """生成一个当前阶段足够轻量的摘要。"""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def build_raw_document(
    *,
    source: str,
    source_type: str,
    external_id: str,
    root_document_id: str | None,
    title: str | None,
    author: str | None,
    created_at: str | None,
    content: str,
    raw_payload: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """把导入器输出标准化为 raw_documents 表需要的结构。"""
    raw_document_id = f"{source.lower()}:{source_type}:{external_id}"
    return {
        "raw_document_id": raw_document_id,
        "source": source,
        "source_type": source_type,
        "external_id": external_id,
        "root_document_id": root_document_id,
        "title": title,
        "author": author,
        "created_at": created_at,
        "content": content,
        "content_hash": get_content_hash(content),
        "raw_payload": json.dumps(raw_payload, ensure_ascii=False),
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }


def build_memory_units(
    raw_document: dict[str, Any],
    *,
    embedding_version: str,
    unit_type: str = "chunk",
) -> list[dict[str, Any]]:
    """从一条原始文档中切出多条记忆单元。"""
    content = raw_document["content"]
    chunks = smart_chunking(
        content,
        raw_document.get("title") or "",
        raw_document.get("author") or "",
    )

    # 如果 chunker 没切出来，但原文非空，至少保留一个完整单元。
    if not chunks and content.strip():
        stripped = content.strip()
        start = content.find(stripped)
        chunks = [
            {
                "content": stripped,
                "start": max(start, 0),
                "end": max(start, 0) + len(stripped),
            }
        ]

    unit_metadata = {
        "source": raw_document["source"],
        "source_type": raw_document["source_type"],
        "title": raw_document.get("title"),
        "author": raw_document.get("author"),
        "created_at": raw_document.get("created_at"),
    }

    memory_units: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        memory_units.append(
            {
                "memory_unit_id": f"{raw_document['raw_document_id']}:{index}",
                "raw_document_id": raw_document["raw_document_id"],
                "unit_index": index,
                "unit_type": unit_type,
                "content": chunk["content"],
                "summary": build_summary(chunk["content"]),
                "start_char": chunk["start"],
                "end_char": chunk["end"],
                "embedding_version": embedding_version,
                "metadata_json": json.dumps(unit_metadata, ensure_ascii=False),
                "is_embedded": 0,
            }
        )

    return memory_units
