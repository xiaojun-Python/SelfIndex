"""Flask 路由。

这里同时承载两类接口：
- 旧 UI 继续使用的 HTML/HTMX 路由
- 新记忆链路暴露出来的最小 JSON API
"""

from __future__ import annotations


from bleach import clean as clean_html
from flask import Blueprint, current_app, jsonify, render_template, request
from markdown import markdown

from app.core.local_auth import get_write_token, valid_write_token
from app.services.documents import DocumentConflictError, DocumentNotFoundError, InvalidDocumentError, save_document
from app.services.source_writeback import SourceWriteConflictError
from engine.retriever import (
    get_memory_unit_payload,
    normalize_timestamp,
    parse_filters,
    search,
    search_memory,
)
from scripts.import_exports import import_browser_capture_payload

bp = Blueprint("main", __name__)

MARKDOWN_ALLOWED_TAGS = {
    "a", "blockquote", "br", "code", "del", "div", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "li", "ol", "p", "pre", "span", "strong",
    "table", "tbody", "td", "th", "thead", "tr", "ul",
}


def _is_local_request() -> bool:
    remote_addr = (request.remote_addr or "").strip()
    host = request.host.rsplit(":", 1)[0].strip("[]")
    return remote_addr in {"", "127.0.0.1", "::1"} and host in {"127.0.0.1", "::1", "localhost"}


@bp.before_request
def _local_requests_only():
    if not _is_local_request():
        return _json_error("Only local requests are allowed.", 403)


def _with_ingest_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
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


def _render_memory_document(memory_unit_id, notice=None):
    """按 memory unit 查看完整原始文档。"""
    sqlite_db = current_app.config["SQLITE_DB"]
    payload = get_memory_unit_payload(sqlite_db, memory_unit_id)
    if payload is None:
        return render_template("document_detail.html", doc=None)

    raw_document = payload["raw_document"]
    metadata = raw_document.get("metadata") or {}
    memory_unit = payload["memory_unit"]
    content_html = clean_html(
        markdown(raw_document["content"], extensions=["extra", "codehilite"]),
        tags=MARKDOWN_ALLOWED_TAGS,
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
        strip_comments=True,
    )

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

    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not valid_write_token(token):
        return _with_ingest_cors(_json_error("A valid local write token is required.", 401))

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

    response = jsonify(
        {
            "ok": True,
            "conversation_id": conversation_id,
            "skip_embedding": skip_embedding,
            **result,
        }
    )
    response.status_code = 202 if result.get("index_status") == "pending" else 200
    return _with_ingest_cors(response)


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
            "expected_revision_id": raw_document["latest_revision_id"],
            "expected_edit_version": raw_document["edit_version"],
            "source_backed": raw_document["source"] == "markdown" and raw_document["source_type"] == "note_file",
            "tags": (raw_document.get("metadata") or {}).get("tags", []),
        },
        write_token=get_write_token(),
    )


@bp.route("/api/document/<chunk_id>", methods=["PUT"])
def update_document(chunk_id):
    """基于新模型保存原始文档，并重建 memory units / vectors。"""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ") or request.form.get("write_token", "")
    if not valid_write_token(token):
        return _json_error("A valid local write token is required.", 401)

    title = request.form.get("title") or ""
    sender = request.form.get("sender") or ""
    content = request.form.get("content") or ""
    try:
        expected_edit_version = int(request.form.get("expected_edit_version", "-1"))
    except ValueError:
        return _json_error("Invalid edit version.", 400)
    try:
        result = save_document(
            current_app.config["SQLITE_DB"],
            current_app.config["VECTOR_DB"],
            chunk_id,
            title=title,
            author=sender,
            content=content,
            expected_revision_id=request.form.get("expected_revision_id"),
            expected_edit_version=expected_edit_version,
        )
    except DocumentNotFoundError:
        return render_template(
            "document_detail.html",
            doc={"notice": "Record not found. It may have been deleted."},
        ), 404
    except InvalidDocumentError as exc:
        return render_template(
            "document_form.html",
            data={"doc_id": chunk_id, "title": title, "sender": sender, "content": content,
                  "tags": [], "error": str(exc),
                  "expected_revision_id": request.form.get("expected_revision_id"),
                  "expected_edit_version": expected_edit_version},
            write_token=get_write_token(),
        ), 400
    except (DocumentConflictError, SourceWriteConflictError) as exc:
        return render_template(
            "document_form.html",
            data={"doc_id": chunk_id, "title": title, "sender": sender, "content": content,
                  "tags": [], "error": str(exc),
                  "expected_revision_id": request.form.get("expected_revision_id"),
                  "expected_edit_version": request.form.get("expected_edit_version")},
            write_token=get_write_token(),
        ), 409
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
                "expected_revision_id": request.form.get("expected_revision_id"),
                "expected_edit_version": expected_edit_version,
            },
            write_token=get_write_token(),
        ), 500

    return _render_memory_document(
        result["memory_unit_id"],
        notice=(
            "Saved to archive, but source-file write is pending."
            if result.get("source_status") == "pending"
            else "Saved. Search indexing is pending."
            if result["index_status"] == "pending"
            else "Saved. Archive, source and search index are in sync."
        ),
    )


@bp.route("/api/metadata/fields")
def get_metadata_fields():
    return jsonify({"fields": ["title", "source", "source_type", "author", "recall_domain"]})


@bp.route("/api/metadata/values/<field>")
def get_metadata_values(field):
    return jsonify({"field": field, "values": []})
