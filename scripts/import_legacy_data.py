"""导入脚本。

当前这条链路会把导出文件中的消息：
1. 标准化成 raw document
2. 切分成 memory units
3. 写入 SQLite
4. 写入 Chroma 向量索引
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.settings import settings
from engine.database import DatabaseManager, VectorManager
from engine.memory import build_memory_units, build_raw_document
from scripts.parsers.chatgpt_parser import parse_format_openai
from scripts.parsers.deepseek_parser import parse_format_deepseek
from scripts.parsers.grok_parser import parse_format_grok


def select_parser(file_path: str):
    """根据文件名做一个当前阶段足够简单的解析器选择。"""
    lower_path = file_path.lower()
    if "grok" in lower_path:
        return parse_format_grok
    if "deepseek" in lower_path:
        return parse_format_deepseek
    return parse_format_openai


def _as_json_ready(value: Any) -> Any:
    """把 Decimal 等对象转换为可序列化的普通结构。"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _as_json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_json_ready(item) for item in value]
    return value


def _get_embedder(embedder: Any = None) -> Any:
    if embedder is not None:
        return embedder

    from engine.embedder import embedding_manager

    return embedding_manager


def import_export_file(
    file_path: str | Path,
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager,
    embedder: Any = None,
) -> dict[str, int]:
    """导入单个导出文件，并返回本次写入的数据量。"""
    parser = select_parser(str(file_path))
    embedder = _get_embedder(embedder)

    imported_documents = 0
    imported_memory_units = 0

    for conv_meta, messages in parser(str(file_path)):
        for message in messages:
            content = (message.get("content") or "").strip()
            if not content:
                continue

            raw_document = build_raw_document(
                source=str(conv_meta.get("source") or "unknown"),
                source_type="conversation_message",
                external_id=str(message["message_id"]),
                root_document_id=str(conv_meta.get("id") or "") or None,
                title=conv_meta.get("title"),
                author=message.get("sender_type"),
                created_at=message.get("timestamp") or conv_meta.get("created_at"),
                content=content,
                raw_payload={
                    "conversation": _as_json_ready(conv_meta),
                    "message": _as_json_ready(message),
                },
                metadata={
                    "model": message.get("model"),
                    "sequence": message.get("sequence"),
                    "sub_title": message.get("sub_title"),
                },
            )

            memory_units = build_memory_units(
                raw_document,
                embedding_version=settings.embedding_model,
            )

            sqlite_db.upsert_raw_document(raw_document)
            old_memory_unit_ids = sqlite_db.replace_memory_units(
                raw_document["raw_document_id"],
                memory_units,
            )

            if old_memory_unit_ids:
                vector_db.delete_vectors(old_memory_unit_ids)

            if memory_units:
                texts = [unit["content"] for unit in memory_units]
                embeddings = embedder.embed_documents(texts)
                metadatas = [
                    {
                        "memory_unit_id": unit["memory_unit_id"],
                        "raw_document_id": unit["raw_document_id"],
                        "title": raw_document.get("title") or "Untitled document",
                        "source": raw_document["source"],
                        "source_type": raw_document["source_type"],
                        "author": raw_document.get("author") or "",
                        "created_at": raw_document.get("created_at") or "",
                        "summary": unit.get("summary") or "",
                    }
                    for unit in memory_units
                ]
                vector_db.add_vectors(
                    ids=[unit["memory_unit_id"] for unit in memory_units],
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=texts,
                )
                sqlite_db.mark_memory_units_as_embedded(
                    [unit["memory_unit_id"] for unit in memory_units]
                )

            imported_documents += 1
            imported_memory_units += len(memory_units)

    return {
        "raw_documents": imported_documents,
        "memory_units": imported_memory_units,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import conversation exports into SelfIndex archive and memory layers."
    )
    parser.add_argument("--file", required=True, type=str, help="Path to the exported JSON file.")
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(settings.sqlite_db_path)
    vector_db = VectorManager(settings.chroma_db_path)
    result = import_export_file(
        args.file,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
    )
    print(
        "Imported raw documents: "
        f"{result['raw_documents']}, memory units: {result['memory_units']}"
    )
