"""Versioned JSON API for local desktop and app integrations."""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from app.core.local_auth import valid_write_token
from app.services.capabilities import collect_capabilities
from app.services.documents import DocumentConflictError, DocumentNotFoundError, InvalidDocumentError, save_document
from app.services.source_writeback import SourceWriteConflictError
from engine.database import IndexModelError
from engine.retriever import get_memory_unit_payload, search_memory

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")
logger = logging.getLogger(__name__)

HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    412: "precondition_failed",
    413: "payload_too_large",
    500: "internal_error",
    503: "service_unavailable",
}


def _error(code: str, message: str, status: int):
    return jsonify({"code": code, "message": message}), status


def _http_error(exc: HTTPException):
    status = exc.code or 500
    return _error(HTTP_ERROR_CODES.get(status, "http_error"), exc.description, status)


@bp.errorhandler(Exception)
def _route_error(exc: Exception):
    if isinstance(exc, HTTPException):
        return _http_error(exc)
    if isinstance(exc, IndexModelError):
        return _error("index_unavailable", str(exc), 503)
    logger.exception("Unhandled v1 API error")
    return _error("internal_error", "The request could not be completed.", 500)


def register_error_handlers(app):
    @app.errorhandler(HTTPException)
    def _unmatched_route_error(exc: HTTPException):
        if request.path.startswith("/api/v1/"):
            return _http_error(exc)
        return exc


@bp.before_request
def _local_requests_only():
    if request.remote_addr not in {"127.0.0.1", "::1"}:
        return _error("local_only", "This API only accepts local requests.", 403)
    host = request.host.rsplit(":", 1)[0].strip("[]")
    if host not in {"127.0.0.1", "::1", "localhost"}:
        return _error("local_only", "This API only accepts local requests.", 403)


@bp.get("/health")
def health():
    return jsonify({"ok": True, "service": "selfindex", "version": "0.1.0"})


@bp.get("/status")
def status():
    try:
        capabilities = collect_capabilities(
            current_app.config["SQLITE_DB"],
            current_app.config["VECTOR_DB"],
            current_app.config["SETTINGS"],
            instance_id=current_app.config["INSTANCE_ID"],
        )
    except Exception:
        logger.exception("Service capability snapshot failed")
        return _error("status_unavailable", "Service capability status is unavailable.", 503)
    return jsonify(capabilities)


@bp.get("/search")
def search():
    query = (request.args.get("query") or "").strip()
    if not query:
        return _error("invalid_query", "Query is required.", 400)
    if len(query) > 4096:
        return _error("invalid_query", "Query is too long.", 400)

    limit_text = request.args.get("limit", "10")
    try:
        limit = int(limit_text)
    except ValueError:
        return _error("invalid_limit", "Limit must be an integer from 1 to 50.", 400)
    if not 1 <= limit <= 50:
        return _error("invalid_limit", "Limit must be an integer from 1 to 50.", 400)

    results = search_memory(
        sqlite_db=current_app.config["SQLITE_DB"],
        vector_db=current_app.config["VECTOR_DB"],
        query=query,
        limit=limit,
    )
    return jsonify({"query": query, "count": len(results), "results": results})


@bp.get("/memory/<path:memory_unit_id>")
def memory_detail(memory_unit_id: str):
    payload = get_memory_unit_payload(
        current_app.config["SQLITE_DB"],
        memory_unit_id,
    )
    if payload is None:
        return _error("not_found", "Memory unit not found.", 404)
    return jsonify(payload)


@bp.put("/memory/<path:memory_unit_id>")
def update_memory(memory_unit_id: str):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not valid_write_token(token):
        return _error("unauthorized", "A valid local write token is required.", 401)

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or any(
        not isinstance(data.get(field), str) for field in ("title", "author", "content")
    ):
        return _error("invalid_document", "Title, author and content must be strings.", 400)
    if "expected_revision_id" not in data or "expected_edit_version" not in data:
        return _error("precondition_required", "Expected revision and edit version are required.", 428)
    if (
        not isinstance(data["expected_revision_id"], str)
        or not data["expected_revision_id"]
        or type(data["expected_edit_version"]) is not int
        or data["expected_edit_version"] < 0
    ):
        return _error("invalid_precondition", "Expected revision and edit version are invalid.", 400)

    try:
        result = save_document(
            current_app.config["SQLITE_DB"],
            current_app.config["VECTOR_DB"],
            memory_unit_id,
            title=data["title"],
            author=data["author"],
            content=data["content"],
            expected_revision_id=data["expected_revision_id"],
            expected_edit_version=data["expected_edit_version"],
        )
    except DocumentNotFoundError:
        return _error("not_found", "Memory unit not found.", 404)
    except InvalidDocumentError as exc:
        return _error("invalid_document", str(exc), 400)
    except DocumentConflictError as exc:
        return _error("conflict", str(exc), 409)
    except SourceWriteConflictError as exc:
        return _error("source_conflict", str(exc), 409)

    status = 200 if result["index_status"] == "ready" and result.get("source_status") != "pending" else 202
    return jsonify(result), status
