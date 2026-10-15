"""Desktop layout preferences survive a new window instance."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray, QSettings
from PySide6.QtWidgets import QApplication

from desktop_mac.main import MainWindow


class DesktopPreferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_window_size_and_splitter_restore_after_restart(self):
        with TemporaryDirectory() as temp_dir, patch.object(MainWindow, "_run"):
            path = str(Path(temp_dir) / "ui.ini")
            first = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            first.resize(780, 600)
            first.show()
            first.pages.setCurrentIndex(1)
            self.app.processEvents()
            first.splitter.setSizes([240, 480])
            self.app.processEvents()
            original_size = first.size()
            original_split = first.splitter.sizes()
            first.close()
            self.assertFalse(first.isVisible())
            saved_keys = QSettings(path, QSettings.Format.IniFormat).allKeys()
            self.assertEqual(saved_keys, ["window/geometry", "window/splitter"])
            first.deleteLater()

            second = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            try:
                second.show()
                second.pages.setCurrentIndex(1)
                self.app.processEvents()
                self.assertEqual(second.size(), original_size)
                restored_split = second.splitter.sizes()
                self.assertAlmostEqual(
                    restored_split[0] / sum(restored_split),
                    original_split[0] / sum(original_split),
                    delta=0.03,
                )
                self.assertEqual(second.home_query.text(), "")
            finally:
                second.hide()
                second.deleteLater()

    def test_home_only_session_preserves_previous_splitter_ratio(self):
        with TemporaryDirectory() as temp_dir, patch.object(MainWindow, "_run"):
            path = str(Path(temp_dir) / "ui.ini")
            first = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            first.show()
            first.pages.setCurrentIndex(1)
            self.app.processEvents()
            first.splitter.setSizes([300, 400])
            self.app.processEvents()
            first.close()
            first.deleteLater()

            expected = QSettings(path, QSettings.Format.IniFormat).value("window/splitter")
            home_only = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            home_only.show()
            self.app.processEvents()
            home_only.close()
            home_only.deleteLater()
            self.assertEqual(QSettings(path, QSettings.Format.IniFormat).value("window/splitter"), expected)

    def test_maximized_state_restores(self):
        with TemporaryDirectory() as temp_dir, patch.object(MainWindow, "_run"):
            path = str(Path(temp_dir) / "ui.ini")
            first = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            first.showMaximized()
            self.app.processEvents()
            first.close()
            first.deleteLater()

            second = MainWindow(QSettings(path, QSettings.Format.IniFormat))
            try:
                second.show()
                self.app.processEvents()
                self.assertTrue(second.isMaximized())
            finally:
                second.hide()
                second.deleteLater()

    def test_invalid_saved_geometry_keeps_default_size(self):
        with TemporaryDirectory() as temp_dir, patch.object(MainWindow, "_run"):
            settings = QSettings(str(Path(temp_dir) / "ui.ini"), QSettings.Format.IniFormat)
            settings.setValue("window/geometry", QByteArray(b"invalid"))
            settings.setValue("window/splitter", QByteArray(b"invalid"))
            window = MainWindow(settings)
            try:
                self.assertEqual((window.width(), window.height()), (1120, 760))
            finally:
                window.deleteLater()


if __name__ == "__main__":
    unittest.main()
