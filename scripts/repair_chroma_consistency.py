"""Audit and optionally repair SQLite/Chroma memory-unit consistency."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from app.core.settings import settings
from engine.database import INDEX_MODEL_KEY, DatabaseManager, ReadOnlyDatabase, VectorManager
from engine.vector_index import vector_metadata_from_row
from engine.vector_outbox import drain_vector_deletions
from scripts.build_embeddings import build_missing_embeddings


def _current_sqlite_memory_units(sqlite_db) -> dict[str, dict]:
    with sqlite_db.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT mu.memory_unit_id, mu.content, mu.summary, mu.recall_domain,
                   mu.embedding_version, mu.is_embedded,
                   rd.raw_document_id, rd.title, rd.source, rd.source_type,
                   rd.author, rd.created_at
            FROM memory_units mu
            JOIN raw_document_revisions rr ON rr.revision_id = mu.revision_id
            JOIN raw_documents rd ON rd.raw_document_id = mu.raw_document_id
            WHERE rr.is_current = 1 AND rd.is_active = 1
            """
        ).fetchall()

    return {row["memory_unit_id"]: row for row in rows}


def _chroma_memory_units(vector_db: VectorManager, *, batch_size: int) -> tuple[dict[str, tuple], bool]:
    count = int(vector_db.collection.count())
    vectors: dict[str, tuple] = {}
    for offset in range(0, count, batch_size):
        result = vector_db.collection.get(
            limit=batch_size, offset=offset, include=["documents", "metadatas"]
        )
        for vector_id, document, metadata in zip(
            result.get("ids") or [], result.get("documents") or [], result.get("metadatas") or []
        ):
            vectors[vector_id] = (document, metadata)
    return vectors, len(vectors) == count == int(vector_db.collection.count())


def _mark_unembedded(sqlite_db: DatabaseManager, memory_unit_ids: list[str]) -> None:
    if not memory_unit_ids:
        return
    with sqlite_db.transaction() as conn:
        conn.executemany(
            """
            UPDATE memory_units
            SET is_embedded = 0, updated_at = CURRENT_TIMESTAMP
            WHERE memory_unit_id = ?
            """,
            [(memory_unit_id,) for memory_unit_id in memory_unit_ids],
        )


def audit_consistency(
    *,
    sqlite_db,
    vector_db: VectorManager,
    batch_size: int,
) -> dict[str, object]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    units = _current_sqlite_memory_units(sqlite_db)
    current_ids = set(units)
    embedded_ids = {unit_id for unit_id, row in units.items() if row["is_embedded"]}
    vectors, chroma_scan_complete = _chroma_memory_units(vector_db, batch_size=batch_size)
    chroma_ids = set(vectors)
    pending_ids = current_ids - embedded_ids
    orphan_vector_ids = chroma_ids - current_ids
    missing_vector_ids = embedded_ids - chroma_ids
    shared_ids = embedded_ids & chroma_ids
    content_mismatch_ids = {
        unit_id for unit_id in shared_ids if vectors[unit_id][0] != units[unit_id]["content"]
    }
    metadata_mismatch_ids = {
        unit_id for unit_id in shared_ids
        if vectors[unit_id][1] != vector_metadata_from_row(units[unit_id])
    }

    return {
        "sqlite_current": len(current_ids),
        "sqlite_embedded": len(embedded_ids),
        "sqlite_pending": len(pending_ids),
        "chroma_vectors": len(chroma_ids),
        "chroma_scan_complete": chroma_scan_complete,
        "orphan_vector_ids": sorted(orphan_vector_ids),
        "missing_vector_ids": sorted(missing_vector_ids),
        "pending_with_vector_ids": sorted(pending_ids & chroma_ids),
        "content_mismatch_ids": sorted(content_mismatch_ids),
        "metadata_mismatch_ids": sorted(metadata_mismatch_ids),
        "sqlite_model_versions": dict(sorted(Counter(
            str(row["embedding_version"]) for row in units.values()
        ).items())),
        "index_model": (vector_db.collection.metadata or {}).get(INDEX_MODEL_KEY),
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit and optionally repair SQLite/Chroma memory-unit consistency."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for Chroma reads, deletes, and optional rebuilds.",
    )
    parser.add_argument(
        "--delete-orphans",
        action="store_true",
        help="Delete Chroma vectors that no longer belong to current active SQLite memory units.",
    )
    parser.add_argument(
        "--drain-pending-deletions",
        action="store_true",
        help="Replay committed vector deletion intents before auditing Chroma.",
    )
    parser.add_argument(
        "--mark-missing-unembedded",
        action="store_true",
        help="Mark SQLite memory units as unembedded when their Chroma vector is missing.",
    )
    parser.add_argument(
        "--rebuild-missing",
        action="store_true",
        help="Mark missing vectors as pending, then rebuild pending embeddings.",
    )
    parser.add_argument(
        "--max-rebuild-units",
        type=int,
        default=None,
        help="Optional cap for --rebuild-missing.",
    )
    parser.add_argument(
        "--adopt-index-model",
        metavar="MODEL",
        help="After a clean offline audit, label an existing unlabelled Chroma index with this model.",
    )
    parser.add_argument(
        "--confirm-offline-adoption",
        action="store_true",
        help="Confirm the service and all other writers are stopped and the index is backed up.",
    )
    parser.add_argument(
        "--repair-metadata", action="store_true",
        help="Refresh drifted Chroma metadata from current SQL without changing embeddings.",
    )
    parser.add_argument(
        "--confirm-offline-repair", action="store_true",
        help="Confirm the service is stopped and a restorable profile backup exists.",
    )
    return parser


