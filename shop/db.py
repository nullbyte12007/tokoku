"""Helper akses SQLite: koneksi per-request, query, dan transaksi eksplisit."""

from contextlib import contextmanager
import os

import sqlite3
from flask import current_app, g

_secured_paths = set()


def _secure_db_file(path):
    """Batasi izin file DB (600) supaya user lain di mesin yang sama tidak bisa baca hash password."""
    if path == ":memory:" or path in _secured_paths:
        return
    for candidate in (path, f"{path}-wal", f"{path}-shm"):
        if not os.path.exists(candidate):
            continue
        try:
            os.chmod(candidate, 0o600)
        except OSError:
            pass
    _secured_paths.add(path)


def get_db():
    """Buka satu koneksi SQLite per request, reuse selama request berjalan."""
    if "db" not in g:
        # isolation_level=None -> mode autocommit; transaksi diatur manual
        # lewat transaction() supaya alurnya eksplisit.
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            isolation_level=None,
            timeout=10,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA journal_mode = WAL")
        g.db.execute("PRAGMA busy_timeout = 10000")
        _secure_db_file(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as fh:
        db.executescript(fh.read().decode("utf-8"))


def query(sql, args=(), one=False):
    """SELECT -> list[sqlite3.Row] (atau satu Row bila one=True)."""
    cur = get_db().execute(sql, args)
    try:
        rows = cur.fetchall()
    finally:
        cur.close()
    if one:
        return rows[0] if rows else None
    return rows


def scalar(sql, args=(), default=None):
    row = query(sql, args, one=True)
    if row is None:
        return default
    return row[0]


def execute(sql, args=()):
    """INSERT/UPDATE/DELETE di luar transaksi (autocommit). Return lastrowid."""
    cur = get_db().execute(sql, args)
    try:
        return cur.lastrowid
    finally:
        cur.close()


@contextmanager
def transaction():
    """Transaksi tulis eksklusif: BEGIN IMMEDIATE ... COMMIT/ROLLBACK."""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def like_pattern(text):
    """Escape wildcard LIKE supaya input user tidak jadi pola pencarian liar."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def init_app(app):
    app.teardown_appcontext(close_db)
