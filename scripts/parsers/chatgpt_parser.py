"""ChatGPT / OpenAI json导入解析器。"""

from __future__ import annotations

from collections import defaultdict

import ijson

from scripts.format_timestamp import format_timestamp


def _normalize_role(raw_role: str | None) -> str:
    role = str(raw_role or "user").strip().lower()
    if role == "assistant":
        return "assistant"
    if role == "system":
        return "system"
    return "user"


def _extract_text_content(message_obj: dict) -> str:
    parts = ((message_obj or {}).get("content") or {}).get("parts") or []
    return "".join(part for part in parts if isinstance(part, str)).strip()


def _parent_node_id(mapping: dict, node_id: str) -> str | None:
    parent_id = (mapping.get(node_id) or {}).get("parent")
    if parent_id is None:
        return None
    parent_text = str(parent_id).strip()
    return parent_text or None


def _resolve_parent_message_id(
    mapping: dict,
    node_id: str,
    node_to_message_id: dict[str, str],
) -> str | None:
    current_parent_id = _parent_node_id(mapping, node_id)
    while current_parent_id:
        if current_parent_id in node_to_message_id:
            return node_to_message_id[current_parent_id]
        current_parent_id = _parent_node_id(mapping, current_parent_id)
    return None


def _timestamp_sort_key(value: str | None) -> tuple[int, str]:
    normalized = str(value or "").strip()[:19]
    if normalized:
        return 0, normalized
    return 1, ""


def _try_linear_parent_order(messages: list[dict]) -> list[dict] | None:
    if not messages or not any(message.get("parent_message_id") for message in messages):
        return None

    by_id = {message["message_id"]: message for message in messages}
    child_map: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []

    for message in messages:
        parent_message_id = message.get("parent_message_id")
        if parent_message_id:
            if parent_message_id not in by_id:
                return None
            child_map[parent_message_id].append(message["message_id"])
        else:
            roots.append(message["message_id"])

    if len(roots) != 1:
        return None
    if any(len(child_ids) > 1 for child_ids in child_map.values()):
        return None

    ordered: list[dict] = []
    visited: set[str] = set()
    current_message_id = roots[0]

    while current_message_id:
        if current_message_id in visited:
            return None
        visited.add(current_message_id)
        ordered.append(by_id[current_message_id])
        children = child_map.get(current_message_id) or []
        current_message_id = children[0] if children else ""

    if len(ordered) != len(messages):
        return None
    return ordered


def _ordered_chat_messages(mapping: dict) -> list[dict]:
    message_candidates: list[dict] = []
    node_to_message_id: dict[str, str] = {}

    for capture_index, (node_id, node_data) in enumerate(mapping.items()):
        message_obj = (node_data or {}).get("message")
        if not message_obj or not message_obj.get("content"):
            continue

        text_content = _extract_text_content(message_obj)
        if not text_content:
            continue

        message_id = str(message_obj.get("id") or node_id)
        node_id_text = str(node_id)
        node_to_message_id[node_id_text] = message_id

        message_candidates.append(
            {
                "node_id": node_id_text,
                "message_id": message_id,
                "sub_title": None,
                "sender_type": _normalize_role((message_obj.get("author") or {}).get("role")),
                "content": text_content,
                "content_length": len(text_content),
                "model": str(message_obj.get("metadata", {}).get("model_slug", "unknown")),
                "timestamp": format_timestamp(message_obj.get("create_time")),
                "capture_index": capture_index,
            }
        )

    for candidate in message_candidates:
        candidate["parent_message_id"] = _resolve_parent_message_id(
            mapping,
            candidate["node_id"],
            node_to_message_id,
        )

    ordered_messages = _try_linear_parent_order(message_candidates)
    if ordered_messages is None:
        ordered_messages = sorted(
            message_candidates,
            key=lambda item: (
                _timestamp_sort_key(item.get("timestamp")),
                item.get("capture_index", 0),
                item["message_id"],
            ),
        )

    for sequence, message in enumerate(ordered_messages):
        message["sequence"] = sequence

    return ordered_messages


def parse_format_openai(file_path):
    """逐条读取 OpenAI 导出文件，并按对话结构重建消息顺序。"""
    with open(file_path, "rb") as file_obj:
        objects = ijson.items(file_obj, "item")

        for obj in objects:
            conv_id = obj.get("id") or obj.get("conversation_id")
            conv_meta = {
                "id": str(conv_id),
                "title": str(obj.get("title") or "Untitled conversation"),
                "created_at": format_timestamp(obj.get("create_time")),
                "source": "ChatGPT",
                "raw_meta": obj,
            }

            mapping = obj.get("mapping", {}) or {}
            yield conv_meta, _ordered_chat_messages(mapping)
