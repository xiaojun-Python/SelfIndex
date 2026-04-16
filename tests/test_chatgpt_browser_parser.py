from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.parsers.chatgpt_browser_parser import parse_format_chatgpt_browser


class ChatGPTBrowserParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

        self.browser_sample_path = self.test_dir / "browser.json"
        self.browser_sample_path.write_text(
            json.dumps(
                {
                    "platform": "chatgpt",
                    "source_label": "browser",
                    "conversation_id": "conv-browser-1",
                    "conversation_title": "Browser Capture",
                    "captured_at": "2026-04-15T10:50:01.531Z",
                    "messages": [
                        {
                            "message_id": "msg-2",
                            "role": "assistant",
                            "model": "gpt-5-4-thinking",
                            "model_slug": "gpt-5-4-thinking",
                            "content": "第二条，**助手回答**。",
                            "timestamp": None,
                            "parent_message_id": "msg-1",
                            "capture_index": 1,
                            "dom_turn_id": "turn-2",
                        },
                        {
                            "message_id": "msg-1",
                            "role": "user",
                            "model": None,
                            "model_slug": None,
                            "content": "第一条，用户提问。",
                            "timestamp": None,
                            "parent_message_id": None,
                            "capture_index": 0,
                            "dom_turn_id": "turn-1",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_browser_parser_orders_by_capture_index_and_preserves_model(self) -> None:
        conv_meta, messages = list(parse_format_chatgpt_browser(str(self.browser_sample_path)))[0]

        self.assertEqual(conv_meta["id"], "conv-browser-1")
        self.assertEqual([message["message_id"] for message in messages], ["msg-1", "msg-2"])
        self.assertEqual([message["sequence"] for message in messages], [0, 1])
        self.assertEqual(messages[1]["model"], "gpt-5-4-thinking")
        self.assertEqual(messages[1]["parent_message_id"], "msg-1")
        self.assertEqual(messages[1]["capture_index"], 1)
        self.assertEqual(messages[1]["node_id"], "turn-2")
        self.assertEqual(messages[1]["content"], "第二条，**助手回答**。")

    def test_browser_parser_preserves_absolute_sequence_for_incremental_payload(self) -> None:
        incremental_sample_path = self.test_dir / "browser-incremental.json"
        incremental_sample_path.write_text(
            json.dumps(
                {
                    "platform": "chatgpt",
                    "source_label": "browser",
                    "conversation_id": "conv-browser-2",
                    "conversation_title": "Browser Incremental Capture",
                    "captured_at": "2026-04-16T09:10:01.531Z",
                    "messages": [
                        {
                            "message_id": "msg-8",
                            "role": "user",
                            "content": "第九条，用户追问。",
                            "capture_index": 8,
                            "dom_turn_id": "turn-8",
                        },
                        {
                            "message_id": "msg-9",
                            "role": "assistant",
                            "model_slug": "gpt-5-4-thinking",
                            "content": "第十条，助手回复。",
                            "capture_index": 9,
                            "dom_turn_id": "turn-9",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        _conv_meta, messages = list(parse_format_chatgpt_browser(str(incremental_sample_path)))[0]

        self.assertEqual([message["message_id"] for message in messages], ["msg-8", "msg-9"])
        self.assertEqual([message["sequence"] for message in messages], [8, 9])

if __name__ == "__main__":
    unittest.main()
