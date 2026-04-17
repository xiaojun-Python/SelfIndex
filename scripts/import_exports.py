"""导入脚本。

当前这条链路会把导出文件中的消息：
1. 标准化成 raw document
2. 切分成 memory units
3. 写入 SQLite
4. 写入 Chroma 向量索引

典型用途：
    作为 CLI 工具直接运行，用于批量导入 AI 对话平台的导出文件。
    支持的平台：OpenAI (ChatGPT)、DeepSeek、Grok。

使用示例：
    # 完整导入（包括向量索引）
    python -m scripts.import_exports --file ./exports/chatgpt.json

    # 仅导入原始文档和 memory units，跳过向量生成
    python -m scripts.import_exports --file ./exports/chatgpt.json --skip-embedding
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Iterable
from typing import Any

from app.core.settings import settings
from engine.database import DatabaseManager, VectorManager
from engine.memory import build_memory_units, build_raw_document
from scripts.parsers.browser_capture_parser import parse_browser_capture_payload
from scripts.parsers.browser_capture_parser import parse_format_browser_capture
from scripts.parsers.chatgpt_parser import parse_format_openai
from scripts.parsers.deepseek_parser import parse_format_deepseek
from scripts.parsers.grok_parser import parse_format_grok


def select_parser(file_path: str):
    """根据文件名选择对应的解析器。

    当前实现基于文件名字符串匹配进行解析器选择，这是一种简单但有效的启发式方法。
    后续如有需要，可扩展为同时读取文件内容进行格式检测。

    参数:
        file_path: 待解析文件的路径字符串。

    返回:
        对应平台的解析函数：
        - grok  -> parse_format_grok
        - deepseek -> parse_format_deepseek
        - 其他（默认）-> parse_format_openai
    """
    lower_path = file_path.lower()
    if "browser" in lower_path:
        return parse_format_browser_capture
    if "grok" in lower_path:
        return parse_format_grok
    if "deepseek" in lower_path:
        return parse_format_deepseek
    return parse_format_openai


def _as_json_ready(value: Any) -> Any:
    """将不可 JSON 序列化的对象（如 Decimal）递归转换为可序列化类型。

    递归处理嵌套的 dict 和 list 结构，确保所有层级都被转换。

    参数:
        value: 任意类型的待转换值。

    返回:
        转换后的 JSON 兼容值：
        - Decimal -> float
        - dict -> 键值递归转换后的新 dict
        - list -> 元素递归转换后的新 list
        - 其他 -> 原样返回
    """
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _as_json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_json_ready(item) for item in value]
    return value


def _get_embedder(embedder: Any = None) -> Any:
    """获取文本嵌入器（embedder）实例。

    如果调用者已传入 embedder，则直接返回；否则从 embedding_manager 获取全局单例。

    参数:
        embedder: 可选的已初始化 embedder 实例，传入时优先使用。

    返回:
        embedder 实例，用于将文本转换为向量表示。
    """
    if embedder is not None:
        return embedder

    from engine.embedder import embedding_manager

    return embedding_manager


def _minimal_message_payload(message: dict[str, Any]) -> dict[str, Any]:
    """从消息字典中提取最小可用的负载信息。

    仅保留消息的核心元数据字段，过滤掉 content 等大字段，
    以减少存储空间并聚焦于可追溯性所需的最小信息集。

    参数:
        message: 原始消息字典，通常包含 message_id、sender_type、model 等字段。

    返回:
        仅包含核心元数据的字典，包含以下字段：
        - message_id: 消息唯一标识
        - sender_type: 发送者类型（如 user、assistant）
        - model: 使用的 AI 模型名称
        - sequence: 消息在对话中的顺序编号
        - timestamp: 消息创建时间戳
        - parent_message_id: 父消息 id（若存在）
    """
    return {
        "message_id": message.get("message_id"),
        "sender_type": message.get("sender_type"),
        "model": message.get("model"),
        "sequence": message.get("sequence"),
        "timestamp": message.get("timestamp"),
        "parent_message_id": message.get("parent_message_id"),
        "node_id": message.get("node_id"),
        "capture_index": message.get("capture_index"),
    }


def _hash_file(file_path: str | Path) -> str:
    """计算文件的 SHA-256 哈希值。

    采用分块读取方式（每块 1MB）计算哈希，适用于大文件且内存占用可控。

    参数:
        file_path: 文件路径，支持 str 或 Path 类型。

    返回:
        文件内容的 64 位十六进制哈希字符串。
    """
    digest = hashlib.sha256()
    with Path(file_path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sync_sequence_into_json_blob(blob_text: str | None, *, sequence: int, target: str) -> str | None:
    if not blob_text:
        return blob_text
    try:
        payload = json.loads(blob_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return blob_text

    if target == "metadata":
        if isinstance(payload, dict):
            payload["sequence"] = sequence
    elif target == "raw_payload":
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, dict):
                message["sequence"] = sequence

    return json.dumps(payload, ensure_ascii=False)


def _build_browser_sequence_merge_updates(
    *,
    snapshot_messages: list[dict[str, Any]],
    previous_sequence_by_external_id: dict[str, int],
    current_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    snapshot_ids = [
        str(message.get("message_id") or "").strip()
        for message in snapshot_messages
        if str(message.get("message_id") or "").strip()
    ]
    if not snapshot_ids:
        return {"mode": "empty", "anchor_count": 0, "updates": []}

    offsets: list[int] = []
    snapshot_index_by_id: dict[str, int] = {}
    for index, message_id in enumerate(snapshot_ids):
        snapshot_index_by_id[message_id] = index
        previous_sequence = previous_sequence_by_external_id.get(message_id)
        if previous_sequence is None:
            continue
        offsets.append(int(previous_sequence) - index)

    if not offsets:
        return {"mode": "no_anchor", "anchor_count": 0, "updates": []}

    offset = Counter(offsets).most_common(1)[0][0]
    proposed_sequence_by_id = {
        message_id: index + offset for index, message_id in enumerate(snapshot_ids)
    }

    sortable_rows: list[tuple[int, int, int, str, dict[str, Any]]] = []
    for row in current_rows:
        row_sequence = row.get("sequence")
        proposed_sequence = proposed_sequence_by_id.get(row["external_id"], row_sequence)
        sortable_rows.append(
            (
                int(proposed_sequence) if proposed_sequence is not None else 10**12,
                snapshot_index_by_id.get(row["external_id"], 10**12),
                int(row_sequence) if row_sequence is not None else 10**12,
                row["external_id"],
                row,
            )
        )

    sortable_rows.sort(key=lambda item: item[:4])

    updates: list[dict[str, Any]] = []
    for normalized_sequence, (_assigned, _snapshot_index, _current_sequence, _external_id, row) in enumerate(sortable_rows):
        if row.get("sequence") == normalized_sequence:
            continue
        updates.append(
            {
                "raw_document_id": row["raw_document_id"],
                "latest_revision_id": row.get("latest_revision_id"),
                "sequence": normalized_sequence,
                "metadata_json": _sync_sequence_into_json_blob(
                    row.get("metadata_json"),
                    sequence=normalized_sequence,
                    target="metadata",
                ),
                "raw_payload": _sync_sequence_into_json_blob(
                    row.get("raw_payload"),
                    sequence=normalized_sequence,
                    target="raw_payload",
                ),
            }
        )

    return {
        "mode": "anchored_merge",
        "anchor_count": len(offsets),
        "offset": offset,
        "updates": updates,
    }


def _build_test_path(path: Path) -> Path:
    """Return a sibling test path like ``name-test.ext``."""
    return path.with_name(f"{path.stem}-test{path.suffix}")


def _import_conversation_batches(
    conversation_batches: Iterable[tuple[dict[str, Any], list[dict[str, Any]]]],
    *,
    source_name: str,
    file_name: str,
    file_path: str,
    file_hash: str,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager | None,
    embedder: Any = None,
    skip_embedding: bool = False,
) -> dict[str, int]:
    """导入标准化对话消息流，并返回本次写入的数据量。"""
    embedder = None if skip_embedding else _get_embedder(embedder)
    import_id = sqlite_db.create_import_job(
        source=source_name,
        file_name=file_name,
        file_path=file_path,
        file_hash=file_hash,
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
    resequenced_documents = 0
    protected_rules = sqlite_db.list_protected_terms()

    try:
        with sqlite_db.transaction() as conn:
            for conv_meta, messages in conversation_batches:
                browser_payload = bool((conv_meta.get("raw_meta") or {}).get("source_label") == "browser")
                existing_sequence_by_external_id: dict[str, int] = {}
                if browser_payload and conv_meta.get("id"):
                    previous_rows = sqlite_db.list_conversation_raw_documents(
                        source=str(conv_meta.get("source") or "unknown"),
                        source_type="conversation_message",
                        root_document_id=str(conv_meta.get("id")),
                        conn=conn,
                    )
                    existing_sequence_by_external_id = {
                        str(row["external_id"]): int(row["sequence"])
                        for row in previous_rows
                        if row.get("sequence") is not None
                    }

                for message in messages:
                    content = (message.get("content") or "").strip()
                    if not content:
                        continue

                    raw_document = build_raw_document(
                        source=str(conv_meta.get("source") or "unknown"),
                        source_type="conversation_message",
                        external_id=str(message["message_id"]),
                        root_document_id=str(conv_meta.get("id") or "") or None,
                        sequence=message.get("sequence"),
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
                            "parent_message_id": message.get("parent_message_id"),
                            "node_id": message.get("node_id"),
                            "capture_index": message.get("capture_index"),
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

                if browser_payload and conv_meta.get("id"):
                    current_rows = sqlite_db.list_conversation_raw_documents(
                        source=str(conv_meta.get("source") or "unknown"),
                        source_type="conversation_message",
                        root_document_id=str(conv_meta.get("id")),
                        conn=conn,
                    )
                    merge_result = _build_browser_sequence_merge_updates(
                        snapshot_messages=messages,
                        previous_sequence_by_external_id=existing_sequence_by_external_id,
                        current_rows=current_rows,
                    )
                    updates = merge_result.get("updates") or []
                    if updates:
                        sqlite_db.update_raw_document_sequence_fields(updates, conn=conn)
                        resequenced_documents += len(updates)
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
        "resequenced_documents": resequenced_documents,
    }


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
    source_name = parser.__name__.replace("parse_format_", "")
    return _import_conversation_batches(
        parser(str(source_path)),
        source_name=source_name,
        file_name=source_path.name,
        file_path=str(source_path.resolve()),
        file_hash=_hash_file(source_path),
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        embedder=embedder,
        skip_embedding=skip_embedding,
    )


def import_browser_capture_payload(
    payload: dict[str, Any] | list[dict[str, Any]],
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager | None,
    embedder: Any = None,
    skip_embedding: bool = False,
) -> dict[str, int]:
    """导入浏览器扩展直接发送的浏览器对话 payload。"""
    serialized_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    payload_hash = hashlib.sha256(serialized_payload.encode("utf-8")).hexdigest()

    if isinstance(payload, list):
        conversation_id = "batch"
        platform = "browser"
    else:
        conversation_id = str(payload.get("conversation_id") or "unknown").strip() or "unknown"
        platform = str(payload.get("platform") or "browser").strip().lower() or "browser"

    return _import_conversation_batches(
        parse_browser_capture_payload(payload),
        source_name=f"{platform}_browser",
        file_name=f"browser-{platform}-{conversation_id}.json",
        file_path=f"browser://{platform}/{conversation_id}",
        file_hash=payload_hash,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        embedder=embedder,
        skip_embedding=skip_embedding,
    )


# Backward-compatible alias for older route and caller names.
import_chatgpt_browser_payload = import_browser_capture_payload


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import conversation exports into SelfIndex archive and memory layers."
    )
    parser.add_argument("--file", required=True, type=str, help="Path to the exported JSON file.")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Optional database path override. Defaults to SQLITE_DB_PATH.",
    )
    parser.add_argument(
        "--chroma",
        type=str,
        default=None,
        help="Optional Chroma path override. Defaults to CHROMA_DB_PATH.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Write into sibling test database / vector store instead of the main paths.",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Import only raw_documents / memory_units and skip embedding + Chroma indexing.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db_path = Path(args.db) if args.db else settings.sqlite_db_path
    chroma_db_path = Path(args.chroma) if args.chroma else settings.chroma_db_path

    if args.test:
        sqlite_db_path = _build_test_path(sqlite_db_path)
        chroma_db_path = _build_test_path(chroma_db_path)

    sqlite_db = DatabaseManager(sqlite_db_path)
    vector_db = None if args.skip_embedding else VectorManager(chroma_db_path)
    result = import_export_file(
        args.file,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        skip_embedding=args.skip_embedding,
    )
    print(
        "Imported raw documents: "
        f"{result['raw_documents']}, memory units: {result['memory_units']}. "
        f"Database: {sqlite_db_path}"
    )
