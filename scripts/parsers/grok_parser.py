import ijson

from scripts.format_timestamp import format_timestamp


def parse_format_grok(file_path):
    with open(file_path, "r", encoding="utf-8") as file_obj:
        objects = ijson.items(file_obj, "conversations.item")

        for obj in objects:
            conv_info = obj.get("conversation", {})
            responses = obj.get("responses", [])

            conv_meta = {
                "id": str(conv_info.get("id", "")),
                "title": str(conv_info.get("title") or "Untitled conversation"),
                "created_at": format_timestamp(conv_info.get("create_time")),
                "source": "Grok",
                "raw_meta": conv_info,
            }

            messages_to_save = []
            for index, item in enumerate(responses):
                response = item.get("response", {})
                content = response.get("message", "")
                if not content:
                    continue

                raw_role = str(response.get("sender", "")).lower()
                standard_role = "assistant" if "assistant" in raw_role or "bot" in raw_role else "user"

                messages_to_save.append(
                    {
                        "message_id": str(response.get("_id")),
                        "sub_title": None,
                        "sender_type": standard_role,
                        "content": str(content),
                        "content_length": len(content),
                        "model": str(response.get("model_slug", "unknown")),
                        "sequence": index,
                        "timestamp": format_timestamp(response.get("create_time")),
                    }
                )

            yield conv_meta, messages_to_save
