"""Run the browser extension's pure sync-planning checks when Node is available."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


class ExtensionSyncPlanTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is not available")
    def test_profile_and_message_changes(self):
        script = Path(__file__).with_name("extension_sync_plan.cjs")
        result = subprocess.run(["node", str(script)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
