"""Local write token shared by the desktop client and API server."""

from __future__ import annotations

import hmac
import os
import secrets
import stat
from pathlib import Path

from app.core.settings import settings


def token_path() -> Path:
    return settings.data_dir / "api-write-token"


def _valid_token_text(value: str) -> bool:
    return bool(value) and value.isascii() and not any(char.isspace() for char in value)


def _read_token(path: Path) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RuntimeError("Local write token cannot be opened; inspect its file and permissions.") from exc
    try:
        info = os.fstat(descriptor)
        insecure_posix_permissions = hasattr(os, "getuid") and (
            info.st_uid != os.getuid() or bool(info.st_mode & 0o077)
        )
        if not stat.S_ISREG(info.st_mode) or insecure_posix_permissions:
            raise RuntimeError("Local write token must be a regular file owned by this user with 0600 permissions.")
        with os.fdopen(descriptor, "r", encoding="ascii") as source:
            descriptor = -1
            token = source.read().strip()
    except (UnicodeError, OSError) as exc:
        raise RuntimeError("Local write token cannot be read; inspect its file and permissions.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not _valid_token_text(token):
        raise RuntimeError("Local write token is empty or invalid; repair the file before starting SelfIndex.")
    return token


def get_write_token() -> str:
    override = os.getenv("API_WRITE_TOKEN")
    if override:
        if not _valid_token_text(override):
            raise RuntimeError("API_WRITE_TOKEN must be non-empty ASCII without whitespace.")
        return override

    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        return _read_token(path)

    token = secrets.token_urlsafe(32)
    temporary_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as output:
            output.write(token)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary_path, path)
        except FileExistsError:
            return _read_token(path)
        return token
    finally:
        temporary_path.unlink(missing_ok=True)


def valid_write_token(value: str | None) -> bool:
    return bool(value) and _valid_token_text(value) and hmac.compare_digest(value, get_write_token())
