import os
import threading
from psycopg2 import pool as pg_pool
from dotenv import load_dotenv

load_dotenv()

_pool = None
_lock = threading.Lock()


def _get_pool():
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                dsn = os.getenv("DATABASE_URL") or (
                    f"dbname=trackist user={os.getenv('USER')} host=localhost"
                )
                _pool = pg_pool.SimpleConnectionPool(1, 10, dsn)
    return _pool


class _PooledConnection:
    """Wraps a psycopg2 connection so close() returns it to the pool."""

    def __init__(self, conn):
        self._conn = conn

    def close(self):
        try:
            _get_pool().putconn(self._conn)
        except Exception:
            self._conn.close()

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_db():
    """Return a pooled connection. Call conn.close() as usual to return it."""
    return _PooledConnection(_get_pool().getconn())
