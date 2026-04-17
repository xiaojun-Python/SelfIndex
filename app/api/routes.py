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

from app.core.settings import settings
from engine.memory import build_memory_units, get_content_hash
from engine.retriever import (
    get_memory_unit_payload,
    normalize_timestamp,
    parse_filters,
    search,
    search_memory,
)
from scripts.import_exports import import_browser_capture_payload

bp = Blueprint("main", __name__)
EMBEDDING_VERSION = "bge-small-zh-v1.5"


def _hash_text(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _is_local_request() -> bool:
    remote_addr = (request.remote_addr or "").strip()
    return remote_addr in {"", "127.0.0.1", "::1"}


def _with_ingest_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


def _json_error(message: str, status_code: int):
    response = jsonify({"ok": False, "error": message})
    response.status_code = status_code
    return response


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
    return render_template(
        "search_results.html",
        results=results,
        search_debug=current_app.config["SETTINGS"].search_debug,
    )


def _vector_payload(memory_units: list[dict], raw_document: dict):
    """为新模型下重建后的 memory units 准备向量数据。"""
    from engine.embedder import embedding_manager

    texts = [unit["content"] for unit in memory_units]
    embeddings = embedding_manager.embed_documents(texts) if texts else []
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
    vector_ids = [unit["memory_unit_id"] for unit in memory_units]
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


def _render_memory_document(memory_unit_id, notice=None):
    """按 memory unit 查看完整原始文档。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    payload = get_memory_unit_payload(sqlite_db, memory_unit_id)
    if payload is None:
        return render_template("document_detail.html", doc=None)

    raw_document = payload["raw_document"]
    metadata = raw_document.get("metadata") or {}
    memory_unit = payload["memory_unit"]
    content_html = markdown(raw_document["content"], extensions=["extra", "codehilite"])

    return render_template(
        "document_detail.html",
        doc={
            "doc_id": memory_unit["memory_unit_id"],
            "raw_document_id": raw_document["raw_document_id"],
            "title": raw_document["title"] or "Untitled document",
            "sender": raw_document["author"] or "unknown",
            "timestamp": raw_document["created_at"],
            "content_html": content_html,
            "metadata": {
                **metadata,
                "source": raw_document["source"],
                "source_type": raw_document["source_type"],
                "recall_domain": memory_unit["recall_domain"],
            },
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


@bp.route("/api/ingest/browser-conversation", methods=["GET", "POST", "OPTIONS"])
@bp.route("/api/ingest/chatgpt-browser", methods=["GET", "POST", "OPTIONS"])
def ingest_browser_capture_payload():
    """接收浏览器扩展直接发送的浏览器对话 JSON，并导入 SelfIndex。"""
    if request.method == "OPTIONS":
        return _with_ingest_cors(jsonify({"ok": True}))

    if request.method == "GET":
        return _with_ingest_cors(
            jsonify(
                {
                    "ok": True,
                    "endpoint": "browser-conversation-ingest",
                    "method": "POST",
                    "local_only": True,
                    "message": "Endpoint is available. Send normalized browser conversation JSON via POST.",
                }
            )
        )

    if not _is_local_request():
        return _with_ingest_cors(_json_error("Only local requests are allowed.", 403))

    payload = request.get_json(silent=True)
    if not payload:
        return _with_ingest_cors(_json_error("Missing JSON payload.", 400))

    conversation_id = None
    if isinstance(payload, dict):
        conversation_id = payload.get("conversation_id")
    skip_embedding = bool(request.args.get("skip_embedding", "").strip().lower() in {"1", "true", "yes"})

    try:
        result = import_browser_capture_payload(
            payload,
            sqlite_db=current_app.config["SQLITE_DB"],
            vector_db=None if skip_embedding else current_app.config["VECTOR_DB"],
            skip_embedding=skip_embedding,
        )
    except Exception as exc:
        return _with_ingest_cors(_json_error(f"Import failed: {exc}", 500))

    return _with_ingest_cors(
        jsonify(
            {
                "ok": True,
                "conversation_id": conversation_id,
                "skip_embedding": skip_embedding,
                **result,
            }
        )
    )


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
    return _render_memory_document(chunk_id)


@bp.route("/api/edit/<chunk_id>")
def edit_document(chunk_id):
    """基于新模型的原始文档编辑表单。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    payload = get_memory_unit_payload(sqlite_db, chunk_id)
    if payload is None:
        return render_template("document_form.html", data=None)

    raw_document = payload["raw_document"]

    return render_template(
        "document_form.html",
        data={
            "doc_id": chunk_id,
            "title": raw_document["title"] or "",
            "sender": raw_document["author"] or "",
            "content": raw_document["content"] or "",
            "tags": (raw_document.get("metadata") or {}).get("tags", []),
        },
    )


@bp.route("/api/document/<chunk_id>", methods=["PUT"])
def update_document(chunk_id):
    """基于新模型保存原始文档，并重建 memory units / vectors。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    vector_db = current_app.config["VECTOR_DB"]

    payload = get_memory_unit_payload(sqlite_db, chunk_id)
    if payload is None:
        return render_template(
            "document_detail.html",
            doc={"notice": "Record not found. It may have been deleted."},
        ), 404
    raw_document = payload["raw_document"]

    title = (request.form.get("title") or raw_document["title"] or "").strip() or "Untitled document"
    sender = (request.form.get("sender") or raw_document["author"] or "").strip() or "unknown"
    content = (request.form.get("content") or "").strip()
    if not content:
        return render_template(
            "document_form.html",
            data={
                "doc_id": chunk_id,
                "title": title,
                "sender": sender,
                "content": content,
                "tags": [],
                "error": "Content cannot be empty.",
            },
        ), 400

    existing_units = sqlite_db.get_memory_units_by_raw_document_id(raw_document["raw_document_id"])
    old_memory_unit_ids = [row["memory_unit_id"] for row in existing_units]

    try:
        updated_raw_document = {
            "raw_document_id": raw_document["raw_document_id"],
            "source": raw_document["source"],
            "source_type": raw_document["source_type"],
            "external_id": raw_document["external_id"],
            "root_document_id": raw_document["root_document_id"],
            "sequence": raw_document.get("sequence"),
            "title": title,
            "author": sender,
            "created_at": raw_document["created_at"],
            "content": content,
            "content_hash": get_content_hash(content),
            "raw_payload": json.dumps(raw_document.get("raw_payload") or {}, ensure_ascii=False),
            "metadata_json": json.dumps(raw_document.get("metadata") or {}, ensure_ascii=False),
        }
        upsert_result = sqlite_db.upsert_raw_document(updated_raw_document)
        revision_id = upsert_result["revision_id"]

        if upsert_result["revision_changed"]:
            new_memory_units = build_memory_units(
                updated_raw_document,
                revision_id=revision_id,
                embedding_version=settings.embedding_model,
                protected_rules=sqlite_db.list_protected_terms(),
            )
            sqlite_db.insert_memory_units(new_memory_units)
            previous_revision_id = upsert_result.get("previous_revision_id")
            if previous_revision_id and previous_revision_id != revision_id:
                vector_db.delete_vectors(sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id))
            new_vector_ids, embeddings, metadatas, documents = _vector_payload(
                new_memory_units,
                updated_raw_document,
            )
            if new_vector_ids:
                vector_db.add_vectors(
                    ids=new_vector_ids,
                    embeddings=embeddings,
                    metadatas=metadatas,
                    documents=documents,
                )
                sqlite_db.mark_memory_units_as_embedded(new_vector_ids)
        else:
            new_memory_units = sqlite_db.get_memory_units_by_raw_document_id(
                updated_raw_document["raw_document_id"]
            )
    except Exception as exc:
        return render_template(
            "document_form.html",
            data={
                "doc_id": chunk_id,
                "title": title,
                "sender": sender,
                "content": content,
                "tags": [],
                "error": f"Save failed: {exc}",
            },
        ), 500

    new_first_memory_unit_id = new_memory_units[0]["memory_unit_id"] if new_memory_units else chunk_id
    return _render_memory_document(
        new_first_memory_unit_id,
        notice="Saved. SQLite and Chroma are now in sync.",
    )


@bp.route("/api/metadata/fields")
def get_metadata_fields():
    return jsonify({"fields": ["title", "source", "source_type", "author", "recall_domain"]})


@bp.route("/api/metadata/values/<field>")
def get_metadata_values(field):
    return jsonify({"field": field, "values": []})
