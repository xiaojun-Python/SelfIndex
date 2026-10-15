"""Offline profile backups are private, complete, and never overwritten."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from scripts.backup_profile import backup_profile


class BackupProfileTests(unittest.TestCase):
    def test_verified_private_backup_and_no_overwrite(self):
        with tempfile.TemporaryDirectory(prefix="selfindex-backup-test-") as temporary:
            root = Path(temporary)
            data = root / "data"
            chroma = data / "chroma"
            chroma.mkdir(parents=True)
            (chroma / "index.bin").write_bytes(b"vector data")
            database = data / "archive.db"
            database.write_bytes(b"archive data")
            config = root / ".env"
            config.write_text("SECRET=synthetic\n", encoding="utf-8")
            destination = root / "backups" / "snapshot"
            result = backup_profile(
                destination, data_dir=data, sqlite_path=database,
                chroma_path=chroma, config_path=config,
            )
            self.assertGreaterEqual(result["files"], 3)
            self.assertEqual((destination / "data" / "archive.db").read_bytes(), b"archive data")
            self.assertEqual((destination / "config.env").read_text(encoding="utf-8"), "SECRET=synthetic\n")
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            self.assertIn("archive.db", manifest["files"])
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((destination / "config.env").stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                backup_profile(
                    destination, data_dir=data, sqlite_path=database,
                    chroma_path=chroma, config_path=config,
                )

    def test_symlink_in_profile_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="selfindex-backup-test-") as temporary:
            root = Path(temporary)
            data = root / "data"
            chroma = data / "chroma"
            chroma.mkdir(parents=True)
            database = data / "archive.db"
            database.write_bytes(b"archive data")
            (data / "external").symlink_to(database)
            config = root / ".env"
            config.write_text("SECRET=synthetic\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "symlink"):
                backup_profile(
                    root / "backup", data_dir=data, sqlite_path=database,
                    chroma_path=chroma, config_path=config,
                )


if __name__ == "__main__":
    unittest.main()
