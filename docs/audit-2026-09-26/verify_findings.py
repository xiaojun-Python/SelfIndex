"""Isolated runtime/retrieval audit proofs; no live data or service mutations."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


def observe_transient_health_failure():
    from scripts import macos_launch_agent as agent

    calls = []

    def fake_launchctl(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    with patch.object(agent, "AGENT_PATH") as path, patch.object(
        agent, "service_is_healthy", side_effect=[False, True]
    ), patch.object(agent, "run_launchctl", side_effect=fake_launchctl):
        path.exists.return_value = True
        agent.ensure()
    return {"forced_restart": any(call[:2] == ("kickstart", "-k") for call in calls)}


def prove_data_dir_does_not_relocate_stores():
    from app.core.settings import Settings

    with patch.dict(os.environ, {"DATA_DIR": "/tmp/selfindex-audit-data-root"}, clear=True):
        settings = Settings()
    return {
        "data_dir": str(settings.data_dir),
        "sqlite_under_data_dir": settings.sqlite_db_path.is_relative_to(settings.data_dir),
        "chroma_under_data_dir": settings.chroma_db_path.is_relative_to(settings.data_dir),
    }


def prove_concurrent_model_initialization():
    from engine import embedder

    barrier = Barrier(2)

    def fake_model(**kwargs):
        barrier.wait(timeout=5)
        return object()

    manager = embedder.EmbeddingManager("audit-no-download", "cpu")
    with patch.object(embedder, "HuggingFaceEmbeddings", side_effect=fake_model) as constructor:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(lambda: manager.model) for _ in range(2)]
            models = [future.result(timeout=10) for future in futures]
    return {"constructors": constructor.call_count, "distinct_instances": models[0] is not models[1]}


def prove_filtered_candidates_starve_recall():
    from engine.retriever import search_memory

    candidate_counts = []

    class Vector:
        def search(self, query_vector, n_results):
            candidate_counts.append(n_results)
            ids = [f"private-{index}" for index in range(100)] + ["public-result"]
            return {"ids": [ids[:n_results]]}

    class Database:
        def get_memory_unit_details(self, ids):
            rows = {identity: {"recall_domain": "identity"} for identity in ids}
            if "public-result" in ids:
                rows["public-result"] = {
                    "recall_domain": "default", "memory_content": "public fact",
                    "summary": "public fact", "source": "test", "source_type": "note",
                    "title": "Public", "author": "", "created_at": "",
                    "raw_document_id": "raw-public", "external_id": "public",
                    "root_document_id": "root", "start_char": 0, "end_char": 11,
                }
            return rows

    result = search_memory(
        Database(), Vector(), query="public fact", limit=10,
        embedder=SimpleNamespace(embed_query=lambda text: [1.0]),
    )
    control = search_memory(
        Database(), Vector(), query="public fact", limit=11,
        embedder=SimpleNamespace(embed_query=lambda text: [1.0]),
    )
    return {
        "candidates_requested": candidate_counts, "results_limit_10": len(result),
        "results_limit_11": len(control), "eligible_candidate_rank": 101,
    }


def observe_search_display_source():
    from engine.retriever import search_memory

    detail = {
        "recall_domain": "default", "memory_content": "CURRENT_SQLITE_TEXT",
        "summary": "CURRENT_SUMMARY", "source": "test", "source_type": "note",
        "title": "Audit", "author": "", "created_at": "", "raw_document_id": "raw-1",
        "external_id": "ext-1", "root_document_id": "root-1", "start_char": 0, "end_char": 19,
    }
    vector = SimpleNamespace(search=lambda *args, **kwargs: {
        "ids": [["unit-1"]], "documents": [["OLD_VECTOR_TEXT"]],
        "metadatas": [[{"summary": "OLD_SUMMARY"}]], "distances": [[0.01]],
    })
    database = SimpleNamespace(get_memory_unit_details=lambda ids: {"unit-1": detail})
    result = search_memory(database, vector, query="current", limit=1,
                           embedder=SimpleNamespace(embed_query=lambda text: [1.0]))[0]
    return {key: result[key] for key in ("content", "summary", "preview")}


if __name__ == "__main__":
    checks = {
        "RUN-01": observe_transient_health_failure,
        "RUN-02": prove_data_dir_does_not_relocate_stores,
        "RET-01": prove_concurrent_model_initialization,
        "RET-02": prove_filtered_candidates_starve_recall,
        "RET-03": observe_search_display_source,
    }
    for finding, check in checks.items():
        print(json.dumps({"finding": finding, "observed": check()}, ensure_ascii=True))
