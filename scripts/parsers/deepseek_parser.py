"""DeepSeek JSON export parser."""

from __future__ import annotations

import ijson

from scripts.format_timestamp import format_timestamp


def _join_fragment_contents(fragments: list[dict], fragment_type: str) -> str:
    return "\n\n".join(
        str(fragment.get("content") or "").strip()
        for fragment in fragments
        if str(fragment.get("type") or "").upper() == fragment_type and str(fragment.get("content") or "").strip()
    ).strip()


def _build_message_payload(
    conversation_id: str,
    node_id: str,
    message_obj: dict,
    sequence: int,
) -> dict | None:
    fragments = message_obj.get("fragments") or []
    if not isinstance(fragments, list) or not fragments:
        return None

    request_text = _join_fragment_contents(fragments, "REQUEST")
    response_text = _join_fragment_contents(fragments, "RESPONSE")
    fallback_text = "\n\n".join(
        str(fragment.get("content") or "").strip()
        for fragment in fragments
        if str(fragment.get("type") or "").upper() != "THINK"
        and str(fragment.get("content") or "").strip()
    ).strip()

    if request_text:
        sender_type = "user"
        content = request_text
    else:
        sender_type = "assistant"
        content = response_text or fallback_text

    if not content:
        return None

    return {
        "message_id": f"{conversation_id}:{node_id}",
        "sub_title": None,
        "sender_type": sender_type,
        "content": content,
        "content_length": len(content),
        "model": str(message_obj.get("model") or "unknown"),
        "sequence": sequence,
        "timestamp": format_timestamp(message_obj.get("inserted_at")),
    }


def parse_format_deepseek(file_path):
    """Stream-parse a DeepSeek export file."""
    with open(file_path, "rb") as file_obj:
        objects = ijson.items(file_obj, "item")

        for obj in objects:
            conv_id = obj.get("id", "")
            conversation_id = str(conv_id)
            conv_meta = {
                "id": conversation_id,
                "title": str(obj.get("title") or "Untitled conversation"),
                "created_at": format_timestamp(obj.get("inserted_at")),
                "source": "DeepSeek",
                "raw_meta": obj,
            }

            mapping = obj.get("mapping", {}) or {}
            messages_to_save = []
            sequence = 0

            sortable_nodes = []
            for node_id, node_data in mapping.items():
                message_obj = (node_data or {}).get("message")
                if not message_obj:
                    continue
                sortable_nodes.append(
                    (
                        str(message_obj.get("inserted_at") or ""),
                        str(node_id),
                        message_obj,
                    )
                )

            for _, node_id, message_obj in sorted(sortable_nodes, key=lambda item: (item[0], item[1])):
                payload = _build_message_payload(conversation_id, node_id, message_obj, sequence)
                if payload is None:
                    continue
                messages_to_save.append(payload)
                sequence += 1

            yield conv_meta, messages_to_save
