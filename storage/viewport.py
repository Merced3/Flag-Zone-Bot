# storage/viewport.py

import os
from typing import List, Tuple, Optional
import pandas as pd
import duckdb
from pathlib import Path

# --- robust import of root-level paths.py ---
try:
    import paths  # project-root module
except ModuleNotFoundError:
    import sys
    ROOT = Path(__file__).resolve().parents[1]  # project root (contains paths.py)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import paths
# --------------------------------------------

MARKET_TZ = 'America/Chicago'
DEBUG_VIEWPORT = os.getenv("DEBUG_VIEWPORT") == "1"

def _to_local_naive_iso_bound(s: str) -> str:
    """
    Convert any ISO string (with/without offset) into a local-naive ISO
    in MARKET_TZ, matching _ts_sql_expr() which yields local timestamps.
    """
    ts = pd.Timestamp(s)
    if ts.tzinfo is None:
        # assume local wall-clock intended; localize to market tz
        ts = ts.tz_localize(MARKET_TZ)
    else:
        ts = ts.tz_convert(MARKET_TZ)
    return ts.tz_localize(None).isoformat()

def _parquet_has_column(file_list, column_name: str) -> bool:
    if not file_list:
        return False
    con = duckdb.connect(":memory:")
    try:
        # LIMIT 0 returns schema only, fast; union_by_name handles mixed schemas
        desc = con.execute(
            "SELECT * FROM read_parquet(?, union_by_name=1, hive_partitioning=1) LIMIT 0",
            [file_list]
        ).description
        cols = [c[0] for c in desc] if desc else []
        return column_name in cols
    finally:
        con.close()

def _collect_candle_files(timeframe: str, include_days: bool, include_parts: bool):
    # Use a set of real (resolved) paths to avoid duplicates on case-insensitive filesystems
    seen = set()
    out = []

    # Collapse variants to a set so we don't iterate identical strings twice
    for variant in {timeframe, timeframe.lower(), timeframe.upper()}:
        root = Path(paths.DATA_DIR) / variant
        if not root.exists():
            continue

        if include_days:
            for p in root.glob("*.parquet"):
                rp = str(p.resolve())
                if rp not in seen:
                    seen.add(rp)
                    out.append(rp)

        if include_parts:
            # parts live under date folders; skip any non-part files
            for p in root.glob("*/*.parquet"):
                if p.name.startswith("part-"):
                    rp = str(p.resolve())
                    if rp not in seen:
                        seen.add(rp)
                        out.append(rp)

    return out

def _ts_sql_expr() -> str:
    """Normalized timestamp expression in local (chart) time."""
    return f"""(COALESCE(
        try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z'),
        try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S%z'),
        to_timestamp(try_cast(ts AS DOUBLE)/1000.0)
    ) AT TIME ZONE '{MARKET_TZ}')"""

def get_timeframe_bounds(
    *, timeframe: str,
    include_days: bool = True,
    include_parts: bool = True,
):
    files = _collect_candle_files(timeframe, include_days, include_parts)
    if not files:
        return None, None, 0
    con = duckdb.connect(":memory:")
    row = con.execute(f"""
        WITH src AS (SELECT * FROM read_parquet(?, union_by_name=1)),
            norm AS (SELECT {_ts_sql_expr()} AS ts FROM src WHERE ts IS NOT NULL)
        SELECT min(ts), max(ts) FROM norm
    """, [files]).fetchone()
    min_ts = pd.Timestamp(row[0]) if row and row[0] else None
    max_ts = pd.Timestamp(row[1]) if row and row[1] else None
    return min_ts, max_ts, len(files)

