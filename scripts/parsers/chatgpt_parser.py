"""ChatGPT / OpenAI 导出解析器。"""

from __future__ import annotations

import ijson

from scripts.format_timestamp import format_timestamp


def parse_format_openai(file_path):
    """逐条读取 OpenAI 导出文件，避免一次性载入超大 JSON。"""
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

            mapping = obj.get("mapping", {})
            messages_to_save = []
            sequence = 0

            for node_id, node_data in mapping.items():
                message_obj = node_data.get("message")
                if not message_obj or not message_obj.get("content"):
                    continue

                parts = message_obj.get("content", {}).get("parts", [])
                text_content = "".join(part for part in parts if isinstance(part, str))
                if not text_content:
                    continue

                raw_role = message_obj.get("author", {}).get("role", "user")
                standard_role = "assistant" if raw_role == "assistant" else "user"
                if raw_role == "system":
                    standard_role = "system"

                messages_to_save.append(
                    {
                        "message_id": str(message_obj.get("id") or node_id),
                        "sub_title": None,
                        "sender_type": standard_role,
                        "content": text_content,
                        "content_length": len(text_content),
                        "model": str(message_obj.get("metadata", {}).get("model_slug", "unknown")),
                        "sequence": sequence,
                        "timestamp": format_timestamp(message_obj.get("create_time")),
                    }
                )
                sequence += 1

            yield conv_meta, messages_to_save
