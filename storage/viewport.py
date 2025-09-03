# storage/viewport.py
from __future__ import annotations
import duckdb
from typing import Optional, Tuple
import pandas as pd
import paths  # <-- use centralized paths

def _candles_glob(timeframe: str) -> str:
    # picks up day files AND parts (recursive)
    return str((paths.DATA_DIR / timeframe / "**" / "*.parquet")).replace("\\", "/")

def _objects_glob(timeframe: str) -> str:
    return str((paths.OBJECTS_DIR / timeframe / "**" / "*.parquet")).replace("\\", "/")

def load_viewport(
    *,
    symbol: str,
    timeframe: str,          # "15m"
    t0_iso: str,             # "YYYY-MM-DDTHH:MM:SS-04:00"
    t1_iso: str,
    y0: Optional[float] = None,
    y1: Optional[float] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(":memory:")

    df_candles = con.execute("""
        SELECT symbol, timeframe, ts, open, high, low, close, volume
        FROM read_parquet(?)
        WHERE symbol = ? AND timeframe = ? AND ts BETWEEN ? AND ?
        ORDER BY ts
    """, [_candles_glob(timeframe), symbol, timeframe, t0_iso, t1_iso]).fetch_df()

    # Objects (parameterize everything; keep order aligned with placeholders)
    price_clause = ""
    # Base params: glob, symbol, timeframe, t1(for event_ts), t1(for coalesce), t0
    params = [_objects_glob(timeframe), symbol, timeframe, t1_iso, t1_iso, t0_iso]
    if y0 is not None and y1 is not None:
        price_clause = " AND y_max >= ? AND y_min <= ?"
        params += [y0, y1]

    df_objects = con.execute(f"""
        WITH ev AS (
            SELECT *
            FROM read_parquet(?)
            WHERE symbol = ? AND timeframe = ? AND event_ts <= ?
        ),
        last_state AS (
            SELECT *,
                ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY event_ts DESC) AS rn
            FROM ev
        )
        SELECT object_id, object_type, action, t_start, t_end, y_min, y_max, payload
        FROM last_state
        WHERE rn = 1
            AND COALESCE(t_end, ?) >= ?
        {price_clause}
    """, params).fetch_df()

    return df_candles, df_objects
