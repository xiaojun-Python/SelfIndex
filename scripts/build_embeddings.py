"""Build embeddings for memory units that are still pending."""

from __future__ import annotations

import argparse
from typing import Any

from app.core.settings import settings
from engine.database import DatabaseManager, VectorManager


def _get_embedder(embedder: Any = None) -> Any:
    if embedder is not None:
        return embedder

    from engine.embedder import embedding_manager

    return embedding_manager


def build_missing_embeddings(
    *,
    sqlite_db: DatabaseManager,
    vector_db: VectorManager,
    embedder: Any = None,
    batch_size: int = 32,
    max_units: int | None = None,
) -> dict[str, int]:
    embedder = _get_embedder(embedder)
    processed = 0

    while True:
        if max_units is not None:
            remaining_budget = max_units - processed
            if remaining_budget <= 0:
                break
            current_limit = min(batch_size, remaining_budget)
        else:
            current_limit = batch_size

        rows = sqlite_db.get_memory_units_needing_embeddings(limit=current_limit)
        if not rows:
            break

        ids = [row["memory_unit_id"] for row in rows]
        texts = [row["content"] for row in rows]
        embeddings = embedder.embed_documents(texts)
        metadatas = [
            {
                "memory_unit_id": row["memory_unit_id"],
                "raw_document_id": row["raw_document_id"],
                "title": row["title"] or "Untitled document",
                "source": row["source"],
                "source_type": row["source_type"],
                "author": row["author"] or "",
                "created_at": row["created_at"] or "",
                "summary": row["summary"] or "",
                "recall_domain": row["recall_domain"] or "default",
            }
            for row in rows
        ]

        vector_db.delete_vectors(ids)
        vector_db.add_vectors(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=texts,
        )
        with sqlite_db.transaction() as conn:
            sqlite_db.mark_memory_units_as_embedded(ids, conn=conn)
        processed += len(rows)

    has_remaining = len(sqlite_db.get_memory_units_needing_embeddings(limit=1))
    return {
        "processed": processed,
        "has_remaining": has_remaining,
    }


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build embeddings for memory units that are still marked as unembedded."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="How many memory units to embed per batch.",
    )
    parser.add_argument(
        "--max-units",
        type=int,
        default=None,
        help="Optional cap for this run; useful for smaller CPU batches.",
    )
    return parser


if __name__ == "__main__":
    args = build_cli().parse_args()
    sqlite_db = DatabaseManager(settings.sqlite_db_path)
    vector_db = VectorManager(settings.chroma_db_path)
    result = build_missing_embeddings(
        sqlite_db=sqlite_db,
        vector_db=vector_db,
        batch_size=max(1, args.batch_size),
        max_units=args.max_units,
    )
    print(
        "Embedded memory units: "
        f"{result['processed']}. Remaining pending units: {result['has_remaining']}."
    )
