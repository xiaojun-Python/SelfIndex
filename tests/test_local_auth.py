"""Local write tokens are published atomically and never accepted when corrupt."""

from __future__ import annotations

import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.core import local_auth


def _create_token_in_process(data_dir, start, results):
    local_auth.settings = SimpleNamespace(data_dir=Path(data_dir))
    try:
        if not start.wait(timeout=10):
            raise TimeoutError("token start timed out")
        results.put(("ok", local_auth.get_write_token()))
    except Exception as exc:
        results.put(("error", repr(exc)))


class LocalAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="selfindex-token-test-")
        self.addCleanup(self.temp_dir.cleanup)
        self.data_dir = Path(self.temp_dir.name) / "data"
        self.settings_patch = patch.object(local_auth, "settings", SimpleNamespace(data_dir=self.data_dir))
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        self.env_patch = patch.dict(os.environ)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        os.environ.pop("API_WRITE_TOKEN", None)

    def test_new_token_is_private_stable_and_nonempty(self):
        token = local_auth.get_write_token()
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(local_auth.get_write_token(), token)
        self.assertEqual(local_auth.token_path().stat().st_mode & 0o777, 0o600)
        self.assertTrue(local_auth.valid_write_token(token))

    def test_empty_or_insecure_file_fails_without_rotation(self):
        self.data_dir.mkdir()
        path = local_auth.token_path()
        path.write_text("", encoding="ascii")
        path.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "empty or invalid"):
            local_auth.get_write_token()
        self.assertEqual(path.read_text(encoding="ascii"), "")

        path.write_text("valid-token", encoding="ascii")
        path.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "0600"):
            local_auth.get_write_token()

    def test_invalid_input_and_override_do_not_crash_compare_digest(self):
        token = local_auth.get_write_token()
        self.assertFalse(local_auth.valid_write_token("非 ASCII"))
        self.assertFalse(local_auth.valid_write_token(token + " "))
        os.environ["API_WRITE_TOKEN"] = "非 ASCII"
        with self.assertRaisesRegex(RuntimeError, "ASCII"):
            local_auth.get_write_token()

    def test_two_processes_publish_the_same_complete_token(self):
        ctx = multiprocessing.get_context("spawn")
        start, results = ctx.Event(), ctx.Queue()
        processes = [
            ctx.Process(target=_create_token_in_process, args=(self.data_dir, start, results))
            for _ in range(2)
        ]
        try:
            for process in processes:
                process.start()
            start.set()
            outcomes = [results.get(timeout=15) for _ in processes]
        finally:
            for process in processes:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        self.assertEqual([process.exitcode for process in processes], [0, 0])
        self.assertEqual([kind for kind, _value in outcomes], ["ok", "ok"])
        self.assertEqual(outcomes[0][1], outcomes[1][1])
        self.assertEqual(local_auth.get_write_token(), outcomes[0][1])


if __name__ == "__main__":
    unittest.main()
