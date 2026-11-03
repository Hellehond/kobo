from __future__ import annotations

import logging

from flask import Flask

from .config import Config
from .db import Database
from . import web
from .kobo import TAG_FORMAT, Context, bp
from .library import Library


def create_app(cfg: Config) -> Flask:
    cfg.prepare()
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False  # type: ignore[attr-defined]
    db = Database(cfg.db_path)
    if db.get_meta("tag_format") != TAG_FORMAT:
        # Collections were sent in an older format: send them all again.
        if db.bump_tags():
            logging.getLogger(__name__).info("Collections will be re-sent to all devices (format %s)", TAG_FORMAT)
        db.set_meta("tag_format", TAG_FORMAT)
    library = Library(cfg, db)
    app.extensions["kobosync"] = Context(cfg, db, library)
    app.config["MAX_CONTENT_LENGTH"] = max(cfg.upload_max_mb, 1) * 1024 * 1024
    web.install(app)
    app.register_blueprint(bp)

    @app.errorhandler(413)
    def too_large(_error):
        return (f"Te groot: hooguit {cfg.upload_max_mb} MB per keer. "
                "Verhoog KOBOSYNC_UPLOAD_MAX_MB of upload in delen.\n"), 413, {"Content-Type": "text/plain; charset=utf-8"}

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
