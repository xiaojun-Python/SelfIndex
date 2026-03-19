from flask import Flask, render_template

from app.api.routes import bp
from app.core.settings import settings
from engine.database import DatabaseManager, VectorManager


def create_app() -> Flask:
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

    @app.route("/")
    def index():
        return render_template("index.html")

    app.register_blueprint(bp)
    return app
