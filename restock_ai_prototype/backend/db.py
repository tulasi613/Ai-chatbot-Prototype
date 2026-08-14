"""
Thin MySQL connection helper built on mysql-connector-python.
"""
import mysql.connector
from mysql.connector import pooling
from config import DB_CONFIG

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="restock_pool",
            pool_size=5,
            **DB_CONFIG
        )
    return _pool


def get_connection():
    """Returns a live MySQL connection from the pool."""
    return get_pool().get_connection()


def query(sql, params=None, fetchone=False):
    """Run a SELECT and return rows as list of dicts (or a single dict)."""
    conn = get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        if fetchone:
            return rows[0] if rows else None
        return rows
    finally:
        conn.close()


def execute(sql, params=None):
    """Run an INSERT/UPDATE/DELETE and return (lastrowid, rowcount)."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        lastrowid, rowcount = cur.lastrowid, cur.rowcount
        cur.close()
        return lastrowid, rowcount
    finally:
        conn.close()
