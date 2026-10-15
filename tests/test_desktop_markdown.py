"""Markdown reading and raw editing stay separate in the desktop detail pane."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from desktop_mac.main import MainWindow


class DesktopMarkdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        ui_settings = QSettings(str(Path(self.temp_dir.name) / "ui.ini"), QSettings.Format.IniFormat)
        self.runner = patch.object(MainWindow, "_run")
        self.run = self.runner.start()
        self.window = MainWindow(ui_settings)
        self.window.current_memory_id = "memory-1"
        self.window._set_detail_enabled(True)
        self.original = "# 标题\n\n**加粗** 和 `代码`\n\n- 第一项\n- 第二项"
        self.window._detail_ready(
            {
                "memory_unit": {"content": "summary"},
                "raw_document": {
                    "title": "我的笔记",
                    "author": "作者",
                    "content": self.original,
                    "created_at": "2026-09-26",
                },
            },
            "memory-1",
            self.window.detail_generation,
        )

    def tearDown(self):
        self.window.deleteLater()
        self.runner.stop()
        self.temp_dir.cleanup()

    def test_reading_renders_markdown_and_editing_shows_source(self):
        self.assertEqual(self.window.content_stack.currentIndex(), 0)
        self.assertFalse(self.window.view_header.isHidden())
        self.assertIn("加粗", self.window.content_preview.toPlainText())
        self.assertNotIn("**加粗**", self.window.content_preview.toPlainText())
        self.assertEqual(self.window.content_field.toPlainText(), self.original)

        self.window._begin_edit()
        self.assertEqual(self.window.content_stack.currentIndex(), 1)
        self.assertFalse(self.window.editor_meta.isHidden())
        self.window.title_field.setText("临时标题")
        self.window.content_field.setPlainText("# 未保存")
        self.window._cancel_edit()

        self.assertEqual(self.window.content_stack.currentIndex(), 0)
        self.assertEqual(self.window.title_view.text(), "我的笔记")
        self.assertEqual(self.window.content_field.toPlainText(), self.original)

    def test_successful_save_returns_to_rendered_preview(self):
        self.window._begin_edit()
        self.window.title_field.setText("新标题")
        self.window.content_field.setPlainText("## 新内容\n\n**已保存**")
        self.window._save()
        self.assertFalse(self.window.content_field.isEnabled())
        operation, on_success, _on_failure = self.run.call_args.args
        self.assertTrue(callable(operation))
        on_success((200, {"memory_unit_id": "memory-2", "index_status": "ready"}))

        self.assertEqual(self.window.current_memory_id, "memory-2")
        self.assertEqual(self.window.content_stack.currentIndex(), 0)
        self.assertEqual(self.window.title_view.text(), "新标题")
        self.assertIn("已保存", self.window.content_preview.toPlainText())
        self.assertNotIn("**已保存**", self.window.content_preview.toPlainText())
        self.assertEqual(self.window.content_field.toPlainText(), "## 新内容\n\n**已保存**")

    def test_failed_save_keeps_editable_source(self):
        self.window._begin_edit()
        self.window.content_field.setPlainText("# 草稿")
        self.window._save()
        _operation, _on_success, on_failure = self.run.call_args.args
        on_failure("网络中断")

        self.assertEqual(self.window.content_stack.currentIndex(), 1)
        self.assertTrue(self.window.content_field.isEnabled())
        self.assertEqual(self.window.content_field.toPlainText(), "# 草稿")
        self.assertIn("网络中断", self.window.index_state.text())

    def test_markdown_resources_are_not_loaded_and_file_links_do_not_open(self):
        preview = self.window.content_preview
        resource_type = QTextDocument.ResourceType.ImageResource
        self.assertIsNone(preview.loadResource(resource_type, QUrl("file:///tmp/private.png")))
        self.assertIsNone(preview.loadResource(resource_type, QUrl("https://example.org/tracker.png")))
        with patch("desktop_mac.main.QDesktopServices.openUrl") as open_url:
            self.window._open_markdown_link(QUrl("file:///tmp/private.txt"))
            self.window._open_markdown_link(QUrl("javascript:alert(1)"))
        open_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