def pick_distinct_trading_dates_sql(
    timeframe: str,
    *,
    days: int,
    anchor_date: Optional[str] = None,   # "YYYY-MM-DD" or None for "latest"
    symbol: Optional[str] = None         # optional filter if you add multi-symbol later
) -> List[str]:
    """
    Return an ascending list of the last `days` DISTINCT trading dates present
    in EOD files only, optionally anchored to <= anchor_date.
    """
    files = _collect_candle_files(timeframe, include_days=True, include_parts=False)
    if not files or days < 1:
        return []

    con = duckdb.connect(":memory:")

    # Build WHERE fragments
    where_sym  = "AND symbol = ?" if symbol else ""
    where_anch = "WHERE d <= ?" if anchor_date else ""

    params: List[object] = [files]
    if symbol:
        params.append(symbol)
    if anchor_date:
        params.append(anchor_date)
    params.append(days)

    rows = con.execute(f"""
      WITH src  AS (
        SELECT * FROM read_parquet(?, union_by_name=1)
      ),
      norm AS (
        SELECT
          -- local wall-clock timestamp for consistent chart filters
          {_ts_sql_expr()} AS ts
          {", symbol" if symbol else ""}
        FROM src
        WHERE ts IS NOT NULL
        {where_sym}
      ),
      dd AS (
        SELECT CAST(ts AS DATE) AS d FROM norm
      )
      SELECT d
      FROM dd
      {where_anch}
      GROUP BY d
      ORDER BY d DESC
      LIMIT ?
    """, params).fetchall()

    if not rows:
        return []

    # rows come newest→oldest; return ascending
    dates_desc = [str(r[0]) for r in rows]
    return list(reversed(dates_desc))

def days_window(
    timeframe: str,
    days: int,
    *,
    anchor_date: Optional[str] = None,
    symbol: Optional[str] = None
) -> Tuple[str, str, List[str]]:
    """
    Exactly `days` trading dates from EOD files (no parts).
      - If anchor_date is None, anchor to the latest date present.
      - Returns (t0_iso, t1_iso, picked_dates_asc).
    """
    picked = pick_distinct_trading_dates_sql(timeframe, days=days, anchor_date=anchor_date, symbol=symbol)
    if not picked:
        return "1900-01-01T00:00:00", "1900-01-01T00:00:01", []

    t0_iso = f"{picked[0]}T00:00:00"
    t1_iso = f"{picked[-1]}T23:59:59.999999"

    if DEBUG_VIEWPORT:
        print(f"[days_window.sql] tf={timeframe} N={days} anchor={anchor_date} → {picked[0]} … {picked[-1]} (N={len(picked)})")

    return t0_iso, t1_iso, picked

