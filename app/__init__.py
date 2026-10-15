"""Flask 应用工厂。

这里把 Web 层需要的依赖组装起来：
- 配置
- SQLite
- Chroma
- 启动时自举逻辑
"""

from __future__ import annotations

import time
import uuid

from flask import Flask, render_template
from flask import g
from flask import request


def create_app(*, warm_up: bool = True) -> Flask:
    """创建并配置 Flask 应用实例。"""
    from app.api.routes import bp
    from app.api.v1 import bp as api_v1_bp, register_error_handlers
    from app.core.settings import settings
    from engine.bootstrap import warm_up_search_stack
    from engine.database import DatabaseManager, VectorManager

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = settings.secret_key
    app.debug = settings.debug

    app.config["SETTINGS"] = settings
    app.config["INSTANCE_ID"] = uuid.uuid4().hex
    app.config["SQLITE_DB"] = DatabaseManager(settings.sqlite_db_path)
    app.config["VECTOR_DB"] = VectorManager(settings.chroma_db_path)
    if warm_up:
        warm_up_search_stack()

    @app.before_request
    def _mark_request_started():
        g._request_started_at = time.perf_counter()

    @app.after_request
    def _log_request(response):
        started_at = getattr(g, "_request_started_at", None)
        duration_ms = 0.0
        if started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000

        print(
            f"[web] {request.method} {request.path} -> {response.status_code} "
            f"({duration_ms:.1f} ms)",
            flush=True,
        )
        return response

    @app.route("/")
    def index():
        return render_template("index.html")

    app.register_blueprint(bp)
    app.register_blueprint(api_v1_bp)
    register_error_handlers(app)
    return app
