# storage/viewport.py
from __future__ import annotations
import duckdb
from typing import Optional, Tuple
import pandas as pd
import paths  # <-- use centralized paths
from utils.time_utils import to_ms

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
    include_parts: bool = True, 
    include_days: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(":memory:")

    # collect files
    cand_files = []
    for variant in (timeframe, timeframe.lower(), timeframe.upper()):
        d = paths.DATA_DIR / variant
        if d.exists():
            cand_files += [str(p) for p in d.rglob("*.parquet")]

    if not cand_files:
        return pd.DataFrame(), pd.DataFrame()  # candles empty, objects empty

    # robust read with union_by_name + timestamp normalization in SQL
    sql = """
    WITH src AS (
    -- union_by_name handles schema diffs between day and part files (e.g., missing global_x)
    SELECT *
    FROM read_parquet(?, union_by_name=1, hive_partitioning=1)
    ),
    norm AS (
    SELECT
        symbol,
        timeframe,
        COALESCE(
        try_strptime(replace(ts_iso, 'Z', '+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z'),
        try_strptime(replace(ts_iso, 'Z', '+00:00'), '%Y-%m-%dT%H:%M:%S%z'),
        to_timestamp(try_cast(ts AS DOUBLE) / 1000.0)  -- epoch ms → seconds
        ) AS ts,
        open, high, low, close, volume,
        try_cast(global_x AS BIGINT) AS global_x  -- may be NULL for part files
    FROM src
    )
    SELECT symbol, timeframe, ts, open, high, low, close, volume, global_x
    FROM norm
    WHERE ts IS NOT NULL AND ts BETWEEN ? AND ?
    ORDER BY ts
    """
    df_candles = con.execute(sql, [cand_files, t0_iso, t1_iso]).df()

    return df_candles, pd.DataFrame()