def load_viewport(*,
    symbol: str,
    timeframe: str,          # "15m"
    t0_iso: str,             # "YYYY-MM-DDTHH:MM:SS-04:00"
    t1_iso: str,
    y0=None,
    y1=None,
    include_parts: bool = True, 
    include_days: bool = True
):
    con = duckdb.connect(":memory:")
    cand_files = _collect_candle_files(timeframe, include_days, include_parts)

    if not cand_files:
        if DEBUG_VIEWPORT:
            print(f"[viewport] timeframe={timeframe} files=0")
        return pd.DataFrame(), pd.DataFrame()

    # detect if these files have 'global_x'
    has_gx = _parquet_has_column(cand_files, "global_x")
    gx_expr = "try_cast(global_x AS BIGINT) AS gx" if has_gx else "CAST(NULL AS BIGINT) AS gx"
    if DEBUG_VIEWPORT:
        print(f"[viewport] has_global_x={has_gx} parts={include_parts} days={include_days}")

    # normalize bounds to local-naive to match _ts_sql_expr() output
    t0_local = _to_local_naive_iso_bound(t0_iso)
    t1_local = _to_local_naive_iso_bound(t1_iso)

    # optional y-range (price) overlap filter
    price_clause = ""
    price_params = []
    if y0 is not None and y1 is not None:
        lo, hi = (float(y0), float(y1)) if y0 <= y1 else (float(y1), float(y0))
        # overlap test: NOT (bar entirely below OR entirely above)
        price_clause = " AND NOT (high < ? OR low > ?)"
        price_params = [lo, hi]
    
    sql = f"""
    WITH src AS (
        SELECT * FROM read_parquet(?, union_by_name=1, hive_partitioning=1)
    ), norm AS (
        SELECT
            symbol, timeframe,
            {_ts_sql_expr()} AS ts,
            open, high, low, close, volume,
            {gx_expr}
        FROM src
    )
    SELECT
        symbol, timeframe, ts, open, high, low, close, volume,
        gx AS global_x
    FROM norm
    WHERE ts IS NOT NULL
        AND symbol = ?
        AND ts BETWEEN ? AND ?{price_clause}
    ORDER BY ts
    """

    if DEBUG_VIEWPORT:
        print(f"[viewport] timeframe={timeframe} files={len(cand_files)}  (examples: {cand_files[:2]})")
        print(f"[viewport] window: {t0_iso} → {t1_iso} y={y0},{y1}")

    params = [cand_files, symbol, t0_local, t1_local] + price_params
    df_candles = con.execute(sql, params).df()

    df_objects = pd.DataFrame()

    # De-dup identical bars when days & parts overlap the same window
    if not df_candles.empty:
        before = len(df_candles)
        df_candles = (
            df_candles
            .drop_duplicates(subset=["symbol", "timeframe", "ts"], keep="last")
            .reset_index(drop=True)
        )
        if DEBUG_VIEWPORT and before != len(df_candles):
            print(f"[viewport] de-duped rows: {before} → {len(df_candles)} (by symbol,timeframe,ts)")
    
    if DEBUG_VIEWPORT:
        print(f"[viewport] rows={len(df_candles)} | window:", t0_iso, "→", t1_iso)

    return df_candles, df_objects

"""
# CLI "lab" for quick testing

## How to use Dev Env:
**TURN ON:**
 - Powershell: $env:DEBUG_VIEWPORT="1"
 - zsh/macOS: export DEBUG_VIEWPORT=1
**TURN OFF:**
 - Powershell: IDK YET
 - zsh/macOS: unset DEBUG_VIEWPORT


## How to use `viewport.py`:

### Quick zones check (15 EOD days on 15M):
```bash
python -m storage.viewport --tf 15M zones --days 15
```

### Quick live check (26 bars on 15M, anchored to latest data you have):
```bash
python -m storage.viewport --tf 15M live  --bars 26 --anchor latest
```

### Live on 2M (195 bars), clip to today’s session open:
```bash
python -m storage.viewport --tf 2M  live  --bars 195 --anchor now --clip-session
```

### Raw custom window, parts only in 5M:
```bash
python -m storage.viewport --tf 5M  raw   --include-parts --t0 2025-10-22T09:30:00 --t1 2025-10-22T16:00:00
```

## You’ll get clean prints like:
```bash
[LAB] ZONES tf=15M days=15 include_days=True include_parts=False
[LAB] EOD bounds: files=4020 min=2020-05-26 ... max=2025-10-21 ...
[LAB] ZONES rows=xxxx
[LAB] first=... last=... days=15

[LAB] LIVE  tf=15M bars=26 anchor=latest include_days=False include_parts=True
[LAB] PARTS bounds: files=60 min=2025-10-22 ... max=2025-10-22 ...
[LAB] LIVE rows=26
[LAB] first=... last=...
```

"""

