# storage/viewport.py

import os
from typing import List, Tuple, Optional
import pandas as pd
import duckdb
import paths

MARKET_TZ = 'America/Chicago'

DEBUG_VIEWPORT = os.getenv("DEBUG_VIEWPORT") == "1"

def _collect_candle_files(timeframe: str, include_days: bool, include_parts: bool) -> List[str]:
    files: List[str] = []
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

def _ts_sql_expr() -> str:
    """Normalized timestamp expression in local (chart) time."""
    return f"""(COALESCE(
        try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S.%f%z'),
        try_strptime(replace(ts_iso,'Z','+00:00'), '%Y-%m-%dT%H:%M:%S%z'),
        to_timestamp(try_cast(ts AS DOUBLE)/1000.0)
    ) AT TIME ZONE '{MARKET_TZ}')"""

def get_timeframe_bounds(*, timeframe: str,
                         include_days: bool = True,
                         include_parts: bool = True) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp], int]:
    files = _collect_candle_files(timeframe, include_days, include_parts)
    if not files:
        return None, None, 0
    con = duckdb.connect(":memory:")
    row = con.execute(f"""
        WITH src AS (SELECT * FROM read_parquet(?, union_by_name=1)),
            norm AS (SELECT {_ts_sql_expr()} AS ts FROM src)
        SELECT min(ts), max(ts) FROM norm WHERE ts IS NOT NULL
    """, [files]).fetchone()
    min_ts = pd.Timestamp(row[0]) if row and row[0] else None
    max_ts = pd.Timestamp(row[1]) if row and row[1] else None
    return min_ts, max_ts, len(files)

def load_viewport(
    *,
    symbol: str,
    timeframe: str,          # "15m"
    t0_iso: str,             # "YYYY-MM-DDTHH:MM:SS-04:00"
    t1_iso: str,
    y0=None,
    y1=None,
    include_parts: bool = True, 
    include_days: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(":memory:")
    cand_files = _collect_candle_files(timeframe, include_days, include_parts)

    if not cand_files:
        return pd.DataFrame(), pd.DataFrame()

    sql = f"""
    WITH src AS (
      SELECT * FROM read_parquet(?, union_by_name=1, hive_partitioning=1)
    ), norm AS (
      SELECT
        symbol, timeframe,
        {_ts_sql_expr()} AS ts,
        open, high, low, close, volume,
        try_cast(global_x AS BIGINT) AS gx
      FROM src
    )
    SELECT
      symbol, timeframe, ts, open, high, low, close, volume,
      gx AS global_x
    FROM norm
    WHERE ts IS NOT NULL AND ts BETWEEN ? AND ?
    ORDER BY ts
    """
    if DEBUG_VIEWPORT:
        print(f"[viewport] timeframe={timeframe} files={len(cand_files)}",
              f" (examples: {cand_files[:2]})")

    df_candles = con.execute(sql, [cand_files, t0_iso, t1_iso]).df()

    if DEBUG_VIEWPORT:
        print(f"[viewport] rows={0 if df_candles.empty else len(df_candles)}",
              "window:", t0_iso, "→", t1_iso)

    return df_candles, pd.DataFrame()


"""
# CLI "lab" for quick testing


## How to use:

1) Quick zones check (15 EOD days on 15M):
```bash
python storage\viewport.py zones --tf 15M --days 15
```

2) Quick live check (26 bars on 15M, anchored to latest data you have):
```bash
python storage\viewport.py live --tf 15M --bars 26 --anchor latest
```

3) Live on 2M (195 bars), clip to today’s session open:
```bash
python storage\viewport.py live --tf 2M --bars 195 --anchor now --clip-session
```

4) Raw custom window, parts only in 5M:
```bash
python storage\viewport.py raw --tf 5M --include-parts --t0 2025-10-22T09:30:00 --t1 2025-10-22T16:00:00
```

5) You’ll get clean prints like:
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
        days = args.days if args.mode else 15
        t1 = pd.Timestamp.now()
        t0 = t1 - pd.Timedelta(days=days + 5)  # cushion
        print(f"\n[LAB] ZONES  tf={tf}  days={days}  include_days=True  include_parts=False")
        min_ts, max_ts, nfiles = get_timeframe_bounds(timeframe=tf, include_days=True, include_parts=False)
        print(f"[LAB] EOD bounds: files={nfiles} min={min_ts}  max={max_ts}")
        df, _ = load_viewport(symbol=args.symbol, timeframe=tf,
                              t0_iso=t0.isoformat(), t1_iso=t1.isoformat(),
                              include_days=True, include_parts=False)
        print(f"[LAB] ZONES rows={len(df)}")
        if not df.empty:
            print(f"[LAB] first={df['ts'].iloc[0]}  last={df['ts'].iloc[-1]}  days={len(pd.to_datetime(df['ts']).dt.date.unique())}")

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
