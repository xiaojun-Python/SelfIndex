"""Flask 路由。

这里同时承载两类接口：
- 旧 UI 继续使用的 HTML/HTMX 路由
- 新记忆链路暴露出来的最小 JSON API
"""

from __future__ import annotations

import hashlib
import json

from flask import Blueprint, current_app, jsonify, render_template, request
from markdown import markdown

from engine.chunker import smart_chunking
from engine.retriever import (
    get_memory_unit_payload,
    normalize_timestamp,
    parse_filters,
    search,
    search_memory,
)

bp = Blueprint("main", __name__)
EMBEDDING_VERSION = "bge-small-zh-v1.5"


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _render_search_results():
    """兼容旧模板的搜索结果渲染。"""
    query = (request.args.get("query") or "").strip()
    filters = parse_filters(request.args)
    results = search(
        sqlite_db=current_app.config["SQLITE_DB"],
        vector_db=current_app.config["VECTOR_DB"],
        query=query,
        filters=filters,
    )
    return render_template("search_results.html", results=results)


def _build_chunks_for_message(content: str) -> list[dict]:
    """旧 UI 编辑消息后，重新生成对应的 chunks。"""
    chunks = smart_chunking(content, "", "")
    if not chunks and content.strip():
        stripped = content.strip()
        chunks = [{"content": stripped, "start": 0, "end": len(stripped)}]

    return [
        {
            "chunk_index": index,
            "start_char": chunk["start"],
            "end_char": chunk["end"],
            "content": chunk["content"],
            "hash": _hash_text(chunk["content"]),
            "embedding_version": EMBEDDING_VERSION,
        }
        for index, chunk in enumerate(chunks)
    ]


def _vector_payload(chunk_rows: list[dict], message_row: dict, conversation_row: dict):
    """为旧 UI 编辑保存后的 chunk 重新准备向量数据。"""
    from engine.embedder import embedding_manager

    texts = [chunk["content"] for chunk in chunk_rows]
    embeddings = embedding_manager.embed_documents(texts) if texts else []
    metadatas = [
        {
            "message_id": message_row["message_id"],
            "title": conversation_row["title"] or "Untitled conversation",
            "source": conversation_row["source"] or "Unknown source",
            "timestamp": message_row["timestamp"] or "",
        }
        for _ in chunk_rows
    ]
    vector_ids = [str(chunk["chunk_id"]) for chunk in chunk_rows]
    return vector_ids, embeddings, metadatas, texts


def _restore_vectors(vector_db, old_vector_state):
    """编辑失败回滚时，把旧向量重新放回去。"""
    old_ids = old_vector_state.get("ids") or []
    if not old_ids:
        return

    vector_db.add_vectors(
        ids=old_ids,
        embeddings=old_vector_state.get("embeddings") or [],
        metadatas=old_vector_state.get("metadatas") or [],
        documents=old_vector_state.get("documents") or [],
    )


def _render_document_by_chunk(chunk_id, notice=None):
    """兼容旧 UI：按 chunk 查看完整消息。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    detail = sqlite_db.get_message_detail_by_chunk(chunk_id)
    if not detail:
        return render_template("document_detail.html", doc=None)

    try:
        extra_meta = json.loads(detail["raw_meta"]) if detail["raw_meta"] else {}
    except json.JSONDecodeError:
        extra_meta = {}

    merged_meta = {**extra_meta, "source": detail["source"], "model": detail["model"]}
    content_html = markdown(detail["content"], extensions=["extra", "codehilite"])

    return render_template(
        "document_detail.html",
        doc={
            "doc_id": chunk_id,
            "message_id": detail["message_id"],
            "title": detail["title"],
            "sender": detail["sender_type"],
            "timestamp": normalize_timestamp(detail["timestamp"]),
            "content_html": content_html,
            "metadata": merged_meta,
            "notice": notice,
        },
    )


@bp.route("/api/search")
def search_view():
    return _render_search_results()


@bp.route("/api/update_filters")
def update_filters():
    return _render_search_results()


@bp.route("/api/memory/search")
def search_memory_view():
    """新版最小检索接口。"""
    query = (request.args.get("query") or "").strip()
    try:
        limit = max(1, min(int(request.args.get("limit", 10)), 50))
    except ValueError:
        limit = 10

    results = search_memory(
        sqlite_db=current_app.config["SQLITE_DB"],
        vector_db=current_app.config["VECTOR_DB"],
        query=query,
        limit=limit,
    )
    return jsonify({"query": query, "count": len(results), "results": results})


@bp.route("/api/memory/<memory_unit_id>")
def memory_unit_detail(memory_unit_id):
    """返回记忆单元和原始文档的完整回溯信息。"""
    payload = get_memory_unit_payload(
        current_app.config["SQLITE_DB"],
        memory_unit_id,
    )
    if payload is None:
        return jsonify({"error": "Memory unit not found."}), 404
    return jsonify(payload)


@bp.route("/api/view/<chunk_id>")
def view_document(chunk_id):
    return _render_document_by_chunk(chunk_id)


@bp.route("/api/edit/<chunk_id>")
def edit_document(chunk_id):
    """兼容旧 UI 的编辑表单。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    detail = sqlite_db.get_message_detail_by_chunk(chunk_id)
    if not detail:
        return render_template("document_form.html", data=None)

    try:
        extra_meta = json.loads(detail["raw_meta"]) if detail["raw_meta"] else {}
    except json.JSONDecodeError:
        extra_meta = {}

    return render_template(
        "document_form.html",
        data={
            "doc_id": chunk_id,
            "message_id": detail["message_id"],
            "conversation_id": detail["conversation_id"],
            "title": detail["title"] or "",
            "sender": detail["sender_type"] or "",
            "content": detail["content"] or "",
            "tags": extra_meta.get("tags", []),
        },
    )


