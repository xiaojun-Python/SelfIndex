"""Grok json导入解析器。

该模块负责解析 Grok AI 导出的对话数据文件（JSON 格式），
并将其转换为标准化的对话数据结构，便于后续存储和处理。

主要功能：
    - 流式解析 Grok 导出的 JSON 文件
    - 提取对话元信息（ID、标题、创建时间等）
    - 提取消息列表（角色、内容、时间戳等）
    - 将非标准角色名称映射为标准角色（user/assistant）
"""

from __future__ import annotations

import ijson

from scripts.format_timestamp import format_timestamp


def parse_format_grok(file_path: str):
    """解析 Grok 导出的对话文件。

    该函数以流式方式解析 Grok 导出的 JSON 文件，提取每个对话的元信息和消息列表。
    使用 ijson 库进行增量解析，适合处理大型导出文件。

    Args:
        file_path: Grok 导出文件的路径，应为 JSON 格式。

    Yields:
        tuple[dict, list[dict]]: 包含两个元素的元组：
            - conv_meta: 对话元信息字典，包含以下键值：
                - id (str): 对话唯一标识符
                - title (str): 对话标题，若为空则使用 "Untitled conversation"
                - created_at (str): 格式化后的创建时间
                - source (str): 数据来源标识，固定为 "Grok"
                - raw_meta (dict): 原始对话元数据的完整副本
            - messages_to_save: 消息列表，每个消息为字典，包含：
                - message_id (str): 消息唯一标识符
                - sub_title (None): 保留字段，此处始终为 None
                - sender_type (str): 标准化后的发送者角色，"user" 或 "assistant"
                - content (str): 消息内容
                - content_length (int): 消息内容长度
                - model (str): 使用的 AI 模型标识
                - sequence (int): 消息在对话中的顺序索引
                - timestamp (str): 格式化后的消息创建时间

    Raises:
        FileNotFoundError: 当指定的文件路径不存在时由 ijson 抛出。
        ijson.JSONError: 当文件内容不是有效的 JSON 格式时抛出。

    Example:
        >>> for conv_meta, messages in parse_format_grok("grok_export.json"):
        ...     print(f"对话: {conv_meta['title']}")
        ...     for msg in messages:
        ...         print(f"  {msg['sender_type']}: {msg['content'][:50]}...")
    """
    with open(file_path, "rb") as file_obj:
        # 使用 ijson 的 items 方法流式提取 "conversations" 数组中的每个对话对象
        # "conversations.item" 表示遍历 conversations 数组的每个元素
        objects = ijson.items(file_obj, "conversations.item")

        for obj in objects:
            # 提取当前对话的元信息
            conv_info = obj.get("conversation", {})
            # 提取当前对话的所有响应消息
            responses = obj.get("responses", [])

            # 构建对话元信息字典
            conv_meta = {
                "id": str(conv_info.get("id", "")),
                "title": str(conv_info.get("title") or "Untitled conversation"),
                "created_at": format_timestamp(conv_info.get("create_time")),
                "source": "Grok",
                "raw_meta": conv_info,
            }

            # 存储当前对话中需要保存的消息
            messages_to_save = []
            for index, item in enumerate(responses):
                # 获取当前响应对象
                response = item.get("response", {})
                # 获取消息内容，若为空则跳过
                content = response.get("message", "")
                if not content:
                    continue

                # 将 Grok 的角色名称映射为标准角色名称
                # Grok 中 "assistant" 或 "bot" 开头的角色归类为 assistant，其余为 user
                raw_role = str(response.get("sender", "")).lower()
                standard_role = (
                    "assistant"
                    if "assistant" in raw_role or "bot" in raw_role
                    else "user"
                )

                # 构建标准化的消息结构
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
