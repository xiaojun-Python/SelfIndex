from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.settings import settings
from engine.embedder import embedding_manager

VALID_SORTS = {"default", "time_asc", "time_desc"}
PREVIEW_LENGTH = 120


def build_preview(text: str, query: str, limit: int = PREVIEW_LENGTH) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""

    keywords = [part.strip() for part in (query or "").split() if part.strip()]
    hit_index = -1
    hit_keyword = ""

    for keyword in keywords:
        idx = cleaned.lower().find(keyword.lower())
        if idx != -1 and (hit_index == -1 or idx < hit_index):
            hit_index = idx
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
    char_count = result["char_count"]
    timestamp = result["timestamp"]
    date_only = timestamp[:10] if timestamp else ""

    if char_count < filters["min_length"]:
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


def _get_message_lengths(sqlite_db: Any, message_ids: list[str]) -> dict[str, int]:
    unique_ids = [message_id for message_id in dict.fromkeys(message_ids) if message_id]
    if not unique_ids:
        return {}

    placeholders = ",".join(["?"] * len(unique_ids))
    query = f"""
        SELECT message_id, content_length
        FROM messages
        WHERE message_id IN ({placeholders})
    """
    with sqlite_db.get_connection() as conn:
        rows = conn.execute(query, unique_ids).fetchall()
    return {row["message_id"]: row["content_length"] or 0 for row in rows}


def search(sqlite_db: Any, vector_db: Any, query: str, filters: dict[str, Any]) -> list[dict[str, Any]]:
    if not query:
        return []

    query_vector = embedding_manager.embed_query(query)
    raw_results = vector_db.search(query_vector, n_results=settings.default_search_k)

    raw_message_ids = []
    if raw_results and raw_results.get("metadatas") and raw_results["metadatas"][0]:
        raw_message_ids = [meta.get("message_id") for meta in raw_results["metadatas"][0] if meta]
    message_lengths = _get_message_lengths(sqlite_db, raw_message_ids)

    search_results = []
    if raw_results and raw_results.get("ids") and raw_results["ids"][0]:
        for index, chunk_id in enumerate(raw_results["ids"][0]):
            content = raw_results["documents"][0][index]
            meta = raw_results["metadatas"][0][index] or {}
            message_id = meta.get("message_id")

            result = {
                "chunk_id": chunk_id,
                "content": content,
                "preview": build_preview(content, query),
                "title": meta.get("title", "Untitled conversation"),
                "source": meta.get("source", "Unknown source"),
                "timestamp": normalize_timestamp(meta.get("timestamp", "")),
                "message_id": message_id,
                "char_count": message_lengths.get(message_id, len(content or "")),
            }

            if _matches_filters(result, filters):
                search_results.append(result)

    return _sort_results(search_results, filters["sort"])[: settings.max_results_display]
