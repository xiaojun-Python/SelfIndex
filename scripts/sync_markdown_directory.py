"""Synchronize markdown files from a directory into SelfIndex."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager, ReadOnlyDatabase, VectorManager
from engine.memory import build_memory_units, build_raw_document
from engine.vector_outbox import drain_vector_deletions

MARKDOWN_SUFFIXES = {".md", ".markdown"}


def load_ignore_patterns(ignore_file: Path | None) -> list[str]:
    if ignore_file is None or not ignore_file.exists():
        return []

    patterns: list[str] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        patterns.append(candidate)
    return patterns


def is_ignored(relative_path: Path, patterns: list[str]) -> bool:
    normalized = relative_path.as_posix()
    for pattern in patterns:
        cleaned = pattern.rstrip("/")
        if not cleaned:
            continue
        if fnmatch.fnmatch(normalized, cleaned):
            return True
        if fnmatch.fnmatch(relative_path.name, cleaned):
            return True
        if normalized.startswith(f"{cleaned}/"):
            return True
    return False


def discover_markdown_files(
    root_dir: Path,
    *,
    recursive: bool = True,
    ignore_patterns: list[str] | None = None,
) -> list[Path]:
    ignore_patterns = ignore_patterns or []
    if not root_dir.is_dir():
        raise NotADirectoryError(f"Markdown source directory is unavailable: {root_dir}")

    def raise_scan_error(error: OSError) -> None:
        raise error

    if recursive:
        iterator = (
            Path(current_dir) / name
            for current_dir, _directories, names in os.walk(root_dir, onerror=raise_scan_error)
            for name in names
        )
    else:
        iterator = root_dir.iterdir()
    discovered: list[Path] = []
    for path in iterator:
        if not path.is_file():
            continue
        if path.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        relative_path = path.relative_to(root_dir)
        if is_ignored(relative_path, ignore_patterns):
            continue
        discovered.append(path)
    return sorted(discovered)


def _build_markdown_raw_document(root_dir: Path, file_path: Path) -> dict:
    content = file_path.read_text(encoding="utf-8")
    relative_path = file_path.relative_to(root_dir)
    stat = file_path.stat()
    return build_raw_document(
        source="markdown",
        source_type="note_file",
        external_id=relative_path.as_posix(),
        root_document_id=str(root_dir.resolve()),
        title=file_path.stem,
        author=None,
        created_at=None,
        content=content,
        raw_payload={
            "file": {
                "name": file_path.name,
                "relative_path": relative_path.as_posix(),
                "suffix": file_path.suffix.lower(),
                "size_bytes": stat.st_size,
                "mtime": int(stat.st_mtime),
            }
        },
        metadata={
            "root_dir": str(root_dir.resolve()),
            "relative_path": relative_path.as_posix(),
            "file_name": file_path.name,
            "suffix": file_path.suffix.lower(),
        },
    )


def _source_identity(conn, root_path: Path, *, register: bool) -> tuple[str, str]:
    root = str(root_path)
    has_registry = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'markdown_sources'"
    ).fetchone()
    if has_registry:
        row = conn.execute(
            "SELECT source_id, identity_mode FROM markdown_sources WHERE root_path = ?", (root,)
        ).fetchone()
        if row:
            return row["source_id"], row["identity_mode"]

    source_id = hashlib.sha256(root.encode("utf-8")).hexdigest()[:16]
    legacy_on_root = conn.execute(
        """
        SELECT 1 FROM raw_documents
        WHERE source = 'markdown' AND source_type = 'note_file'
          AND root_document_id = ? AND external_id NOT LIKE '@%'
        LIMIT 1
        """,
        (root,),
    ).fetchone()
    another_source = conn.execute(
        "SELECT 1 FROM raw_documents WHERE source = 'markdown' AND source_type = 'note_file' LIMIT 1"
    ).fetchone()
    registered_source = has_registry and conn.execute(
        "SELECT 1 FROM markdown_sources LIMIT 1"
    ).fetchone()
    identity_mode = "legacy" if legacy_on_root or not (another_source or registered_source) else "scoped"
    if register:
        conn.execute(
            "INSERT INTO markdown_sources (source_id, root_path, identity_mode) VALUES (?, ?, ?)",
            (source_id, root, identity_mode),
        )
    return source_id, identity_mode


def _external_id(relative_path: str, source_id: str, identity_mode: str) -> str:
    return relative_path if identity_mode == "legacy" else f"@{source_id}/{relative_path}"


def _apply_source_identity(raw_document: dict, source_id: str, identity_mode: str) -> dict:
    raw_document["external_id"] = _external_id(raw_document["external_id"], source_id, identity_mode)
    raw_document["raw_document_id"] = f"markdown:note_file:{raw_document['external_id']}"
    metadata = json.loads(raw_document["metadata_json"])
    metadata["source_instance_id"] = source_id
    raw_document["metadata_json"] = json.dumps(metadata, ensure_ascii=False)
    return raw_document


def _scan_source(root_dir: str | Path, *, recursive: bool, ignore_file: str | Path | None):
    root_path = Path(root_dir).resolve(strict=True)
    if not root_path.is_dir():
        raise NotADirectoryError(f"Markdown source directory is unavailable: {root_path}")
    root_identity = (root_path.stat().st_dev, root_path.stat().st_ino)
    patterns = load_ignore_patterns(Path(ignore_file)) if ignore_file else []
    files = discover_markdown_files(root_path, recursive=recursive, ignore_patterns=patterns)
    if not root_path.is_dir() or (root_path.stat().st_dev, root_path.stat().st_ino) != root_identity:
        raise OSError(f"Markdown source directory changed during scan: {root_path}")
    return root_path, files


def preview_markdown_directory(
    root_dir: str | Path,
    *,
    sqlite_db: DatabaseManager | ReadOnlyDatabase,
    recursive: bool = True,
    ignore_file: str | Path | None = None,
) -> dict[str, object]:
    root_path, files = _scan_source(root_dir, recursive=recursive, ignore_file=ignore_file)
    with sqlite_db.get_connection() as conn:
        source_id, identity_mode = _source_identity(conn, root_path, register=False)
        has_outbox = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'source_write_outbox'"
        ).fetchone()
        pending_source_writes = 0
        if has_outbox:
            pending_source_writes = conn.execute(
                "SELECT COUNT(*) AS count FROM source_write_outbox WHERE root_path = ?",
                (str(root_path),),
            ).fetchone()["count"]
        rows = conn.execute(
            """
            SELECT external_id FROM raw_documents
            WHERE source = 'markdown' AND source_type = 'note_file'
              AND root_document_id = ? AND is_active = 1
            """,
            (str(root_path),),
        ).fetchall()
    current_ids = {
        _external_id(path.relative_to(root_path).as_posix(), source_id, identity_mode)
        for path in files
    }
    missing_ids = sorted(row["external_id"] for row in rows if row["external_id"] not in current_ids)
    return {
        "source_id": source_id,
        "identity_mode": identity_mode,
        "pending_source_writes": pending_source_writes,
        "files_seen": len(files),
        "would_inactivate": len(missing_ids),
        "inactivation_sample": missing_ids[:20],
    }


def sync_markdown_directory(
    root_dir: str | Path,
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager | None,
    recursive: bool = True,
    ignore_file: str | Path | None = None,
    allow_empty_source: bool = False,
) -> dict[str, int | str]:
    root_path, files = _scan_source(root_dir, recursive=recursive, ignore_file=ignore_file)
    if not files and not allow_empty_source:
        existing_documents = sqlite_db.list_active_raw_documents(
            source="markdown", source_type="note_file", root_document_id=str(root_path),
        )
        if existing_documents:
            raise RuntimeError(
                "Markdown source has no files, but indexed documents exist. "
                "Use allow_empty_source only when clearing this source is intentional."
            )
    protected_rules = sqlite_db.list_protected_terms()

    synced = 0
    skipped = 0
    inactivated = 0
    memory_units_written = 0
    stale_vector_ids: set[str] = set()

    with sqlite_db.transaction() as conn:
        if conn.execute(
            "SELECT 1 FROM source_write_outbox WHERE root_path = ? LIMIT 1",
            (str(root_path),),
        ).fetchone():
            raise RuntimeError("Markdown source has pending App writes; resolve them before syncing.")
        source_id, identity_mode = _source_identity(conn, root_path, register=True)
        current_external_ids = {
            _external_id(file_path.relative_to(root_path).as_posix(), source_id, identity_mode)
            for file_path in files
        }
        for file_path in files:
            raw_document = _apply_source_identity(
                _build_markdown_raw_document(root_path, file_path), source_id, identity_mode
            )
            owner = conn.execute(
                "SELECT root_document_id FROM raw_documents WHERE raw_document_id = ?",
                (raw_document["raw_document_id"],),
            ).fetchone()
            if owner and owner["root_document_id"] != str(root_path):
                raise RuntimeError("Markdown identity collision with another source; no documents were changed.")
            upsert_result = sqlite_db.upsert_raw_document(raw_document, conn=conn)
            if not upsert_result["revision_changed"]:
                skipped += 1
                continue

            revision_id = upsert_result["revision_id"]
            memory_units = build_memory_units(
                raw_document,
                revision_id=revision_id,
                embedding_version=settings.embedding_model,
                protected_rules=protected_rules,
            )
            sqlite_db.insert_memory_units(memory_units, conn=conn)

            previous_revision_id = upsert_result.get("previous_revision_id")
            if previous_revision_id and previous_revision_id != revision_id:
                stale_vector_ids.update(
                    sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id, conn=conn)
                )

            synced += 1
            memory_units_written += len(memory_units)

        existing_documents = sqlite_db.list_active_raw_documents(
            source="markdown",
            source_type="note_file",
            root_document_id=str(root_path),
            conn=conn,
        )
        for document in existing_documents:
            if document["external_id"] in current_external_ids:
                continue
            inactive_result = sqlite_db.mark_raw_document_inactive(
                document["raw_document_id"],
                conn=conn,
            )
            previous_revision_id = inactive_result.get("previous_revision_id") if inactive_result else None
            if previous_revision_id:
                stale_vector_ids.update(
                    sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id, conn=conn)
                )
            inactivated += 1

        sqlite_db.queue_vector_deletions(sorted(stale_vector_ids), conn=conn)

    if vector_db is not None:
        try:
            drain_vector_deletions(sqlite_db, vector_db)
        except Exception as exc:
            raise RuntimeError(
                "Markdown archive was committed, but vector cleanup is queued. "
                "Retry index recovery after checking the error."
            ) from exc

    return {
        "source_id": source_id,
        "identity_mode": identity_mode,
        "files_seen": len(files),
        "synced": synced,
        "skipped": skipped,
        "inactivated": inactivated,
        "memory_units": memory_units_written,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize markdown files from a directory into SelfIndex."
    )
    parser.add_argument("--dir", required=True, help="Root directory to scan.")
    parser.add_argument(
        "--ignore-file",
        default=None,
        help="Optional ignore file with gitignore-like glob patterns.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Only scan the top-level directory.",
    )
    parser.add_argument(
        "--skip-embedding",
        action="store_true",
        help="Sync archive and memory units only; do not touch Chroma.",
    )
    parser.add_argument(
        "--allow-empty-source",
        action="store_true",
        help="Allow an empty source to inactivate all previously indexed Markdown files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview source identity and inactivation without opening either database for writes.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    if args.dry_run:
        result = preview_markdown_directory(
            args.dir,
            sqlite_db=ReadOnlyDatabase(settings.sqlite_db_path),
            recursive=not args.no_recursive,
            ignore_file=args.ignore_file,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0)
    sqlite_db = DatabaseManager(settings.sqlite_db_path)
    vector_db = None if args.skip_embedding else VectorManager(settings.chroma_db_path)
    result = sync_markdown_directory(
        args.dir,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        recursive=not args.no_recursive,
        ignore_file=args.ignore_file,
        allow_empty_source=args.allow_empty_source,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
