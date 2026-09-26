"""Tokoku — toko online multiuser (Flask + SQLite3)."""

import os
import secrets

from flask import Flask, g, render_template

from . import db, security
from .formatting import rupiah


def _load_secret_key(app):
    """Ambil SECRET_KEY dari env; kalau tidak ada, simpan sekali di instance/."""
    env_key = os.environ.get("TOKOKU_SECRET_KEY")
    if env_key:
        return env_key

    key_path = os.path.join(app.instance_path, "secret_key")
    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as fh:
            key = fh.read().strip()
            if key:
                return key

    key = secrets.token_urlsafe(48)
    with open(key_path, "w", encoding="utf-8") as fh:
        fh.write(key)
    os.chmod(key_path, 0o600)
    return key


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.from_mapping(
        SECRET_KEY=_load_secret_key(app),
        DATABASE=os.path.join(app.instance_path, "tokoku.sqlite3"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("TOKOKU_COOKIE_SECURE") == "1",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 14,
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,
        PRODUCTS_PER_PAGE=9,
        # SMTP untuk fitur lupa password (opsional).
        # Kalau tidak diisi, tautan reset hanya ditulis ke log (mode staging).
        SMTP_HOST=os.environ.get("TOKOKU_SMTP_HOST"),
        SMTP_PORT=int(os.environ.get("TOKOKU_SMTP_PORT", "587")),
        SMTP_USER=os.environ.get("TOKOKU_SMTP_USER"),
        SMTP_PASSWORD=os.environ.get("TOKOKU_SMTP_PASSWORD"),
        SMTP_FROM=os.environ.get("TOKOKU_SMTP_FROM"),
        SMTP_TLS=os.environ.get("TOKOKU_SMTP_TLS", "1") != "0",
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    security.init_app(app)

    from . import admin, auth, cart, catalog, orders

    app.register_blueprint(catalog.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(cart.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(admin.bp)

    app.jinja_env.filters["rupiah"] = rupiah
    app.jinja_env.globals["csrf_token"] = security.generate_csrf_token

    @app.context_processor
    def inject_globals():
        cart_count = 0
        if g.get("user") is not None:
            cart_count = db.scalar(
                "SELECT COALESCE(SUM(qty), 0) FROM cart_items WHERE user_id = ?",
                (g.user["id"],),
                default=0,
            )
        return {"cart_count": cart_count, "current_user": g.get("user")}

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/400.html", message=error.description), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template("errors/400.html", message="Kiriman terlalu besar."), 413

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html"), 500

    @app.cli.command("init-db")
    def init_db_command():
        """Buat ulang tabel dari schema.sql."""
        db.init_db()
        print("Database siap:", app.config["DATABASE"])

    return app
