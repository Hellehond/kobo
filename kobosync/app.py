from __future__ import annotations

import logging

from flask import Flask

from .config import Config
from .db import Database
from .kobo import Context, bp
from .library import Library


def create_app(cfg: Config) -> Flask:
    cfg.prepare()
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False  # type: ignore[attr-defined]
    db = Database(cfg.db_path)
    library = Library(cfg, db)
    app.extensions["kobosync"] = Context(cfg, db, library)
    app.register_blueprint(bp)

    @app.route("/")
    def index():
        return ("kobosync draait. Zet op elke Kobo in .kobo/Kobo/Kobo eReader.conf onder "
                "[OneStoreServices] de regel api_endpoint=<deze-url>/kobo/<token>\n"), 200, {"Content-Type": "text/plain; charset=utf-8"}

    @app.route("/health")
    def health():
        return {"status": "ok"}

    return app


def configure_logging(verbose: bool = False) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
