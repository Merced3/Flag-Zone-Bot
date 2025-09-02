# storage/duck.py
import duckdb, threading

_lock = threading.Lock()
_conn = None

def conn():
    global _conn
    with _lock:
        if _conn is None:
            _conn = duckdb.connect(":memory:")
        return _conn

"""
    `storage/duck.py` is an ultra-minimal singleton creating a DuckDB in-memory
    connection. You ended up not needing it on the write path anymore (we write 
    via Pandas/Arrow), but it’s still useful if you later add small read helpers 
    or one-off queries. It’s intentionally simple to avoid Windows driver quirks.
"""