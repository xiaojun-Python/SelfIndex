"""Contract tests for the versioned local desktop JSON API."""

from __future__ import annotations

import unittest
from urllib.parse import quote
from unittest.mock import Mock, patch

from flask import Flask

from app.api import v1
from app.services.documents import DocumentConflictError, DocumentNotFoundError, InvalidDocumentError


class DesktopApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sqlite_db = Mock(name="sqlite_db")
        self.vector_db = Mock(name="vector_db")
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLITE_DB=self.sqlite_db,
            VECTOR_DB=self.vector_db,
        )
        self.app.register_blueprint(v1.bp)
        v1.register_error_handlers(self.app)
        self.client = self.app.test_client()

    def assert_json_error(self, response, status_code: int) -> dict:
        self.assertEqual(response.status_code, status_code)
        payload = response.get_json()
        self.assertIsInstance(payload, dict)
        self.assertEqual(set(payload), {"code", "message"})
        self.assertTrue(payload["code"])
        self.assertTrue(payload["message"])
        return payload

    def test_health_returns_versioned_service_metadata(self) -> None:
        response = self.client.get("/api/v1/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"ok": True, "service": "selfindex", "version": "0.1.0"},
        )

    def test_unmatched_path_and_method_return_json(self) -> None:
        self.assertEqual(self.assert_json_error(self.client.get("/api/v1/missing"), 404)["code"], "not_found")
        self.assertEqual(self.assert_json_error(self.client.post("/api/v1/health"), 405)["code"], "method_not_allowed")

    def test_unexpected_search_failure_is_safe_json(self) -> None:
        with patch.object(v1, "search_memory", side_effect=RuntimeError("private backend detail")):
            with self.assertLogs("app.api.v1", level="ERROR"):
                response = self.client.get("/api/v1/search?query=test")
        payload = self.assert_json_error(response, 500)
        self.assertEqual(payload["code"], "internal_error")
        self.assertNotIn("private backend detail", payload["message"])

    def test_oversized_request_returns_json(self) -> None:
        self.app.config["MAX_CONTENT_LENGTH"] = 8
        with patch.object(v1, "valid_write_token", return_value=True):
            response = self.client.put(
                "/api/v1/memory/mu-42", data=b"0123456789",
                content_type="application/json", headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(self.assert_json_error(response, 413)["code"], "payload_too_large")

    def test_search_returns_engine_results_and_requested_query(self) -> None:
        results = [
            {"memory_unit_id": "mu-1", "content": "contract result", "score": 0.91}
        ]
        with patch.object(v1, "search_memory", return_value=results) as search_memory:
            response = self.client.get(
                "/api/v1/search?query=  contract%20test%20&limit=7"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json(),
            {"query": "contract test", "count": 1, "results": results},
        )
        search_memory.assert_called_once_with(
            sqlite_db=self.sqlite_db,
            vector_db=self.vector_db,
            query="contract test",
            limit=7,
        )

    def test_search_without_query_returns_structured_400(self) -> None:
        with patch.object(v1, "search_memory") as search_memory:
            response = self.client.get("/api/v1/search")

        payload = self.assert_json_error(response, 400)
        self.assertEqual(payload["code"], "invalid_query")
        search_memory.assert_not_called()

    def test_search_with_invalid_limit_returns_structured_400(self) -> None:
        with patch.object(v1, "search_memory") as search_memory:
            for limit in ("abc", "0", "-1", "51", "1.5"):
                with self.subTest(limit=limit):
                    response = self.client.get(
                        "/api/v1/search", query_string={"query": "test", "limit": limit}
                    )
                    payload = self.assert_json_error(response, 400)
                    self.assertEqual(payload["code"], "invalid_limit")

        search_memory.assert_not_called()

    def test_memory_detail_returns_memory_unit_and_raw_document(self) -> None:
        payload = {
            "memory_unit": {"memory_unit_id": "mu-42", "content": "remember this"},
            "raw_document": {"raw_document_id": "doc-9", "content": "original text"},
        }
        with patch.object(v1, "get_memory_unit_payload", return_value=payload) as get_payload:
            response = self.client.get("/api/v1/memory/mu-42")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)
        get_payload.assert_called_once_with(self.sqlite_db, "mu-42")

    def test_memory_detail_accepts_percent_encoded_slash_in_memory_id(self) -> None:
        memory_unit_id = "markdown:note_file:folder/note.md:hash:0"
        payload = {
            "memory_unit": {"memory_unit_id": memory_unit_id},
            "raw_document": {"raw_document_id": "markdown:note_file:folder/note.md"},
        }
        with patch.object(v1, "get_memory_unit_payload", return_value=payload) as get_payload:
            response = self.client.get(f"/api/v1/memory/{quote(memory_unit_id, safe='')}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), payload)
        get_payload.assert_called_once_with(self.sqlite_db, memory_unit_id)

    def test_unknown_memory_returns_structured_404(self) -> None:
        with patch.object(v1, "get_memory_unit_payload", return_value=None) as get_payload:
            response = self.client.get("/api/v1/memory/missing")

        payload = self.assert_json_error(response, 404)
        self.assertEqual(payload["code"], "not_found")
        get_payload.assert_called_once_with(self.sqlite_db, "missing")

    def test_versioned_api_rejects_non_local_requests(self) -> None:
        paths = (
            "/api/v1/health",
            "/api/v1/search?query=test",
            "/api/v1/memory/mu-42",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(
                    path, environ_base={"REMOTE_ADDR": "203.0.113.10"}
                )
                payload = self.assert_json_error(response, 403)
                self.assertEqual(payload["code"], "local_only")

    def test_update_without_bearer_token_returns_401(self) -> None:
        with patch.object(v1, "valid_write_token", return_value=False) as valid_token:
            with patch.object(v1, "save_document") as save_document:
                response = self.client.put(
                    "/api/v1/memory/mu-42",
                    json={"title": "Title", "author": "Author", "content": "Text"},
                )

        payload = self.assert_json_error(response, 401)
        self.assertEqual(payload["code"], "unauthorized")
        valid_token.assert_called_once_with("")
        save_document.assert_not_called()

    def test_update_with_valid_token_returns_save_result(self) -> None:
        document = {"title": "Updated", "author": "Me", "content": "New text",
                    "expected_revision_id": "r1", "expected_edit_version": 0}
        result = {"memory_unit_id": "mu-42", "index_status": "ready", "revision_id": "r2"}
        with patch.object(v1, "valid_write_token", return_value=True) as valid_token:
            with patch.object(v1, "save_document", return_value=result) as save_document:
                response = self.client.put(
                    "/api/v1/memory/mu-42",
                    json=document,
                    headers={"Authorization": "Bearer test-write-token"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), result)
        valid_token.assert_called_once_with("test-write-token")
        save_document.assert_called_once_with(
            self.sqlite_db,
            self.vector_db,
            "mu-42",
            title="Updated",
            author="Me",
            content="New text",
            expected_revision_id="r1",
            expected_edit_version=0,
        )

    def test_update_with_pending_index_returns_202(self) -> None:
        result = {"memory_unit_id": "mu-42", "index_status": "pending"}
        with patch.object(v1, "valid_write_token", return_value=True):
            with patch.object(v1, "save_document", return_value=result):
                response = self.client.put(
                    "/api/v1/memory/mu-42",
                    json={"title": "Title", "author": "Author", "content": "Text",
                          "expected_revision_id": "r1", "expected_edit_version": 0},
                    headers={"Authorization": "Bearer test-write-token"},
                )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), result)

    def test_update_with_invalid_json_returns_400(self) -> None:
        with patch.object(v1, "valid_write_token", return_value=True):
            with patch.object(v1, "save_document") as save_document:
                response = self.client.put(
                    "/api/v1/memory/mu-42",
                    data="{invalid json",
                    content_type="application/json",
                    headers={"Authorization": "Bearer test-write-token"},
                )

        payload = self.assert_json_error(response, 400)
        self.assertEqual(payload["code"], "invalid_document")
        save_document.assert_not_called()

    def test_update_with_empty_content_returns_400(self) -> None:
        with patch.object(v1, "valid_write_token", return_value=True):
            with patch.object(
                v1, "save_document", side_effect=InvalidDocumentError("Content cannot be empty.")
            ) as save_document:
                response = self.client.put(
                    "/api/v1/memory/mu-42",
                    json={"title": "Title", "author": "Author", "content": "",
                          "expected_revision_id": "r1", "expected_edit_version": 0},
                    headers={"Authorization": "Bearer test-write-token"},
                )

        payload = self.assert_json_error(response, 400)
        self.assertEqual(payload["code"], "invalid_document")
        save_document.assert_called_once()

    def test_update_of_unknown_memory_returns_404(self) -> None:
        with patch.object(v1, "valid_write_token", return_value=True):
            with patch.object(
                v1, "save_document", side_effect=DocumentNotFoundError("not found")
            ) as save_document:
                response = self.client.put(
                    "/api/v1/memory/missing",
                    json={"title": "Title", "author": "Author", "content": "Text",
                          "expected_revision_id": "r1", "expected_edit_version": 0},
                    headers={"Authorization": "Bearer test-write-token"},
                )

        payload = self.assert_json_error(response, 404)
        self.assertEqual(payload["code"], "not_found")
        save_document.assert_called_once()

    def test_update_requires_preconditions_and_reports_conflict(self) -> None:
        with patch.object(v1, "valid_write_token", return_value=True), patch.object(v1, "save_document") as save_document:
            missing = self.client.put(
                "/api/v1/memory/mu-42",
                json={"title": "Title", "author": "Author", "content": "Text"},
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(self.assert_json_error(missing, 428)["code"], "precondition_required")
        save_document.assert_not_called()

        with patch.object(v1, "valid_write_token", return_value=True), patch.object(
            v1, "save_document", side_effect=DocumentConflictError("Changed since opened.")
        ):
            conflict = self.client.put(
                "/api/v1/memory/mu-42",
                json={"title": "Title", "author": "Author", "content": "Text",
                      "expected_revision_id": "r1", "expected_edit_version": 0},
                headers={"Authorization": "Bearer test"},
            )
        self.assertEqual(self.assert_json_error(conflict, 409)["code"], "conflict")


if __name__ == "__main__":
    unittest.main()
