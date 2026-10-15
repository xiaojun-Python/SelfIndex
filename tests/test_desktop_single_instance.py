"""The native desktop entry reuses an existing UI process."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from desktop_mac.main import MainWindow, claim_desktop_instance


class DesktopSingleInstanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_second_start_activates_first_instance(self):
        name = "selfindex-test-" + uuid4().hex
        activations: list[str] = []
        server = claim_desktop_instance(lambda: activations.append("show"), name)
        self.assertIsNotNone(server)
        try:
            second = claim_desktop_instance(lambda: None, name)
            self.assertIsNone(second)
            self.app.processEvents()
            self.assertEqual(activations, ["show"])
        finally:
            server.close()
            QLocalServer.removeServer(name)

    def test_search_home_transitions_to_results_and_back(self):
        with TemporaryDirectory() as temp_dir, patch.object(MainWindow, "_run") as run:
            settings = QSettings(str(Path(temp_dir) / "ui.ini"), QSettings.Format.IniFormat)
            window = MainWindow(settings)
            try:
                self.assertEqual(window.pages.currentIndex(), 0)
                window.home_query.setText("SelfIndex")
                window._search()
                self.assertEqual(window.pages.currentIndex(), 1)
                self.assertEqual(window.query.text(), "SelfIndex")
                self.assertEqual(run.call_count, 2)  # Health check and search.

                window._show_home()
                self.assertEqual(window.pages.currentIndex(), 0)
                self.assertEqual(window.home_query.text(), "")
            finally:
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
