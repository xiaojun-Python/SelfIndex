"""Editing actions preserve drafts while navigation or save is in progress."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from desktop_mac.main import DockReopenFilter, MainWindow


class DesktopEditGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.runner = patch.object(MainWindow, "_run")
        self.run = self.runner.start()
        self.addCleanup(self.runner.stop)
        settings = QSettings(str(Path(self.temp_dir.name) / "ui.ini"), QSettings.IniFormat)
        self.window = MainWindow(settings)
        self.window.show()
        self.window.pages.setCurrentIndex(1)
        self.window.query.setText("synthetic")
        self.window._search_ready(
            {"results": [{"memory_unit_id": "unit-1", "title": "Note"}]},
            self.window.search_generation,
        )
        self.window._detail_ready(
            {"memory_unit": {}, "raw_document": {
                "title": "Note", "author": "Writer", "content": "Original",
            }},
            "unit-1", self.window.detail_generation,
        )
        self.addCleanup(self._close_window)

    def _close_window(self):
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def _edit_draft(self):
        self.window._begin_edit()
        self.window.content_field.setPlainText("Draft")

    def test_search_icon_cancel_keeps_draft(self):
        self._edit_draft()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.window.workspace_search_button.click()
        self.assertEqual(self.window.current_memory_id, "unit-1")
        self.assertEqual(self.window.content_field.toPlainText(), "Draft")
        self.assertEqual(self.window.content_stack.currentIndex(), 1)

    def test_discard_before_search_drops_draft_explicitly(self):
        self._edit_draft()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Discard):
            self.window.workspace_search_button.click()
        self.assertIsNone(self.window.current_memory_id)
        self.assertEqual(self.window.content_stack.currentIndex(), 0)
        self.assertEqual(self.window.state.text(), "正在搜索…")

    def test_save_before_search_waits_for_result(self):
        self._edit_draft()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Save):
            self.window.workspace_search_button.click()
        self.assertTrue(self.window._saving)
        self.assertEqual(self.window.current_memory_id, "unit-1")
        self.assertFalse(self.window.save_button.isEnabled())
        _operation, success, _failure = self.run.call_args.args
        self.window._search()
        self.assertEqual(self.window.current_memory_id, "unit-1")
        success((200, {"memory_unit_id": "unit-2", "index_status": "ready"}))
        self.assertFalse(self.window._saving)
        self.assertIsNone(self.window.current_memory_id)
        self.assertEqual(self.window.state.text(), "正在搜索…")

    def test_failed_save_cancels_navigation_and_restores_actions(self):
        self._edit_draft()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Save):
            self.window._search()
        _operation, _success, failure = self.run.call_args.args
        failure("offline")
        self.assertIsNone(self.window._pending_navigation)
        self.assertEqual(self.window.current_memory_id, "unit-1")
        self.assertEqual(self.window.content_field.toPlainText(), "Draft")
        self.assertTrue(self.window.save_button.isEnabled())
        self.assertTrue(self.window.cancel_button.isEnabled())

    def test_quit_cancel_and_save(self):
        self._edit_draft()
        with patch.object(self.app, "quit") as quit_app:
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
                self.window._request_quit()
            quit_app.assert_not_called()
            with patch.object(QMessageBox, "question", return_value=QMessageBox.Save):
                self.window._request_quit()
            quit_app.assert_not_called()
            _operation, success, _failure = self.run.call_args.args
            success((200, {"memory_unit_id": "unit-2", "index_status": "ready"}))
            quit_app.assert_called_once()

    def test_application_quit_event_uses_draft_guard(self):
        self._edit_draft()
        app_filter = DockReopenFilter(self.window)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.Cancel):
            self.assertTrue(app_filter.eventFilter(self.app, QEvent(QEvent.Type.Quit)))
        self.assertFalse(self.window._quit_authorized)
        self.assertEqual(self.window.content_field.toPlainText(), "Draft")

    def test_server_normalized_document_is_displayed(self):
        self.window._begin_edit()
        self.window.title_field.setText("  Name  ")
        self.window.author_field.setText("  ")
        self.window.content_field.setPlainText("  body  ")
        self.window._save()
        _operation, success, _failure = self.run.call_args.args
        success((200, {
            "memory_unit_id": "unit-2", "index_status": "ready",
            "document": {"title": "Name", "author": "unknown", "content": "body"},
        }))
        self.assertEqual(self.window.loaded_detail["title"], "Name")
        self.assertEqual(self.window.loaded_detail["author"], "unknown")
        self.assertEqual(self.window.loaded_detail["content"], "body")
        self.assertEqual(self.window.list.item(0).text().splitlines()[:2], ["Name", "body"])


if __name__ == "__main__":
    unittest.main()
