# tools/csv_to_parquet_days.py
from __future__ import annotations
from pathlib import Path
import sys
import argparse
import pandas as pd

# Ensure repo root (where paths.py lives) is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import paths  # centralized paths  (storage/, data/, objects/, etc.)
import json

"""
Luckily This will only need to be run once (or very rarely).

How you’ll use it:

- Convert the entire CSV (with global_x):
python tools/csv_to_parquet_days.py --write-global --start-global 0

- Convert only the first N days (dry run / test):
python tools/csv_to_parquet_days.py --write-global --start-global 0 --limit-days 3 --out-dir storage/_tmp_data

- Convert without global_x (just candles):
python tools/csv_to_parquet_days.py

Arguments:
--csv           Path to input CSV (default: storage/csv/SPY_15_minute_candles.csv)
--symbol        Symbol tag (default: SPY)
--timeframe     Timeframe folder name (default: 15m)
--out-dir       Root output folder (default: storage/data)
--limit-days    Process only first N days (default: 0 → all days)
--write-global  Add a running global_x column
--start-global  Starting index for global_x (default: 0)

Output files:
storage/data/15m/YYYY-MM-DD.parquet (or under --out-dir if provided)
"""

def _summarize_files(paths, sample=3):
    n = len(paths)
    head = paths[:sample]
    tail = paths[-sample:] if n > sample else []
    return {"count": n, "head": head, "tail": tail}

def _write_atomic(df: pd.DataFrame, out_file: Path) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_file.with_suffix(out_file.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(out_file)  # atomic-ish on same volume

def csv_15m_to_days(
    *,
    csv_path: Path,
    symbol: str = "SPY",
    timeframe: str = "15m",
    write_global: bool = False,
    start_global: int = 0,
    out_dir: Path | None = None,
    limit_days: int = 0,
) -> dict:
    """
    Convert the big CSV of 15m candles into per-day Parquet files:
        storage/data/15m/YYYY-MM-DD.parquet

    Columns written match viewport expectations:
        symbol, timeframe, ts, open, high, low, close, volume

    If write_global=True, also add a 'global_x' column with a running index.
    """
    if not csv_path.exists():
        return {"ok": False, "reason": f"CSV not found: {csv_path}"}

    # Load + normalize time column
    df = pd.read_csv(csv_path)
    if "timestamp" not in df.columns:
        return {"ok": False, "reason": "CSV is missing required 'timestamp' column"}
    df = df.rename(columns={"timestamp": "ts"})
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.sort_values("ts").reset_index(drop=True)

    # Ensure 'volume' exists (viewer expects it)
    if "volume" not in df.columns:
        df["volume"] = 0.0

    # Group by day
    df["day"] = df["ts"].dt.strftime("%Y-%m-%d")
    days = sorted(df["day"].unique().tolist())
    if limit_days and limit_days > 0:
        days = days[:limit_days]

    # Resolve output root
    out_root = out_dir if out_dir else paths.DATA_DIR
    tf_dir = out_root / timeframe.lower()

    written = []
    g = start_global

    for day in days:
        day_df = df[df["day"] == day].copy().reset_index(drop=True)

        # Build the exact columns your viewport reads
        out_df = pd.DataFrame({
            "symbol":   symbol,
            "timeframe": timeframe,
            "ts":        day_df["ts"].dt.tz_localize(None).astype("datetime64[ns]"),
            "open":      day_df["open"].astype(float),
            "high":      day_df["high"].astype(float),
            "low":       day_df["low"].astype(float),
            "close":     day_df["close"].astype(float),
            "volume":    day_df["volume"].astype(float),
        })

        if write_global:
            n = len(out_df)
            out_df["global_x"] = range(g, g + n)
            g += n

        out_file = tf_dir / f"{day}.parquet"
        _write_atomic(out_df, out_file)
        written.append(str(out_file))

    return {
        "ok": True,
        "days": len(days),
        "files": _summarize_files(written, sample=3),
        "final_global": (g if write_global else None)
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=str(paths.SPY_15_MINUTE_CANDLES_PATH),
                    help="Path to the 15m CSV (default: storage/csv/SPY_15_minute_candles.csv)")
    ap.add_argument("--symbol", default="SPY")
    ap.add_argument("--timeframe", default="15m")
    ap.add_argument("--out-dir", default="", help="optional output root (default uses storage/data)")
    ap.add_argument("--limit-days", type=int, default=0, help="process only the first N days")
    ap.add_argument("--write-global", action="store_true", help="also write a running 'global_x' column")
    ap.add_argument("--start-global", type=int, default=0, help="starting index for global_x (default 0)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None
    res = csv_15m_to_days(
        csv_path=Path(args.csv),
        symbol=args.symbol,
        timeframe=args.timeframe,
        write_global=args.write_global,
        start_global=args.start_global,
        out_dir=out_dir,
        limit_days=args.limit_days,
    )
    print(json.dumps(res, indent=2))