def main() -> None:
    parser = build_cli()
    args = parser.parse_args()
    batch_size = max(1, args.batch_size)
    mutating = (
        args.drain_pending_deletions or args.delete_orphans or args.mark_missing_unembedded
        or args.rebuild_missing or bool(args.adopt_index_model) or args.repair_metadata
    )
    if mutating and batch_size > 900:
        parser.error("index repair actions require --batch-size <= 900")
    if args.adopt_index_model:
        if not args.confirm_offline_adoption:
            parser.error("--adopt-index-model requires --confirm-offline-adoption")
        if args.adopt_index_model != settings.embedding_model:
            parser.error("adopted model must match the configured EMBEDDING_MODEL")
        if args.delete_orphans or args.drain_pending_deletions or args.mark_missing_unembedded or args.rebuild_missing or args.repair_metadata:
            parser.error("model adoption must run separately from repair actions")
    if args.repair_metadata and not args.confirm_offline_repair:
        parser.error("--repair-metadata requires --confirm-offline-repair")
    if not Path(settings.sqlite_db_path).is_file():
        parser.error("SQLite database path does not exist; refusing to create a repair target")
    if not Path(settings.chroma_db_path).is_dir():
        parser.error("Chroma directory does not exist; refusing to create a repair target")
    sqlite_db = DatabaseManager(settings.sqlite_db_path) if mutating else ReadOnlyDatabase(settings.sqlite_db_path)
    vector_db = VectorManager(settings.chroma_db_path, create_if_missing=False)
    print(f"Queued vector deletions: {sqlite_db.count_pending_vector_deletions()}")
    if args.drain_pending_deletions:
        replay = drain_vector_deletions(sqlite_db, vector_db, batch_size=batch_size)
        print(
            f"Replayed deletion intents: {replay['processed']}; "
            f"delete requests: {replay['delete_requested']}."
        )
        print(f"Queued vector deletions remaining: {sqlite_db.count_pending_vector_deletions()}")
    report = audit_consistency(
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        batch_size=batch_size,
    )

    orphan_ids = list(report["orphan_vector_ids"])
    missing_ids = list(report["missing_vector_ids"])
    print(f"SQLite current memory units: {report['sqlite_current']}")
    print(f"SQLite marked embedded: {report['sqlite_embedded']}")
    print(f"SQLite pending embeddings: {report['sqlite_pending']}")
    print(f"Chroma vectors: {report['chroma_vectors']}")
    if not report["chroma_scan_complete"]:
        print("WARNING: Chroma changed during the paginated scan; repeat the audit offline.")
    print(f"Chroma orphan vectors: {len(orphan_ids)}")
    print(f"SQLite embedded units missing from Chroma: {len(missing_ids)}")
    for label, key in (
        ("Pending units still in Chroma", "pending_with_vector_ids"),
        ("Chroma document mismatches", "content_mismatch_ids"),
        ("Chroma metadata mismatches", "metadata_mismatch_ids"),
    ):
        print(f"{label}: {len(report[key])}")
        if report[key]:
            print(f"{label} sample: {report[key][:10]}")
    print(f"SQLite model versions: {report['sqlite_model_versions']}")
    print(f"Chroma model manifest: {report['index_model'] or '(missing)'}")
    if orphan_ids:
        print(f"Orphan sample: {orphan_ids[:10]}")
    if missing_ids:
        print(f"Missing sample: {missing_ids[:10]}")

    if args.repair_metadata:
        current_units = _current_sqlite_memory_units(sqlite_db)
        repaired = 0
        for start in range(0, len(report["metadata_mismatch_ids"]), batch_size):
            ids = report["metadata_mismatch_ids"][start : start + batch_size]
            vector_db.collection.update(
                ids=ids,
                metadatas=[vector_metadata_from_row(current_units[unit_id]) for unit_id in ids],
            )
            repaired += len(ids)
        print(f"Refreshed Chroma metadata: {repaired}")

    if args.adopt_index_model:
        inconsistent = any(report[key] for key in (
            "orphan_vector_ids", "missing_vector_ids", "pending_with_vector_ids",
            "content_mismatch_ids", "metadata_mismatch_ids",
        ))
        if inconsistent or not report["chroma_scan_complete"] or sqlite_db.count_pending_vector_deletions():
            parser.error("index audit is not clean; resolve drift and pending deletions before adoption")
        if set(report["sqlite_model_versions"]) != {args.adopt_index_model}:
            parser.error("SQLite current units do not all use the requested model")
        vector_db.adopt_existing_model(args.adopt_index_model)
        print(f"Adopted Chroma index model: {args.adopt_index_model}")

    if args.delete_orphans:
        with sqlite_db.transaction() as conn:
            sqlite_db.queue_vector_deletions(orphan_ids, conn=conn)
        replay = drain_vector_deletions(sqlite_db, vector_db, batch_size=batch_size)
        print(f"Orphan vector delete requests: {replay['delete_requested']}")

    if args.mark_missing_unembedded or args.rebuild_missing:
        _mark_unembedded(sqlite_db, missing_ids)
        print(f"Marked missing vectors as pending embeddings: {len(missing_ids)}")

    if args.rebuild_missing:
        result = build_missing_embeddings(
            sqlite_db=sqlite_db,
            vector_db=vector_db,
            batch_size=batch_size,
            max_units=args.max_rebuild_units,
        )
        print(
            "Rebuilt pending embeddings: "
            f"{result['processed']}. Remaining pending units: {result['has_remaining']}."
        )


if __name__ == "__main__":
    main()
