"""Synchronize markdown files from a directory into SelfIndex."""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path

from app.core.settings import settings
from engine.database import DatabaseManager, VectorManager
from engine.memory import build_memory_units, build_raw_document

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
    iterator = root_dir.rglob("*") if recursive else root_dir.glob("*")
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


def sync_markdown_directory(
    root_dir: str | Path,
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager | None,
    recursive: bool = True,
    ignore_file: str | Path | None = None,
) -> dict[str, int]:
    root_path = Path(root_dir).resolve()
    patterns = load_ignore_patterns(Path(ignore_file)) if ignore_file else []
    files = discover_markdown_files(root_path, recursive=recursive, ignore_patterns=patterns)
    current_external_ids = {file_path.relative_to(root_path).as_posix() for file_path in files}
    protected_rules = sqlite_db.list_protected_terms()

    synced = 0
    skipped = 0
    inactivated = 0
    memory_units_written = 0

    with sqlite_db.transaction() as conn:
        for file_path in files:
            raw_document = _build_markdown_raw_document(root_path, file_path)
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
            if previous_revision_id and previous_revision_id != revision_id and vector_db is not None:
                vector_db.delete_vectors(sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id))

            synced += 1
            memory_units_written += len(memory_units)

        existing_documents = sqlite_db.list_active_raw_documents(
            source="markdown",
            source_type="note_file",
            root_document_id=str(root_path),
        )
        for document in existing_documents:
            if document["external_id"] in current_external_ids:
                continue
            inactive_result = sqlite_db.mark_raw_document_inactive(
                document["raw_document_id"],
                conn=conn,
            )
            previous_revision_id = inactive_result.get("previous_revision_id") if inactive_result else None
            if previous_revision_id and vector_db is not None:
                vector_db.delete_vectors(sqlite_db.get_memory_unit_ids_by_revision(previous_revision_id))
            inactivated += 1

    return {
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
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(settings.sqlite_db_path)
    vector_db = None if args.skip_embedding else VectorManager(settings.chroma_db_path)
    result = sync_markdown_directory(
        args.dir,
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        recursive=not args.no_recursive,
        ignore_file=args.ignore_file,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
