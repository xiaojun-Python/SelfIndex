from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.parsers.chatgpt_parser import parse_format_openai


class ChatGPTParserOrderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.export_path = self.test_dir / "chatgpt_export.json"
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

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parser_rebuilds_linear_order_from_parent_chain(self) -> None:
        _, messages = list(parse_format_openai(str(self.export_path)))[0]

        self.assertEqual([message["message_id"] for message in messages], ["msg-1", "msg-2"])
        self.assertEqual([message["sequence"] for message in messages], [0, 1])
        self.assertIsNone(messages[0]["parent_message_id"])
        self.assertEqual(messages[1]["parent_message_id"], "msg-1")


if __name__ == "__main__":
    unittest.main()
