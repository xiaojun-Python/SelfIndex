"""Flask 应用工厂。

这里把 Web 层需要的依赖组装起来：
- 配置
- SQLite
- Chroma
- 启动时自举逻辑
"""

from __future__ import annotations

from flask import Flask, render_template


def create_app() -> Flask:
    """创建并配置 Flask 应用实例。"""
    from app.api.routes import bp
    from app.core.settings import settings
    from engine.bootstrap import bootstrap_legacy_memory_layer, warm_up_search_stack
    from engine.database import DatabaseManager, VectorManager

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = settings.secret_key
    app.debug = settings.debug

    app.config["SETTINGS"] = settings
    app.config["SQLITE_DB"] = DatabaseManager(settings.sqlite_db_path)
    app.config["VECTOR_DB"] = VectorManager(settings.chroma_db_path)

    # 启动时尽量把旧数据接到新记忆链路上，避免“能打开页面但搜不到”。
    app.config["BOOTSTRAP_STATUS"] = bootstrap_legacy_memory_layer(app.config["SQLITE_DB"])
    warm_up_search_stack()

    @app.route("/")
    def index():
        return render_template("index.html")

    app.register_blueprint(bp)
    return app
