from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import unittest
from pathlib import Path

from scripts.audit_chatgpt_order import (
    audit_chatgpt_conversation,
    build_order_view,
    fetch_database_conversation_bundle,
    load_browser_sample_bundles,
    load_chatgpt_export_bundles,
)
from scripts.parsers.chatgpt_parser import parse_format_openai


def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


class ChatGPTOrderAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.export_path = self.test_dir / "chatgpt_order_export.json"
        self.export_path.write_text(
            json.dumps(
                [
                    {
                        "id": "conv-1",
                        "title": "Out of order mapping",
                        "create_time": "2026-04-10T10:00:00",
                        "mapping": {
                            "root": {
                                "id": "root",
                                "parent": None,
                                "children": ["node-user"],
                                "message": None,
                            },
                            "node-assistant": {
                                "id": "node-assistant",
                                "parent": "node-user",
                                "children": [],
                                "message": {
                                    "id": "msg-2",
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["第二条，助手回答。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T10:00:02",
                                },
                            },
                            "node-user": {
                                "id": "node-user",
                                "parent": "root",
                                "children": ["node-assistant"],
                                "message": {
                                    "id": "msg-1",
                                    "author": {"role": "user"},
                                    "content": {"parts": ["第一条，用户提问。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T10:00:01",
                                },
                            },
                        },
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.branch_export_path = self.test_dir / "chatgpt_branch_export.json"
        self.branch_export_path.write_text(
            json.dumps(
                [
                    {
                        "id": "conv-branch",
                        "title": "Branching conversation",
                        "create_time": "2026-04-10T11:00:00",
                        "mapping": {
                            "root": {
                                "id": "root",
                                "parent": None,
                                "children": ["node-user"],
                                "message": None,
                            },
                            "node-user": {
                                "id": "node-user",
                                "parent": "root",
                                "children": ["node-assistant-a", "node-assistant-b"],
                                "message": {
                                    "id": "msg-10",
                                    "author": {"role": "user"},
                                    "content": {"parts": ["这是一条会分支的用户消息。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T11:00:01",
                                },
                            },
                            "node-assistant-a": {
                                "id": "node-assistant-a",
                                "parent": "node-user",
                                "children": [],
                                "message": {
                                    "id": "msg-11",
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["分支 A。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T11:00:02",
                                },
                            },
                            "node-assistant-b": {
                                "id": "node-assistant-b",
                                "parent": "node-user",
                                "children": [],
                                "message": {
                                    "id": "msg-12",
                                    "author": {"role": "assistant"},
                                    "content": {"parts": ["分支 B。"]},
                                    "metadata": {"model_slug": "gpt-4.1"},
                                    "create_time": "2026-04-10T11:00:03",
                                },
                            },
                        },
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.browser_sample_path = self.test_dir / "chatgpt_browser_sample.json"
        self.browser_sample_path.write_text(
            json.dumps(
                [
                    {
                        "platform": "chatgpt",
                        "conversation_id": "conv-1",
                        "message_id": "msg-1",
                        "parent_message_id": None,
                        "role": "user",
                        "content": "第一条，用户提问。",
                        "content_hash": _content_hash("第一条，用户提问。"),
                        "timestamp": None,
                        "sequence": None,
                        "capture_index": 0,
                        "source_label": "browser",
                    },
                    {
                        "platform": "chatgpt",
                        "conversation_id": "conv-1",
                        "message_id": "msg-2",
                        "parent_message_id": None,
                        "role": "assistant",
                        "content": "第二条，助手回答。",
                        "content_hash": _content_hash("第二条，助手回答。"),
                        "timestamp": None,
                        "sequence": None,
                        "capture_index": 1,
                        "source_label": "browser",
                    },
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_database_from_current_parser(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """
            CREATE TABLE raw_documents (
                raw_document_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_type TEXT NOT NULL,
                external_id TEXT NOT NULL,
                root_document_id TEXT,
                author TEXT,
                created_at TEXT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                raw_payload TEXT,
                metadata_json TEXT
            )
            """
        )

        conv_meta, messages = list(parse_format_openai(str(self.export_path)))[0]
        for message in messages:
            raw_document_id = f"chatgpt:conversation_message:{message['message_id']}"
            conn.execute(
                """
                INSERT INTO raw_documents (
                    raw_document_id,
                    source,
                    source_type,
                    external_id,
                    root_document_id,
                    author,
                    created_at,
                    content,
                    content_hash,
                    is_active,
                    raw_payload,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    raw_document_id,
                    "ChatGPT",
                    "conversation_message",
                    message["message_id"],
                    conv_meta["id"],
                    message["sender_type"],
                    message["timestamp"],
                    message["content"],
                    _content_hash(message["content"]),
                    json.dumps(
                        {
                            "message": {
                                "message_id": message["message_id"],
                                "timestamp": message["timestamp"],
                                "sequence": message["sequence"],
                            }
                        },
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        {
                            "sequence": message["sequence"],
                            "conversation": {
                                "id": conv_meta["id"],
                                "title": conv_meta["title"],
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
            )

        return conn

    def test_reference_export_rebuild_differs_from_current_parser_order(self) -> None:
        _, parser_messages = list(parse_format_openai(str(self.export_path)))[0]
        self.assertEqual([item["message_id"] for item in parser_messages], ["msg-2", "msg-1"])

        export_bundle = load_chatgpt_export_bundles(self.export_path)["conv-1"]
        export_view = build_order_view(export_bundle)

        self.assertEqual(export_view.order_strategy, "parent_message_id")
        self.assertEqual(export_view.message_ids, ["msg-1", "msg-2"])

    def test_audit_distinguishes_parser_issue_from_storage_gap(self) -> None:
        conn = self._create_database_from_current_parser()
        self.addCleanup(conn.close)

        database_bundle = fetch_database_conversation_bundle(conn, "conv-1")
        export_bundle = load_chatgpt_export_bundles(self.export_path)["conv-1"]

        report = audit_chatgpt_conversation(
            "conv-1",
            database_bundle=database_bundle,
            export_bundle=export_bundle,
        )

        self.assertTrue(report["diagnosis"]["parser_ordering_issue"])
        self.assertFalse(report["diagnosis"]["storage_field_gap"])
        self.assertTrue(report["diagnosis"]["sortable_retrieval_supported"])
        self.assertTrue(report["comparisons"]["database_vs_export"]["order_conflicts"])

    def test_browser_sample_uses_capture_index_without_timestamps(self) -> None:
        browser_bundle = load_browser_sample_bundles(self.browser_sample_path)["conv-1"]
        browser_view = build_order_view(browser_bundle)
        export_bundle = load_chatgpt_export_bundles(self.export_path)["conv-1"]

        report = audit_chatgpt_conversation(
            "conv-1",
            export_bundle=export_bundle,
            browser_bundle=browser_bundle,
        )

        self.assertEqual(browser_view.order_strategy, "capture_index")
        self.assertEqual(browser_view.missing_timestamps, ["msg-1", "msg-2"])
        self.assertEqual(report["comparisons"]["browser_vs_export"]["order_conflicts"], [])
        self.assertFalse(report["diagnosis"]["browser_capture_gap"])

    def test_browser_duplicates_are_reported(self) -> None:
        duplicate_path = self.test_dir / "chatgpt_browser_duplicate.json"
        duplicate_path.write_text(
            json.dumps(
                json.loads(self.browser_sample_path.read_text(encoding="utf-8"))
                + [
                    {
                        "platform": "chatgpt",
                        "conversation_id": "conv-1",
                        "message_id": "msg-2",
                        "parent_message_id": None,
                        "role": "assistant",
                        "content": "第二条，助手回答。",
                        "content_hash": _content_hash("第二条，助手回答。"),
                        "timestamp": None,
                        "sequence": None,
                        "capture_index": 2,
                        "source_label": "browser",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        browser_bundle = load_browser_sample_bundles(duplicate_path)["conv-1"]
        browser_view = build_order_view(browser_bundle)

        self.assertEqual(browser_view.duplicates, ["msg-2"])

    def test_branching_export_marks_linearization_ambiguity(self) -> None:
        export_bundle = load_chatgpt_export_bundles(self.branch_export_path)["conv-branch"]
        export_view = build_order_view(export_bundle)

        ambiguity_types = [item["type"] for item in export_view.linearization_ambiguities]
        self.assertIn("branching_children", ambiguity_types)


if __name__ == "__main__":
    unittest.main()
