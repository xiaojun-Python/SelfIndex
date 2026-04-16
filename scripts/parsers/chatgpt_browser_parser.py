"""ChatGPT 浏览器捕获 JSON 导入解析器。"""

from __future__ import annotations

import json
from typing import Any

from scripts.format_timestamp import format_timestamp
from scripts.parsers.chatgpt_parser import _normalize_role


def _normalize_capture_index(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _normalize_sequence(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ordered_browser_messages(raw_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_messages: list[dict[str, Any]] = []

    for fallback_index, item in enumerate(raw_messages):
        content = str(item.get("content") or "").strip()
        if not content:
            continue

        capture_index = _normalize_capture_index(item.get("capture_index"), fallback_index)
        sequence = _normalize_sequence(item.get("sequence"))
        model_slug = str(item.get("model_slug") or item.get("model") or "unknown").strip()
        sort_sequence = sequence if sequence is not None else capture_index

        normalized_messages.append(
            {
                "message_id": str(item.get("message_id") or "").strip(),
                "sub_title": None,
                "sender_type": _normalize_role(item.get("role")),
                "content": content,
                "content_length": len(content),
                "model": model_slug or "unknown",
                "sequence": sequence,
                "timestamp": format_timestamp(item.get("timestamp")),
                "parent_message_id": item.get("parent_message_id"),
                "node_id": str(item.get("dom_turn_id") or item.get("message_id") or "").strip() or None,
                "capture_index": capture_index,
                "sort_sequence": sort_sequence,
            }
        )

    ordered_messages = sorted(
        normalized_messages,
        key=lambda item: (
            item.get("sort_sequence", 0),
            item.get("capture_index", 0),
            item.get("message_id") or "",
        ),
    )

    next_sequence = 0
    for message in ordered_messages:
        if message["sequence"] is None:
            message["sequence"] = message.get("sort_sequence", next_sequence)
        next_sequence = max(next_sequence, int(message["sequence"]) + 1)
        message.pop("sort_sequence", None)

    return ordered_messages


def parse_chatgpt_browser_payload(payload: Any):
    """解析内存中的 ChatGPT 浏览器捕获 payload。"""
    if isinstance(payload, list):
        conversation_payloads = payload
    else:
        conversation_payloads = [payload]

    for obj in conversation_payloads:
        conversation_id = str(obj.get("conversation_id") or obj.get("id") or "").strip()
        conv_meta = {
            "id": conversation_id,
            "title": str(obj.get("conversation_title") or obj.get("title") or "Untitled conversation"),
            "created_at": format_timestamp(obj.get("captured_at") or obj.get("created_at")),
            "source": "ChatGPT",
            "raw_meta": obj,
        }

        raw_messages = obj.get("messages") or []
        yield conv_meta, _ordered_browser_messages(raw_messages)


def parse_format_chatgpt_browser(file_path: str):
    """解析 ChatGPT 浏览器扩展导出的标准化 JSON。"""
    with open(file_path, encoding="utf-8") as file_obj:
        payload = json.load(file_obj)

    yield from parse_chatgpt_browser_payload(payload)
