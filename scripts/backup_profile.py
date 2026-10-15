"""Make a verified, private offline backup of one unified local profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from app.core.settings import settings
from engine.profile_lock import acquire_writer_lease


def _files(root: Path) -> list[Path]:
    entries = sorted(path for path in root.rglob("*") if path.is_file())
    if any(path.is_symlink() for path in root.rglob("*")):
        raise RuntimeError("Profile contains a symlink; inspect it before backup.")
    return entries


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_profile(
    destination: Path,
    *,
    data_dir: Path,
    sqlite_path: Path,
    chroma_path: Path,
    config_path: Path,
) -> dict[str, int]:
    destination = destination.expanduser().resolve()
    data_dir = data_dir.resolve(strict=True)
    if destination.exists():
        raise FileExistsError(destination)
    if destination.is_relative_to(data_dir) or data_dir.is_relative_to(destination):
        raise ValueError("Backup destination must not contain or be inside the live data directory.")
    if not sqlite_path.is_file() or not chroma_path.is_dir() or not config_path.is_file():
        raise FileNotFoundError("Profile database, Chroma directory, or configuration file is missing.")
    if sqlite_path.resolve().parent != data_dir or chroma_path.resolve().parent != data_dir:
        raise ValueError("This backup command requires a unified DATA_DIR profile.")

    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lease = acquire_writer_lease(sqlite_path)
    stage = Path(tempfile.mkdtemp(prefix=f".{destination.name}.tmp-", dir=destination.parent))
    try:
        source_files = _files(data_dir)
        shutil.copytree(data_dir, stage / "data")
        shutil.copy2(config_path, stage / "config.env")
        copied_files = _files(stage / "data")
        if [path.relative_to(data_dir) for path in source_files] != [
            path.relative_to(stage / "data") for path in copied_files
        ]:
            raise RuntimeError("Backup file list differs from source.")
        manifest: dict[str, str] = {}
        for source, copied in zip(source_files, copied_files):
            source_hash = _digest(source)
            if source_hash != _digest(copied):
                raise RuntimeError("Backup file hash differs from source.")
            manifest[str(source.relative_to(data_dir))] = source_hash
        if _digest(config_path) != _digest(stage / "config.env"):
            raise RuntimeError("Backup configuration hash differs from source.")
        for directory in [stage, *(path for path in stage.rglob("*") if path.is_dir())]:
            directory.chmod(0o700)
        for path in _files(stage):
            path.chmod(0o600)
        (stage / "manifest.json").write_text(
            json.dumps({"files": manifest, "config_sha256": _digest(config_path)}, sort_keys=True),
            encoding="utf-8",
        )
        (stage / "manifest.json").chmod(0o600)
        os.replace(stage, destination)
        return {"files": len(manifest), "bytes": sum(path.stat().st_size for path in source_files)}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        del lease


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--confirm-service-stopped", action="store_true")
    args = parser.parse_args()
    if not args.confirm_service_stopped:
        parser.error("--confirm-service-stopped is required")
    result = backup_profile(
        args.destination,
        data_dir=settings.data_dir,
        sqlite_path=settings.sqlite_db_path,
        chroma_path=settings.chroma_db_path,
        config_path=settings.base_dir / ".env",
    )
    print(f"Verified offline backup: {result['files']} files, {result['bytes']} bytes.")


if __name__ == "__main__":
    main()
