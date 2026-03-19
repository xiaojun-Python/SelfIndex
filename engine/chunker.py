import re


# def smart_chunking(text, title, role, min_len=30, max_len=500):
#     # 1. 清理数据噪音
#     text = text.strip()
#     if not text or len(text) < 5:  # 过滤掉彻底的废话
#         return []
#
#     prefix = f"[{title}] {role}: "
#
#     # 2. 改进的分隔符：不仅按句号，还按换行符
#     # 这样可以保留对话的自然结构
#     segments = re.split(r'([。！？\n])', text)
#
#     chunks = []
#     current_content = ""
#     start_ptr = 0
#
#     for i in range(0, len(segments) - 1, 2):
#         sentence = segments[i] + segments[i + 1]  # 重新组合句子和标点
#
#         # 如果当前累加的内容太短，就继续往后加（合并短句）
#         if len(current_content) + len(sentence) < max_len:
#             if not current_content:
#                 start_ptr = text.find(sentence)
#             current_content += sentence
#         else:
#             # 只有达到最小长度要求才保存，防止产生“好的”、“嗯”这种碎片
#             if len(current_content.strip()) >= min_len:
#                 chunks.append({
#                     "content": prefix + current_content.strip(),
#                     "start": start_ptr,
#                     "end": start_ptr + len(current_content)
#                 })
#             current_content = sentence
#             start_ptr = text.find(sentence)
#
#     # 处理最后剩下的部分
#     if len(current_content.strip()) >= min_len:
#         chunks.append({
#             "content": prefix + current_content.strip(),
#             "start": start_ptr,
#             "end": start_ptr + len(current_content)
#         })
#
#     return chunks

def smart_chunking(text,  title, role,min_len=30, max_len=500, overlap=1):

    text = text.strip()
    if not text or len(text) < 5:
        return []
    text = text.strip()
    if not text or len(text) < 5:
        return []

    # 切句
    sentences = re.split(r'(?<=[。！？\n])', text)

    chunks = []
    current = []
    current_len = 0
    cursor = 0

    for sentence in sentences:
        s_len = len(sentence)
        if current_len + s_len <= max_len:
            current.append(sentence)
            current_len += s_len
        else:
            content = "".join(current).strip()
            if len(content) >= min_len:
                chunks.append({
                    "content": content,
                    "start": cursor - current_len,
                    "end": cursor
                })

            # overlap
            current = current[-overlap:]
            current_len = sum(len(s) for s in current)

            current.append(sentence)
            current_len += s_len

        cursor += s_len

    # 最后一个chunk
    content = "".join(current).strip()

    if len(content) >= min_len:
        chunks.append({
            "content": content,
            "start": cursor - current_len,
            "end": cursor
        })

    return chunks