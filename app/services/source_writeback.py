"""Recoverable Markdown source writes after archive commits."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from engine.memory import get_content_hash


class SourceWriteConflictError(RuntimeError):
    pass


def _source_path(root_text: str, relative_text: str) -> Path:
    relative = Path(relative_text)
    if relative.is_absolute() or not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise SourceWriteConflictError("Markdown source path is invalid.")
    try:
        root = Path(root_text).resolve(strict=True)
    except OSError as exc:
        raise SourceWriteConflictError("Markdown source directory is unavailable.") from exc
    if not root.is_dir():
        raise SourceWriteConflictError("Markdown source directory is unavailable.")
    candidate = root / relative
    if candidate.is_symlink() or not candidate.is_file():
        raise SourceWriteConflictError("Markdown source file is unavailable or is a symlink.")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SourceWriteConflictError("Markdown source file is unavailable.") from exc
    if not resolved.is_relative_to(root):
        raise SourceWriteConflictError("Markdown source file escapes its registered root.")
    return resolved


def prepare_source_write(raw_document: dict[str, Any], content: str) -> dict[str, str]:
    metadata = raw_document.get("metadata") or {}
    root_text = str(metadata.get("root_dir") or "")
    relative_text = str(metadata.get("relative_path") or "")
    if not root_text or not relative_text or root_text != raw_document.get("root_document_id"):
        raise SourceWriteConflictError("Markdown source location is missing or inconsistent.")
    path = _source_path(root_text, relative_text)
    try:
        current_content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SourceWriteConflictError("Markdown source file cannot be read as UTF-8.") from exc
    if get_content_hash(current_content) != raw_document["content_hash"]:
        raise SourceWriteConflictError("Markdown source changed on disk. Reload and reconcile it before saving.")
    return {
        "root_path": root_text,
        "relative_path": relative_text,
        "expected_content_hash": raw_document["content_hash"],
        "content": content,
    }


def _atomic_replace(path: Path, content: str) -> None:
    original_mode = stat.S_IMODE(path.stat().st_mode)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.selfindex-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            os.fchmod(output.fileno(), original_mode)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def drain_source_write(sqlite_db: Any, raw_document_id: str) -> bool:
    conn = sqlite_db.get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT root_path, relative_path, expected_content_hash, content
            FROM source_write_outbox WHERE raw_document_id = ?
            """,
            (raw_document_id,),
        ).fetchone()
        if row is None:
            conn.commit()
            return False
        path = _source_path(row["root_path"], row["relative_path"])
        current_hash = get_content_hash(path.read_text(encoding="utf-8"))
        target_hash = get_content_hash(row["content"])
        if current_hash != target_hash:
            if current_hash != row["expected_content_hash"]:
                raise SourceWriteConflictError(
                    "Markdown source changed after the archive edit; pending write was not applied."
                )
            _atomic_replace(path, row["content"])
        conn.execute("DELETE FROM source_write_outbox WHERE raw_document_id = ?", (raw_document_id,))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def drain_pending_source_writes(sqlite_db: Any, *, limit: int = 100) -> dict[str, int]:
    if limit < 1:
        raise ValueError("limit must be positive")
    with sqlite_db.get_connection() as conn:
        rows = conn.execute(
            "SELECT raw_document_id FROM source_write_outbox ORDER BY queued_at, raw_document_id LIMIT ?",
            (limit,),
        ).fetchall()
    processed = failed = 0
    for row in rows:
        try:
            if drain_source_write(sqlite_db, row["raw_document_id"]):
                processed += 1
        except (OSError, UnicodeError, SourceWriteConflictError):
            failed += 1
    return {"processed": processed, "failed": failed, "pending": sqlite_db.count_pending_source_writes()}
