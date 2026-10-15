"""Browser ingestion requires the same local write token as desktop edits."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from app.api.routes import bp


class IngestAuthTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "app" / "templates"))
        app.config["TESTING"] = True
        app.config["SQLITE_DB"] = object()
        app.config["VECTOR_DB"] = object()
        app.register_blueprint(bp)
        self.client = app.test_client()

    def test_preflight_allows_authorization_header(self):
        response = self.client.options("/api/ingest/browser-conversation")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Authorization", response.headers["Access-Control-Allow-Headers"])

    def test_write_without_token_is_rejected_before_import(self):
        with patch("app.api.routes.valid_write_token", return_value=False), patch(
            "app.api.routes.import_browser_capture_payload"
        ) as import_payload:
            response = self.client.post(
                "/api/ingest/browser-conversation",
                json={"conversation_id": "test"},
            )
        self.assertEqual(response.status_code, 401)
        import_payload.assert_not_called()

    def test_valid_token_allows_import(self):
        with patch("app.api.routes.valid_write_token", return_value=True), patch(
            "app.api.routes.import_browser_capture_payload",
            return_value={"raw_documents": 1},
        ) as import_payload:
            response = self.client.post(
                "/api/ingest/browser-conversation",
                headers={"Authorization": "Bearer local-token"},
                json={"conversation_id": "test"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        import_payload.assert_called_once()

    def test_archived_but_pending_index_returns_202(self):
        with patch("app.api.routes.valid_write_token", return_value=True), patch(
            "app.api.routes.import_browser_capture_payload",
            return_value={"raw_documents": 1, "index_status": "pending"},
        ):
            response = self.client.post(
                "/api/ingest/browser-conversation",
                headers={"Authorization": "Bearer local-token"},
                json={"conversation_id": "test"},
            )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["index_status"], "pending")

    def test_legacy_edit_rejects_missing_token(self):
        with patch("app.api.routes.save_document") as save:
            response = self.client.put("/api/document/test-id", data={"content": "edited"})
        self.assertEqual(response.status_code, 401)
        save.assert_not_called()

    def test_legacy_markdown_detail_strips_active_html(self):
        content = (
            "# Safe heading\n\n**Bold text** [safe](https://example.com) "
            "[unsafe](javascript:alert(1))\n\n"
            "| A | B |\n| - | - |\n| 1 | 2 |\n\n"
            "```python\nprint('safe')\n```\n\n"
            "<script>alert('script')</script>"
            "<img src=x onerror=alert(1)>"
            "<a href='https://example.com' onclick='alert(1)'>raw link</a>"
            "<iframe src='https://example.com'></iframe>"
            "<svg onload='alert(1)'><circle /></svg>"
        )
        payload = {
            "memory_unit": {"memory_unit_id": "unit-1", "recall_domain": "default"},
            "raw_document": {
                "raw_document_id": "raw-1", "title": "Title", "author": "A",
                "created_at": "", "content": content, "metadata": {}, "source": "test",
                "source_type": "note",
            },
        }
        with patch("app.api.routes.get_memory_unit_payload", return_value=payload):
            response = self.client.get("/api/view/unit-1")
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("<h1>Safe heading</h1>", html)
        self.assertIn("<strong>Bold text</strong>", html)
        self.assertIn("<table>", html)
        self.assertIn("print", html)
        self.assertIn('href="https://example.com"', html)
        for unsafe in ("<script", "<img", "<iframe", "<svg", "onload=", "onerror=", "onclick=", "javascript:"):
            self.assertNotIn(unsafe, html)

    def test_legacy_edit_form_embeds_token_and_can_save(self):
        payload = {"raw_document": {
            "title": "Title", "author": "A", "content": "Body", "metadata": {},
            "latest_revision_id": "revision-1", "edit_version": 1,
            "source": "test", "source_type": "note",
        }}
        with patch("app.api.routes.get_memory_unit_payload", return_value=payload), patch(
            "app.api.routes.get_write_token", return_value="local-token"
        ):
            response = self.client.get("/api/edit/test-id")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="write_token" value="local-token"', response.data)

        with patch("app.api.routes.valid_write_token", return_value=True) as check, patch(
            "app.api.routes.save_document", return_value={"memory_unit_id": "new-id", "index_status": "ready"}
        ) as save, patch("app.api.routes._render_memory_document", return_value="saved"):
            response = self.client.put(
                "/api/document/test-id",
                data={"write_token": "local-token", "title": "Title", "sender": "A", "content": "Body",
                      "expected_revision_id": "revision-1", "expected_edit_version": "1"},
            )
        self.assertEqual(response.status_code, 200)
        check.assert_called_once_with("local-token")
        save.assert_called_once()

    def test_legacy_routes_reject_nonlocal_host(self):
        response = self.client.get("/api/edit/test-id", headers={"Host": "other.example"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
