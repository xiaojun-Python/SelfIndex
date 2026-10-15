"""Service startup replays queued vector cleanup without loading an embedding model."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app import service_main


class ServiceOutboxStartupTests(unittest.TestCase):
    @patch("waitress.serve")
    @patch("app.service_main.drain_pending_source_writes", return_value={"processed": 1, "failed": 0, "pending": 0})
    @patch("app.service_main.drain_vector_deletions")
    @patch("app.service_main.create_app")
    @patch("app.service_main.get_write_token")
    def test_startup_replays_before_listening(self, _token, create_app, drain, source_drain, serve):
        create_app.return_value.config = {"SQLITE_DB": object(), "VECTOR_DB": object()}
        service_main.main()

        create_app.assert_called_once_with(warm_up=False)
        drain.assert_called_once_with(
            create_app.return_value.config["SQLITE_DB"],
            create_app.return_value.config["VECTOR_DB"],
        )
        source_drain.assert_called_once_with(create_app.return_value.config["SQLITE_DB"])
        serve.assert_called_once()

    @patch("waitress.serve")
    @patch("app.service_main.drain_pending_source_writes", return_value={"processed": 0, "failed": 0, "pending": 0})
    @patch("app.service_main.drain_vector_deletions", side_effect=RuntimeError("synthetic Chroma failure"))
    @patch("app.service_main.create_app")
    @patch("app.service_main.get_write_token")
    def test_cleanup_failure_does_not_prevent_service_start(self, _token, create_app, _drain, _source_drain, serve):
        create_app.return_value.config = {"SQLITE_DB": object(), "VECTOR_DB": object()}
        with self.assertLogs("app.service_main", level="ERROR"):
            service_main.main()
        serve.assert_called_once()

    @patch("waitress.serve")
    @patch("app.service_main.drain_pending_source_writes", return_value={"processed": 0, "failed": 1, "pending": 1})
    @patch("app.service_main.drain_vector_deletions")
    @patch("app.service_main.create_app")
    @patch("app.service_main.get_write_token")
    def test_source_conflict_is_reported_without_stopping_service(self, _token, create_app, _drain, _source_drain, serve):
        create_app.return_value.config = {"SQLITE_DB": object(), "VECTOR_DB": object()}
        with self.assertLogs("app.service_main", level="WARNING") as captured:
            service_main.main()
        self.assertIn("manual resolution", captured.output[0])
        serve.assert_called_once()


if __name__ == "__main__":
    unittest.main()