@bp.route("/api/document/<chunk_id>", methods=["PUT"])
def update_document(chunk_id):
    """兼容旧 UI 的消息编辑保存。

    这部分仍然基于旧的 messages/chunks 表工作，后续如果全面切到新模型，
    可以再把它统一收敛。
    """
    sqlite_db = current_app.config["SQLITE_DB"]
    vector_db = current_app.config["VECTOR_DB"]

    detail = sqlite_db.get_message_detail_by_chunk(chunk_id)
    if not detail:
        return render_template(
            "document_detail.html",
            doc={"notice": "Record not found. It may have been deleted."},
        ), 404

    title = (request.form.get("title") or detail["title"] or "").strip() or "Untitled conversation"
    sender = (request.form.get("sender") or detail["sender_type"] or "").strip() or "unknown"
    content = (request.form.get("content") or "").strip()
    if not content:
        return render_template(
            "document_form.html",
            data={
                "doc_id": chunk_id,
                "message_id": detail["message_id"],
                "conversation_id": detail["conversation_id"],
                "title": title,
                "sender": sender,
                "content": content,
                "tags": [],
                "error": "Content cannot be empty.",
            },
        ), 400

    old_chunks = [dict(row) for row in sqlite_db.get_chunks_by_message_id(detail["message_id"])]
    old_chunk_ids = [str(chunk["chunk_id"]) for chunk in old_chunks]
    old_vector_state = vector_db.get_vectors(old_chunk_ids)

    snapshot = {
        "conversation": {
            "conversation_id": detail["conversation_id"],
            "title": detail["title"],
        },
        "message": {
            "message_id": detail["message_id"],
            "sender_type": detail["sender_type"],
            "content": detail["content"],
            "content_length": detail["content_length"],
            "content_hash": detail["content_hash"],
        },
        "chunks": old_chunks,
    }

    new_chunks = _build_chunks_for_message(content)
    new_content_hash = _hash_text(content)

    try:
        inserted_chunks = sqlite_db.replace_message_and_chunks(
            message_id=detail["message_id"],
            conversation_id=detail["conversation_id"],
            title=title,
            sender=sender,
            content=content,
            content_hash=new_content_hash,
            chunk_rows=new_chunks,
        )

        updated_message = {
            "message_id": detail["message_id"],
            "timestamp": detail["timestamp"],
        }
        updated_conversation = {
            "title": title,
            "source": detail["source"],
        }
        new_vector_ids, embeddings, metadatas, documents = _vector_payload(
            inserted_chunks,
            updated_message,
            updated_conversation,
        )

        vector_db.delete_vectors(old_chunk_ids)
        if new_vector_ids:
            vector_db.add_vectors(
                ids=new_vector_ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents,
            )
            sqlite_db.mark_chunks_as_processed([chunk["chunk_id"] for chunk in inserted_chunks])
    except Exception as exc:
        try:
            sqlite_db.restore_message_snapshot(snapshot)
            if "inserted_chunks" in locals():
                vector_db.delete_vectors([str(chunk["chunk_id"]) for chunk in inserted_chunks])
            _restore_vectors(vector_db, old_vector_state)
        except Exception:
            return render_template(
                "document_form.html",
                data={
                    "doc_id": chunk_id,
                    "message_id": detail["message_id"],
                    "conversation_id": detail["conversation_id"],
                    "title": title,
                    "sender": sender,
                    "content": content,
                    "tags": [],
                    "error": "Save failed and automatic rollback also failed.",
                },
            ), 500

        return render_template(
            "document_form.html",
            data={
                "doc_id": chunk_id,
                "message_id": detail["message_id"],
                "conversation_id": detail["conversation_id"],
                "title": title,
                "sender": sender,
                "content": content,
                "tags": [],
                "error": f"Save failed and changes were rolled back: {exc}",
            },
        ), 500

    new_first_chunk_id = inserted_chunks[0]["chunk_id"] if inserted_chunks else chunk_id
    return _render_document_by_chunk(
        new_first_chunk_id,
        notice="Saved. SQLite and Chroma are now in sync.",
    )


@bp.route("/api/metadata/fields")
def get_metadata_fields():
    return jsonify({"fields": ["title", "source", "sender_type", "model"]})


@bp.route("/api/metadata/values/<field>")
def get_metadata_values(field):
    return jsonify({"field": field, "values": []})
