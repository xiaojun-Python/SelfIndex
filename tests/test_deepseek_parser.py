from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from scripts.parsers.deepseek_parser import parse_format_deepseek


class DeepSeekParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace_temp_root = Path.cwd() / ".tmp_tests"
        self.workspace_temp_root.mkdir(exist_ok=True)
        self.test_dir = self.workspace_temp_root / self._testMethodName
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_request_and_response_fragments_while_ignoring_think(self) -> None:
        export_path = self.test_dir / "deepseek_export.json"
        export_payload = [
            {
                "id": "conv-1",
                "title": "DeepSeek sample",
                "inserted_at": "2026-04-04T10:00:00.000000+08:00",
                "mapping": {
                    "root": {"id": "root", "parent": None, "children": ["1"], "message": None},
                    "1": {
                        "id": "1",
                        "parent": "root",
                        "children": ["2"],
                        "message": {
                            "model": "deepseek-reasoner",
                            "inserted_at": "2026-04-04T10:00:01.000000+08:00",
                            "fragments": [
                                {"type": "REQUEST", "content": "你好，帮我总结今天的计划。"}
                            ],
                        },
                    },
                    "2": {
                        "id": "2",
                        "parent": "1",
                        "children": [],
                        "message": {
                            "model": "deepseek-reasoner",
                            "inserted_at": "2026-04-04T10:00:02.000000+08:00",
                            "fragments": [
                                {"type": "THINK", "content": "先分析用户需求，再输出简短计划。"},
                                {"type": "RESPONSE", "content": "今天先整理文档，再补解析器测试。"},
                            ],
                        },
                    },
                },
            }
        ]
        export_path.write_text(json.dumps(export_payload, ensure_ascii=False), encoding="utf-8")

        parsed = list(parse_format_deepseek(str(export_path)))

        self.assertEqual(len(parsed), 1)
        conv_meta, messages = parsed[0]
        self.assertEqual(conv_meta["source"], "DeepSeek")
        self.assertEqual(conv_meta["id"], "conv-1")
        self.assertEqual(len(messages), 2)

        self.assertEqual(messages[0]["sender_type"], "user")
        self.assertEqual(messages[0]["message_id"], "conv-1:1")
        self.assertEqual(messages[0]["content"], "你好，帮我总结今天的计划。")

        self.assertEqual(messages[1]["sender_type"], "assistant")
        self.assertEqual(messages[1]["message_id"], "conv-1:2")
        self.assertEqual(messages[1]["content"], "今天先整理文档，再补解析器测试。")
        self.assertIsNone(messages[1]["sub_title"])

    def test_message_ids_are_unique_across_conversations(self) -> None:
        export_path = self.test_dir / "deepseek_export_multi.json"
        export_payload = [
            {
                "id": "conv-a",
                "title": "A",
                "inserted_at": "2026-04-04T10:00:00.000000+08:00",
                "mapping": {
                    "1": {
                        "id": "1",
                        "message": {
                            "model": "deepseek-reasoner",
                            "inserted_at": "2026-04-04T10:00:01.000000+08:00",
                            "fragments": [{"type": "REQUEST", "content": "A1"}],
                        },
                    }
                },
            },
            {
                "id": "conv-b",
                "title": "B",
                "inserted_at": "2026-04-04T11:00:00.000000+08:00",
                "mapping": {
                    "1": {
                        "id": "1",
                        "message": {
                            "model": "deepseek-reasoner",
                            "inserted_at": "2026-04-04T11:00:01.000000+08:00",
                            "fragments": [{"type": "REQUEST", "content": "B1"}],
                        },
                    }
                },
            },
        ]
        export_path.write_text(json.dumps(export_payload, ensure_ascii=False), encoding="utf-8")

        parsed = list(parse_format_deepseek(str(export_path)))
        message_ids = [message["message_id"] for _, messages in parsed for message in messages]

        self.assertEqual(message_ids, ["conv-a:1", "conv-b:1"])


if __name__ == "__main__":
    unittest.main()
