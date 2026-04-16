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


def get_revision_id(raw_document_id: str, content_hash: str) -> str:
    """Build a stable revision id from the document identity and content hash."""
    return f"{raw_document_id}:{content_hash[:12]}"


def build_summary(text: str, limit: int = 120) -> str:
    """生成一个当前阶段足够轻量的摘要。"""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def build_protected_match_text(
    *,
    content: str,
    title: str | None = None,
    author: str | None = None,
) -> str:
    parts = [title or "", author or "", content or ""]
    return "\n".join(part for part in parts if part).lower()


def build_raw_document(
    *,
    source: str,
    source_type: str,
    external_id: str,
    root_document_id: str | None,
    sequence: int | None = None,
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
        "sequence": sequence,
        "title": title,
        "author": author,
        "created_at": created_at,
        "content": content,
        "content_hash": get_content_hash(content),
        "raw_payload": json.dumps(raw_payload, ensure_ascii=False),
        "metadata_json": json.dumps(metadata, ensure_ascii=False),
    }


def build_raw_document_revision(
    raw_document: dict[str, Any],
    *,
    change_type: str = "updated",
    is_current: int = 1,
) -> dict[str, Any]:
    """Build a raw document revision snapshot from the current raw document payload."""
    revision_id = get_revision_id(raw_document["raw_document_id"], raw_document["content_hash"])
    return {
        "revision_id": revision_id,
        "raw_document_id": raw_document["raw_document_id"],
        "content": raw_document["content"],
        "content_hash": raw_document["content_hash"],
        "title": raw_document.get("title"),
        "author": raw_document.get("author"),
        "created_at": raw_document.get("created_at"),
        "raw_payload": raw_document.get("raw_payload"),
        "metadata_json": raw_document.get("metadata_json"),
        "change_type": change_type,
        "is_current": is_current,
    }


def build_memory_units(
    raw_document: dict[str, Any],
    *,
    revision_id: str,
    embedding_version: str,
    unit_type: str = "chunk",
    protected_rules: list[dict[str, Any]] | None = None,
    protected_terms: list[str] | None = None,
    protected_domain: str = "identity",
) -> list[dict[str, Any]]:
    """从一条原始文档中切出多条记忆单元。"""
    content = raw_document["content"]
    protected_terms = protected_terms or []
    protected_rules = protected_rules or []
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

    normalized_rules = [
        {
            "term": rule["term"].lower(),
            "domain": rule.get("domain") or "sensitive",
        }
        for rule in protected_rules
        if rule.get("term")
    ]
    normalized_rules.extend(
        {
            "term": term.lower(),
            "domain": protected_domain,
        }
        for term in protected_terms
        if term
    )

    memory_units: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        chunk_content = chunk["content"]
        recall_domain = "default"
        if normalized_rules:
            lowered = build_protected_match_text(
                content=chunk_content,
                title=raw_document.get("title"),
                author=raw_document.get("author"),
            )
            for rule in normalized_rules:
                if rule["term"] in lowered:
                    recall_domain = rule["domain"]
                    break

        memory_units.append(
            {
                "memory_unit_id": f"{revision_id}:{index}",
                "revision_id": revision_id,
                "raw_document_id": raw_document["raw_document_id"],
                "unit_index": index,
                "unit_type": unit_type,
                "recall_domain": recall_domain,
                "content": chunk_content,
                "summary": build_summary(chunk_content),
                "start_char": chunk["start"],
                "end_char": chunk["end"],
                "embedding_version": embedding_version,
                "metadata_json": json.dumps(unit_metadata, ensure_ascii=False),
                "is_embedded": 0,
            }
        )

    return memory_units
