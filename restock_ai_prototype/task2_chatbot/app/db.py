"""
Dual-engine database adapter.

The whole application writes ONE dialect of SQL (MySQL style, `%s` placeholders)
and this module translates it for SQLite when running in zero-setup demo mode.

    rows = db.query("SELECT * FROM products WHERE stock_level = %s", (0,))
    new_id, n = db.execute("INSERT INTO ... VALUES (%s, %s)", (a, b))

Rows always come back as plain dicts with JSON-safe values (Decimal -> float,
date/datetime -> ISO string) so they can be handed straight to json.dumps.
"""
import json
import sqlite3
import threading
from datetime import date, datetime
from decimal import Decimal

from . import config

_local = threading.local()
_sqlite_lock = threading.Lock()


# ------------------------------------------------------------------ helpers
def engine():
    return config.DB_ENGINE


def _translate(sql):
    """MySQL placeholders/functions -> SQLite equivalents."""
    if config.DB_ENGINE == "mysql":
        return sql
    sql = sql.replace("%s", "?")
    sql = sql.replace("NOW()", "CURRENT_TIMESTAMP")
    sql = sql.replace("CURDATE()", "DATE('now')")
    return sql


def _normalize(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def _row_to_dict(row, columns):
    return {col: _normalize(val) for col, val in zip(columns, row)}


# ------------------------------------------------------------------ connections
def _sqlite_conn():
    conn = getattr(_local, "sqlite", None)
    if conn is None:
        config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(config.SQLITE_PATH), timeout=15)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        _local.sqlite = conn
    return conn


def _mysql_conn():
    import mysql.connector  # imported lazily: only needed in MySQL mode

    conn = getattr(_local, "mysql", None)
    if conn is None or not conn.is_connected():
        # autocommit is required here: these connections are long-lived and
        # per-thread, so under InnoDB's REPEATABLE READ an uncommitted read
        # transaction would keep serving a stale snapshot to the live panel.
        conn = mysql.connector.connect(autocommit=True, **config.MYSQL_CONFIG)
        _local.mysql = conn
    return conn


def connect(with_database=True):
    """Open a raw connection (used by init_db, which may need to CREATE DATABASE)."""
    if config.DB_ENGINE == "mysql":
        import mysql.connector

        cfg = dict(config.MYSQL_CONFIG)
        if not with_database:
            cfg.pop("database", None)
        return mysql.connector.connect(**cfg)
    config.SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(config.SQLITE_PATH))


def ping():
    """Return (ok, message) so /api/health can report the DB status."""
    try:
        query("SELECT 1 AS ok", fetchone=True)
        target = (
            f"mysql://{config.MYSQL_CONFIG['host']}/{config.MYSQL_CONFIG['database']}"
            if config.DB_ENGINE == "mysql"
            else f"sqlite://{config.SQLITE_PATH.name}"
        )
        return True, target
    except Exception as exc:  # pragma: no cover - surfaced in the UI instead
        return False, str(exc)


# ------------------------------------------------------------------ query API
def query(sql, params=None, fetchone=False):
    """Run a SELECT; returns a list of dicts (or one dict / None when fetchone)."""
    sql = _translate(sql)
    params = tuple(params or ())

    if config.DB_ENGINE == "mysql":
        conn = _mysql_conn()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = [_row_to_dict(r, columns) for r in cur.fetchall()]
        finally:
            cur.close()
    else:
        with _sqlite_lock:
            conn = _sqlite_conn()
            cur = conn.execute(sql, params)
            columns = [c[0] for c in cur.description]
            rows = [_row_to_dict(r, columns) for r in cur.fetchall()]
            cur.close()

    if fetchone:
        return rows[0] if rows else None
    return rows


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE; returns (lastrowid, rowcount)."""
    sql = _translate(sql)
    params = tuple(params or ())

    if config.DB_ENGINE == "mysql":
        conn = _mysql_conn()
        cur = conn.cursor()
        try:
            cur.execute(sql, params)
            conn.commit()
            return cur.lastrowid, cur.rowcount
        finally:
            cur.close()

    with _sqlite_lock:
        conn = _sqlite_conn()
        cur = conn.execute(sql, params)
        conn.commit()
        result = (cur.lastrowid, cur.rowcount)
        cur.close()
        return result


def executemany(sql, seq_of_params):
    sql = _translate(sql)
    if config.DB_ENGINE == "mysql":
        conn = _mysql_conn()
        cur = conn.cursor()
        try:
            cur.executemany(sql, list(seq_of_params))
            conn.commit()
            return cur.rowcount
        finally:
            cur.close()

    with _sqlite_lock:
        conn = _sqlite_conn()
        cur = conn.executemany(sql, list(seq_of_params))
        conn.commit()
        count = cur.rowcount
        cur.close()
        return count


def load_json(value):
    """products.attributes is a JSON column in MySQL and TEXT in SQLite."""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}
