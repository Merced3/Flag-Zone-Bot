# tools/normalize_ts_all.py
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import pandas as pd
from utils.time_utils import to_ms, to_iso

def _is_int_series(s: pd.Series) -> bool:
    return pd.api.types.is_integer_dtype(s) or s.dtype.kind in ("i", "u")

def normalize_file(path: Path, dry_run: bool = False, verbose: bool = False) -> dict:
    """Normalize a single parquet file's timestamps to:
       - ts: int64 epoch ms (UTC)
       - ts_iso: ISO8601 UTC ('Z') string
       Returns a small result dict.
    """
    try:
        df = pd.read_parquet(path)
    except Exception as e:
        return {"ok": False, "path": str(path), "reason": f"read_error: {e}"}

    if df.empty:
        return {"ok": True, "path": str(path), "changed": False, "rows": 0, "reason": "empty"}

    changed = False

    # 1) Ensure we have a 'ts' column in int64 ms
    if "ts" in df.columns:
        s = df["ts"]
        if _is_int_series(s):
            # Detect nanoseconds by magnitude (anything way above ms range)
            if s.abs().max() > 10**16:
                df["ts"] = (s // 1_000_000).astype("int64")
                changed = True
        else:
            # strings/datetime/etc → ms
            df["ts"] = s.apply(to_ms).astype("int64")
            changed = True
    elif "timestamp" in df.columns:
        df["ts"] = df["timestamp"].apply(to_ms).astype("int64")
        changed = True
    elif "ts_iso" in df.columns:
        # If we only have ISO, derive ms from it
        df["ts"] = pd.to_datetime(df["ts_iso"], utc=True).view("int64") // 1_000_000
        changed = True
    else:
        return {"ok": False, "path": str(path), "reason": "no ts/timestamp/ts_iso column"}

    # 2) Ensure 'ts_iso' exists (or recompute to be safe/consistent)
    if "ts_iso" not in df.columns:
        df["ts_iso"] = df["ts"].apply(to_iso)
        changed = True
    else:
        # normalize to UTC-Z format
        iso_new = df["ts"].apply(to_iso)
        if not (iso_new == df["ts_iso"].astype(str)).all():
            df["ts_iso"] = iso_new
            changed = True

    # 3) Sort by ts to keep files tidy/consistent
    df = df.sort_values("ts").reset_index(drop=True)

    # 4) Write back atomically if changed
    if changed and not dry_run:
        tmp = path.with_suffix(path.suffix + ".tmp")
        df.to_parquet(tmp, index=False)
        tmp.replace(path)

    if verbose and changed:
        print(f"[ok] normalized {path}")

    return {"ok": True, "path": str(path), "changed": changed, "rows": len(df)}

def main():
    ap = argparse.ArgumentParser(description="Normalize parquet ts → int64 ms (UTC) + ts_iso")
    ap.add_argument("--root", default="storage/data", help="Root folder containing timeframes (default: storage/data)")
    ap.add_argument("--timeframes", nargs="*", default=["2m", "5m", "15m"],
                    help="Which TFs to scan (default: 2m 5m 15m)")
    ap.add_argument("--pattern", default="*.parquet", help="Glob pattern (default: *.parquet)")
    ap.add_argument("--recurse", action="store_true", help="Recurse into subfolders (to catch part-*.parquet)")
    ap.add_argument("--dry-run", action="store_true", help="Report changes but do not write")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N files processed (debug)")
    ap.add_argument("--verbose", action="store_true", help="Print each changed file")
    args = ap.parse_args()

    root = Path(args.root)
    total = changed = skipped = errors = 0
    touched = []

    for tf in args.timeframes:
        base = root / tf
        if not base.exists():
            print(f"[warn] missing timeframe dir: {base}")
            continue
        files = base.rglob(args.pattern) if args.recurse else base.glob(args.pattern)
        for i, p in enumerate(files, start=1):
            res = normalize_file(p, dry_run=args.dry_run, verbose=args.verbose)
            total += 1
            if not res.get("ok"):
                errors += 1
                if args.verbose:
                    print(f"[err] {p}: {res.get('reason')}")
            else:
                if res.get("changed"):
                    changed += 1
                    touched.append(str(p))
                else:
                    skipped += 1
            if args.limit and total >= args.limit:
                break

    print({
        "ok": errors == 0,
        "scanned": total,
        "changed": changed,
        "unchanged": skipped,
        "errors": errors
    })
    if args.verbose and touched:
        print("Changed files:")
        for t in touched:
            print(" -", t)

if __name__ == "__main__":
    main()

"""
HOW TO RUN

Dry run first (no writes, show what would change):
`python tools/normalize_ts_all.py --root storage/data --recurse --verbose --dry-run`

Do the actual normalization (all TFs):
`python tools/normalize_ts_all.py --root storage/data --recurse --verbose`

Only 15m dayfiles (no parts):
`Only 15m dayfiles (no parts):`

Limit for quick smoke test:
`python tools/normalize_ts_all.py --root storage/data --recurse --limit 10 --verbose`
"""