# storage/viewport.py
from __future__ import annotations
import duckdb
from typing import Optional, Tuple
import pandas as pd
import paths  # <-- use centralized paths
from utils.time_utils import to_ms
import os
DEBUG_VIEWPORT = os.getenv("DEBUG_VIEWPORT") == "1"

def _collect_candle_files(timeframe: str, include_days: bool, include_parts: bool) -> list[str]:
    files: list[str] = []
    for variant in (timeframe, timeframe.lower(), timeframe.upper()):
        root = paths.DATA_DIR / variant
        if not root.exists():
            continue
        if include_days:
            # EOD day files at the root of the TF dir:  <TF>/<YYYY-MM-DD>.parquet
            files += [str(p) for p in root.glob("*.parquet")]
        if include_parts:
            # live “part-*” files are under subfolders: <TF>/<YYYY-MM-DD>/part-*.parquet
            for sub in root.iterdir():
                if sub.is_dir():
                    files += [str(p) for p in sub.glob("*.parquet")]
    return files

def get_timeframe_bounds(*, timeframe: str) -> tuple[pd.Timestamp|None, pd.Timestamp|None]:
    files = _collect_candle_files(timeframe, include_days=True, include_parts=True)
    if not files:
        return None, None
    con = duckdb.connect(":memory:")
    row = con.execute("""
      WITH src AS (SELECT * FROM read_parquet(?, union_by_name=1)),
           norm AS (SELECT COALESCE(
                       try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z'),
                       try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S%z'),
                       to_timestamp(try_cast(ts AS DOUBLE)/1000.0)
                     ) AS ts FROM src)
      SELECT min(ts), max(ts) FROM norm WHERE ts IS NOT NULL
    """, [files]).fetchone()
    return (pd.Timestamp(row[0]) if row and row[0] else None,
            pd.Timestamp(row[1]) if row and row[1] else None)

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
    cand_files = _collect_candle_files(timeframe, include_days, include_parts)

    if not cand_files:
        return pd.DataFrame(), pd.DataFrame()

    sql = """
    WITH src AS (
      SELECT * FROM read_parquet(?, union_by_name=1, hive_partitioning=1)
    ), norm AS (
      SELECT
        symbol, timeframe,
        COALESCE(
          try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z'),
          try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S%z'),
          to_timestamp(try_cast(ts AS DOUBLE)/1000.0)
        ) AS ts,
        open, high, low, close, volume,
        try_cast(global_x AS BIGINT) AS global_x
      FROM src
    )
    SELECT symbol, timeframe, ts, open, high, low, close, volume, global_x
    FROM norm
    WHERE ts IS NOT NULL AND ts BETWEEN ? AND ?
    ORDER BY ts
    """
    if DEBUG_VIEWPORT:
        print(f"[viewport] timeframe={timeframe} files={len(cand_files)} (examples: {cand_files[:2]})")

    df_candles = con.execute(sql, [cand_files, t0_iso, t1_iso]).df()

    if DEBUG_VIEWPORT:
        print("[viewport] rows=" + (str(len(df_candles)) if not df_candles.empty else "0"),
              "window:", t0_iso, "→", t1_iso)

    return df_candles, pd.DataFrame()

