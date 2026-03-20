"""检索层逻辑。

这里负责把查询转换为向量搜索，再把命中的记忆单元组装成界面或 API 可消费的数据。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.core.settings import settings
from engine.memory import build_summary

VALID_SORTS = {"default", "time_asc", "time_desc"}
PREVIEW_LENGTH = 120


def _get_embedder(embedder: Any = None) -> Any:
    if embedder is not None:
        return embedder

    from engine.embedder import embedding_manager

    return embedding_manager


def build_preview(text: str, query: str, limit: int = PREVIEW_LENGTH) -> str:
    """给搜索结果生成一段靠近命中词的预览片段。"""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""

    keywords = [part.strip() for part in (query or "").split() if part.strip()]
    hit_index = -1
    hit_keyword = ""

    for keyword in keywords:
        index = cleaned.lower().find(keyword.lower())
        if index != -1 and (hit_index == -1 or index < hit_index):
            hit_index = index
            hit_keyword = keyword

    if hit_index == -1:
        return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "..."

    keyword_len = len(hit_keyword)
    half_window = max(20, (limit - keyword_len) // 2)
    start = max(0, hit_index - half_window)
    end = min(len(cleaned), hit_index + keyword_len + half_window)

    snippet = cleaned[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(cleaned):
        snippet = snippet + "..."
    return snippet


def normalize_timestamp(value: Any) -> str:
    """把不同格式的时间统一为便于展示和比较的字符串。"""
    if not value:
        return ""

    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text[:19]


def parse_filters(args: Any) -> dict[str, Any]:
    """解析旧 UI 搜索页用到的过滤条件。"""
    sort = args.get("sort", "default")
    if sort not in VALID_SORTS:
        sort = "default"

    try:
        min_length = max(0, int(args.get("min_length", 0) or 0))
    except ValueError:
        min_length = 0

    return {
        "sort": sort,
        "min_length": min_length,
        "start_date": (args.get("start_date") or "").strip(),
        "end_date": (args.get("end_date") or "").strip(),
    }


def _matches_filters(result: dict[str, Any], filters: dict[str, Any]) -> bool:
    date_only = result["timestamp"][:10] if result["timestamp"] else ""

    if result["char_count"] < filters["min_length"]:
        return False
    if filters["start_date"] and date_only and date_only < filters["start_date"]:
        return False
    if filters["end_date"] and date_only and date_only > filters["end_date"]:
        return False
    return True


def _sort_results(results: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    if sort == "time_asc":
        return sorted(results, key=lambda item: item["timestamp"] or "")
    if sort == "time_desc":
        return sorted(results, key=lambda item: item["timestamp"] or "", reverse=True)
    return results


def search_memory(
    sqlite_db: Any,
    vector_db: Any,
    *,
    query: str,
    limit: int | None = None,
    embedder: Any = None,
) -> list[dict[str, Any]]:
    """新检索接口的核心实现。"""
    if not query.strip():
        return []

    embedder = _get_embedder(embedder)
    query_vector = embedder.embed_query(query)
    raw_results = vector_db.search(
        query_vector,
        n_results=limit or settings.default_search_k,
    )

    ids = raw_results.get("ids") or []
    documents = raw_results.get("documents") or []
    metadatas = raw_results.get("metadatas") or []
    distances = raw_results.get("distances") or []

    if not ids or not ids[0]:
        return []

    results: list[dict[str, Any]] = []
    for index, memory_unit_id in enumerate(ids[0]):
        metadata = (metadatas[0][index] if metadatas and metadatas[0] else {}) or {}
        detail = sqlite_db.get_memory_unit_detail(memory_unit_id)
        if detail is None:
            continue

        results.append(
            {
                "memory_unit_id": memory_unit_id,
                "score": distances[0][index] if distances and distances[0] else None,
                "content": documents[0][index] if documents and documents[0] else detail["memory_content"],
                "summary": metadata.get("summary")
                or detail["summary"]
                or build_summary(detail["memory_content"]),
                "preview": build_preview(detail["memory_content"], query),
                "source": detail["source"],
                "source_type": detail["source_type"],
                "title": detail["title"] or "Untitled document",
                "author": detail["author"] or "",
                "created_at": normalize_timestamp(detail["created_at"]),
                "raw_document_id": detail["raw_document_id"],
                "trace": {
                    "raw_document_id": detail["raw_document_id"],
                    "external_id": detail["external_id"],
                    "root_document_id": detail["root_document_id"],
                    "start_char": detail["start_char"],
                    "end_char": detail["end_char"],
                },
            }
        )

    return results[: limit or settings.max_results_display]


def get_memory_unit_payload(sqlite_db: Any, memory_unit_id: str) -> dict[str, Any] | None:
    """返回单个记忆单元的详情，以及它可追溯的原始文档。"""
    detail = sqlite_db.get_memory_unit_detail(memory_unit_id)
    if detail is None:
        return None

    memory_metadata = json.loads(detail["memory_metadata_json"]) if detail["memory_metadata_json"] else {}
    raw_metadata = json.loads(detail["raw_metadata_json"]) if detail["raw_metadata_json"] else {}
    raw_payload = json.loads(detail["raw_payload"]) if detail["raw_payload"] else {}

    return {
        "memory_unit": {
            "memory_unit_id": detail["memory_unit_id"],
            "raw_document_id": detail["raw_document_id"],
            "unit_index": detail["unit_index"],
            "unit_type": detail["unit_type"],
            "content": detail["memory_content"],
            "summary": detail["summary"],
            "start_char": detail["start_char"],
            "end_char": detail["end_char"],
            "embedding_version": detail["embedding_version"],
            "metadata": memory_metadata,
        },
        "raw_document": {
            "raw_document_id": detail["raw_document_id"],
            "source": detail["source"],
            "source_type": detail["source_type"],
            "external_id": detail["external_id"],
            "root_document_id": detail["root_document_id"],
            "title": detail["title"],
            "author": detail["author"],
            "created_at": normalize_timestamp(detail["created_at"]),
            "imported_at": normalize_timestamp(detail["imported_at"]),
            "content": detail["raw_content"],
            "content_hash": detail["content_hash"],
            "metadata": raw_metadata,
            "raw_payload": raw_payload,
        },
    }


def search(sqlite_db: Any, vector_db: Any, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    """兼容旧 UI 的搜索格式。

    旧页面仍然期望拿到 `chunk_id`、`timestamp` 这种字段，
    所以这里把新检索结果转换成旧模板能直接消费的结构。
    """
    search_results = search_memory(
        sqlite_db,
        vector_db,
        query=query,
        limit=settings.default_search_k,
    )

    normalized_results = [
        {
            "chunk_id": item["memory_unit_id"],
            "content": item["content"],
            "preview": item["preview"],
            "title": item["title"],
            "source": item["source"],
            "timestamp": item["created_at"],
            "message_id": item["raw_document_id"],
            "char_count": len(item["content"] or ""),
        }
        for item in search_results
    ]

    filtered_results = [item for item in normalized_results if _matches_filters(item, filters)]
    return _sort_results(filtered_results, filters["sort"])[: settings.max_results_display]
