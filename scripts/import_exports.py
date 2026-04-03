"""导入脚本。

当前这条链路会把导出文件中的消息：
1. 标准化成 raw document
2. 切分成 memory units
3. 写入 SQLite
4. 写入 Chroma 向量索引
"""

from __future__ import annotations

import argparse
import hashlib
import json
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


def _minimal_message_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": message.get("message_id"),
        "sender_type": message.get("sender_type"),
        "model": message.get("model"),
        "sequence": message.get("sequence"),
        "timestamp": message.get("timestamp"),
    }


def _hash_file(file_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def import_export_file(
    file_path: str | Path,
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager | None,
    embedder: Any = None,
    skip_embedding: bool = False,
) -> dict[str, int]:
    """导入单个导出文件，并返回本次写入的数据量。"""
    source_path = Path(file_path)
    parser = select_parser(str(source_path))
    embedder = None if skip_embedding else _get_embedder(embedder)
    source_name = parser.__name__.replace("parse_format_", "")
    import_id = sqlite_db.create_import_job(
        source=source_name,
        file_name=source_path.name,
        file_path=str(source_path.resolve()),
        file_hash=_hash_file(source_path),
        import_config_json=json.dumps(
            {
                "embedding_model": settings.embedding_model,
                "embedding_enabled": not skip_embedding,
                "protected_terms_source": "database",
            },
            ensure_ascii=False,
        ),
        notes="Imported without embeddings." if skip_embedding else None,
    )

    imported_documents = 0
    imported_memory_units = 0
    protected_rules = sqlite_db.list_protected_terms()

    try:
        with sqlite_db.transaction() as conn:
            for conv_meta, messages in parser(str(source_path)):
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
                            "message": _as_json_ready(_minimal_message_payload(message)),
                        },
                        metadata={
                            "model": message.get("model"),
                            "sequence": message.get("sequence"),
                            "sub_title": message.get("sub_title"),
                            "conversation": {
                                "id": conv_meta.get("id"),
                                "title": conv_meta.get("title"),
                                "created_at": conv_meta.get("created_at"),
                                "source": conv_meta.get("source"),
                            },
                        },
                    )

                    upsert_result = sqlite_db.upsert_raw_document(raw_document, conn=conn)
                    revision_id = upsert_result["revision_id"]

                    if upsert_result["revision_changed"]:
                        memory_units = build_memory_units(
                            raw_document,
                            revision_id=revision_id,
                            embedding_version=settings.embedding_model,
                            protected_rules=protected_rules,
                        )
                        sqlite_db.insert_memory_units(memory_units, conn=conn)
                    else:
                        memory_units = sqlite_db.get_memory_units_by_raw_document_id(
                            raw_document["raw_document_id"]
                        )

                    previous_revision_id = upsert_result.get("previous_revision_id")
                    if (
                        previous_revision_id
                        and previous_revision_id != revision_id
                        and vector_db is not None
                    ):
                        vector_db.delete_vectors(
                            sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id)
                        )

                    if (
                        upsert_result["revision_changed"]
                        and memory_units
                        and vector_db is not None
                        and embedder is not None
                    ):
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
                                "recall_domain": unit.get("recall_domain") or "default",
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
                            [unit["memory_unit_id"] for unit in memory_units],
                            conn=conn,
                        )

                    imported_documents += 1
                    imported_memory_units += len(memory_units)
    except Exception as exc:
        sqlite_db.finish_import_job(
            import_id,
            status="failed",
            raw_documents_count=imported_documents,
            memory_units_count=imported_memory_units,
            error_message=str(exc),
        )
        raise

    sqlite_db.finish_import_job(
        import_id,
        status="success",
        raw_documents_count=imported_documents,
        memory_units_count=imported_memory_units,
    )

    return {
        "import_id": import_id,
        "raw_documents": imported_documents,
        "memory_units": imported_memory_units,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import conversation exports into SelfIndex archive and memory layers."
    )
    parser.add_argument("--file", required=True, type=str, help="Path to the exported JSON file.")
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Import only raw_documents / memory_units and skip embedding + Chroma indexing.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(settings.sqlite_db_path)
    vector_db = None if args.skip_embedding else VectorManager(settings.chroma_db_path)
    result = import_export_file(
        args.file,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        skip_embedding=args.skip_embedding,
    )
    print(
        "Imported raw documents: "
        f"{result['raw_documents']}, memory units: {result['memory_units']}"
    )
