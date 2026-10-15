"""One archive profile cannot have two cross-process writers."""

from __future__ import annotations

import gc
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine.database import DatabaseManager


class ProfileWriterLockTests(unittest.TestCase):
    def test_second_process_cannot_open_writer_while_first_is_alive(self):
        with tempfile.TemporaryDirectory(prefix="selfindex-writer-lock-") as temporary:
            path = Path(temporary) / "archive.db"
            first = DatabaseManager(path)
            second = DatabaseManager(path)
            self.assertIs(first._writer_lease, second._writer_lease)
            program = (
                "from engine.database import DatabaseManager; "
                "from engine.profile_lock import ProfileWriterBusyError; "
                "import sys; "
                "\ntry: DatabaseManager(sys.argv[1])"
                "\nexcept ProfileWriterBusyError: sys.exit(12)"
            )
            blocked = subprocess.run(
                [sys.executable, "-c", program, str(path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15,
                check=False,
            )
            self.assertEqual(blocked.returncode, 12, blocked.stderr)
            del first, second
            gc.collect()
            available = subprocess.run(
                [sys.executable, "-c", program, str(path)],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=15,
                check=False,
            )
            self.assertEqual(available.returncode, 0, available.stderr)


if __name__ == "__main__":
    unittest.main()
