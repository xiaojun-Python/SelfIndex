"""文本分块逻辑。

当前阶段的目标不是做“最聪明”的 chunk，而是做一个稳定、可解释、可重建的切分器。
"""

from __future__ import annotations

import re


def smart_chunking(
    text: str,
    title: str,
    role: str,
    min_len: int = 30,
    max_len: int = 500,
    overlap: int = 1,
) -> list[dict[str, int | str]]:
    """按句子边界切分文本，并保留原文中的字符区间。

    `title` 和 `role` 目前还没有参与切分逻辑，但保留参数是为了兼容旧调用点，
    也为后续更细的分块策略预留扩展位置。
    """
    _ = title, role

    cleaned = text.strip()
    if len(cleaned) < 5:
        return []

    sentences = re.split(r"(?<=[。！？\n])", cleaned)

    chunks: list[dict[str, int | str]] = []
    current: list[str] = []
    current_len = 0
    cursor = 0

    for sentence in sentences:
        sentence_len = len(sentence)
        if current_len + sentence_len <= max_len:
            current.append(sentence)
            current_len += sentence_len
        else:
            content = "".join(current).strip()
            if len(content) >= min_len:
                chunks.append(
                    {
                        "content": content,
                        "start": cursor - current_len,
                        "end": cursor,
                    }
                )

            # 保留少量重叠句子，避免语义被切得太碎。
            current = current[-overlap:]
            current_len = sum(len(item) for item in current)
            current.append(sentence)
            current_len += sentence_len

        cursor += sentence_len

    content = "".join(current).strip()
    if len(content) >= min_len:
        chunks.append(
            {
                "content": content,
                "start": cursor - current_len,
                "end": cursor,
            }
        )

    return chunks