if __name__ == "__main__":
    import argparse

    def bar_minutes(tf: str) -> int:
        tf = str(tf)
        return int(''.join(ch for ch in tf if ch.isdigit())) or 1

    ap = argparse.ArgumentParser(description="Viewport debug lab")
    ap.add_argument("--tf", default="15M", help="Timeframe: 2M|5M|15M (case-insensitive)")
    ap.add_argument("--symbol", default="SPY")
    sub = ap.add_subparsers(dest="mode", required=False)

    # Zones mode: last N EOD days (no parts)
    ap_z = sub.add_parser("zones", help="EOD-only window")
    ap_z.add_argument("--days", type=int, default=15)

    # Live mode: last K bars, parts-only
    ap_l = sub.add_parser("live", help="parts-only window")
    ap_l.add_argument("--bars", type=int, default=26, help="bars cap")
    ap_l.add_argument("--anchor", default="now", help="now | latest | DATE:YYYY-MM-DD")
    ap_l.add_argument("--clip-session", action="store_true", help="Clamp t0 to session open")

    # Raw mode: custom include flags + absolute window
    ap_r = sub.add_parser("raw", help="custom include flags and ISO window")
    ap_r.add_argument("--include-days", action="store_true")
    ap_r.add_argument("--include-parts", action="store_true")
    ap_r.add_argument("--t0", required=True, help="ISO start e.g. 2025-10-21T09:30:00")
    ap_r.add_argument("--t1", required=True, help="ISO end")

    args = ap.parse_args()
    tf = args.tf

    # Print bounds per the mode and then run the call
    if args.mode in (None, "zones"):
        t0, t1, picked = days_window(tf, args.days)
        print(f"[LAB] window: {t0} → {t1}  (trading days={len(picked)}; first={picked[0] if picked else None}, last={picked[-1] if picked else None})")

        df, _ = load_viewport(
            symbol=args.symbol, timeframe=tf,
            t0_iso=t0, t1_iso=t1,
            include_days=True, include_parts=False,
        )
        print(f"[LAB] ZONES rows={len(df)}")
        if not df.empty:
            ts = pd.to_datetime(df["ts"], errors="coerce")
            print(f"[LAB] first={ts.iloc[0]}  last={ts.iloc[-1]}  days={len(ts.dt.date.unique())}")

    if args.mode in (None, "live"):
        bars = getattr(args, "bars", 26)
        anchor = getattr(args, "anchor", "now").lower()
        print(f"\n[LAB] LIVE   tf={tf}  bars={bars}  anchor={anchor}  include_days=False  include_parts=True")
        min_ts, max_ts, nfiles = get_timeframe_bounds(timeframe=tf, include_days=False, include_parts=True)
        print(f"[LAB] PARTS bounds: files={nfiles} min={min_ts}  max={max_ts}")

        # Resolve anchor
        if anchor == "latest" and max_ts is not None:
            t1 = pd.Timestamp(max_ts)
        elif anchor.startswith("date:"):
            day = anchor.split(":", 1)[1]
            t1 = pd.Timestamp(day).replace(hour=23, minute=59, second=59)
        else:
            t1 = pd.Timestamp.now()

        tfmin = bar_minutes(tf)
        t0 = t1 - pd.Timedelta(minutes=bars * tfmin)

        if getattr(args, "clip_session", False):
            # 09:30 local
            sess_open = t1.tz_localize(None).replace(hour=9, minute=30, second=0, microsecond=0)
            t0 = max(t0, sess_open)

        df2, _ = load_viewport(symbol=args.symbol, timeframe=tf,
                               t0_iso=t0.isoformat(), t1_iso=t1.isoformat(),
                               include_days=False, include_parts=True)
        print(f"[LAB] LIVE rows={len(df2)}")
        if not df2.empty:
            print(f"[LAB] first={df2['ts'].iloc[0]}  last={df2['ts'].iloc[-1]}")

    if args.mode == "raw":
        print(f"\n[LAB] RAW    tf={tf}  include_days={args.include_days} include_parts={args.include_parts}")
        df3, _ = load_viewport(symbol=args.symbol, timeframe=tf,
                               t0_iso=args.t0, t1_iso=args.t1,
                               include_days=args.include_days, include_parts=args.include_parts)
        print(f"[LAB] RAW rows={len(df3)}")
        if not df3.empty:
            print(f"[LAB] first={df3['ts'].iloc[0]}  last={df3['ts'].iloc[-1]}")
