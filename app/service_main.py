"""Long-running loopback service entry point for desktop and local API clients."""

from __future__ import annotations

import logging

from app import create_app
from app.core.local_auth import get_write_token
from app.core.settings import settings
from app.services.source_writeback import drain_pending_source_writes
from engine.vector_outbox import drain_vector_deletions

logger = logging.getLogger(__name__)


def main() -> None:
    from waitress import serve

    if settings.host not in {"127.0.0.1", "::1", "localhost"}:
        raise SystemExit("SelfIndex local service must bind to a loopback address.")

    get_write_token()
    app = create_app(warm_up=False)
    try:
        drain_vector_deletions(app.config["SQLITE_DB"], app.config["VECTOR_DB"])
    except Exception:
        logger.exception("Queued vector cleanup failed; it can be retried after service startup")
    try:
        source_replay = drain_pending_source_writes(app.config["SQLITE_DB"])
        if source_replay["failed"]:
            logger.warning("Some queued Markdown source writes need manual resolution: %s", source_replay["failed"])
    except Exception:
        logger.exception("Queued Markdown source write replay failed; it can be retried later")
    app.debug = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    serve(
        app,
        host=settings.host,
        port=settings.port,
        threads=4,
        max_request_body_size=64 * 1024 * 1024,
    )


if __name__ == "__main__":
    main()
