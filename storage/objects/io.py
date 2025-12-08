# storage/objects/io.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np
import os, time
import paths

"""
This script functions as a "Stored Procedures" module for object storage.

This folder contains functions to read/write object storage files.
- Current snapshot: paths.CURRENT_OBJECTS_PATH (single parquet file)
- Timeline events: paths.TIMELINE_OBJECTS_DIR/YYYY-MM/YYYY-MM-DD.parquet (partitioned by day)
Parquet is used for efficiency and schema enforcement.
"""

# ───🔹 SCHEMA & ENFORCEMENT ─────────────────────────────────────────────
SCHEMA = {
    "id": "string",
    "type": "string",
    "left": "Int64",          # nullable int
    "y": "Float64",
    "top": "Float64",
    "bottom": "Float64",
    "status": "string",
    "symbol": "string",
    "timeframe": "string",
    "created_ts": "Int64",
    "updated_ts": "Int64",
    "created_step": "Int64",
    "updated_step": "Int64",
}

REQ_COLS = list(SCHEMA.keys())

def _enforce_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure required columns exist and have consistent nullable dtypes."""
    out = df.copy()
    for c, dt in SCHEMA.items():
        if c not in out.columns:
            out[c] = pd.NA
    # reorder then cast
    out = out[REQ_COLS]
    # cast with pandas nullable dtypes
    for c, dt in SCHEMA.items():
        try:
            out[c] = out[c].astype(dt)
        except TypeError:
            # fallback: coerce numerics, then astype
            if dt in ("Int64", "Float64"):
                out[c] = pd.to_numeric(out[c], errors="coerce")
                out[c] = out[c].astype(dt)
            else:
                out[c] = out[c].astype("string")
    return out

# ───🔹 PATHS & STORAGE ───────────────────────────────────────────────────

def _cur_path(): return paths.CURRENT_OBJECTS_PATH
def _timeline_dir(): return paths.TIMELINE_OBJECTS_DIR

def _ensure_dirs():
    _cur_path().parent.mkdir(parents=True, exist_ok=True)
    _timeline_dir().mkdir(parents=True, exist_ok=True)

# ───🔹 LOADERS ───────────────────────────────────────────────────────────

def load_current_objects(columns: list[str] | None = None) -> pd.DataFrame:
    _ensure_dirs()
    try:
        df = pd.read_parquet(_cur_path())
        df = _enforce_schema(df)
        if columns:
            # make sure requested columns exist even if empty
            for c in columns:
                if c not in df.columns:
                    df[c] = pd.NA
            df = df[columns]
        return df
    except FileNotFoundError:
        cols = columns or REQ_COLS
        return _enforce_schema(pd.DataFrame(columns=cols))

def load_timeline_day(day: str) -> pd.DataFrame:
    """
    Load timeline events for YYYY-MM-DD, or empty frame if missing.
    """
    p = _timeline_dir() / day[:7] / f"{day}.parquet"
    try:
        return pd.read_parquet(p)
    except FileNotFoundError:
        return pd.DataFrame(columns=[
            "step","ts","action","reason","object_id","type","left","y","top","bottom","status","symbol","timeframe"
        ])

# ───🔹 HELPERS ───────────────────────────────────────────────────────────

def _replace_with_retries(src: Path, dst: Path, *, attempts: int = 8, delay: float = 0.05):
    """
    Cross-platform atomic replace with Windows-friendly retries.
    """
    last_err = None
    for i in range(attempts):
        try:
            os.replace(src, dst)     # atomic on Windows & POSIX
            return
        except PermissionError as e:  # indexer/AV held file for a moment
            last_err = e
            time.sleep(delay * (i + 1))  # linear backoff
    # If we get here, surface the last error (helps debug a real lock)
    raise last_err

def _normalize_ts(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_iso" in df.columns:
        ts = pd.to_datetime(df["ts_iso"], errors="coerce", utc=True)
    else:
        s = pd.to_numeric(df.get("ts"), errors="coerce")
        ts = pd.to_datetime(s, unit="ms", errors="coerce", utc=True)
    df["ts"] = ts.dt.tz_convert(None)
    return df

def read_current_objects(symbol: str | None = None, timeframe: str | None = None) -> pd.DataFrame:
    p = _cur_path()
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    df = _normalize_ts(df)
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if timeframe and "timeframe" in df.columns:
        df = df[df["timeframe"].astype(str).str.lower() == timeframe.lower()]
    return df.sort_values("ts").reset_index(drop=True)

# ───🔹 WRITERS / UPSERTS ────────────────────────────────────────────────

def write_current_objects(df: pd.DataFrame) -> None:
    """
    Atomically write the current snapshot parquet file.
    """
    _ensure_dirs()
    df = _enforce_schema(df)

    out = _cur_path()
    tmp = out.with_name(out.name + ".tmp")

    # 1) write to a temp file (closed once to_parquet returns)
    df.to_parquet(tmp, index=False)
    
    # 2) atomic replace with Windows-friendly retries
    _replace_with_retries(tmp, out)

def upsert_current_objects(changes: pd.DataFrame) -> None:
    # normalize incoming
    df_changes = _enforce_schema(changes)

    # current snapshot
    cur = load_current_objects()
    cur_idx = (cur.set_index("id") if not cur.empty else
               _enforce_schema(pd.DataFrame(columns=REQ_COLS)).set_index("id"))
    ch_idx = df_changes.set_index("id")

    # 1) update overlap via DataFrame.update (keeps dtypes, no warnings)
    overlap = cur_idx.index.intersection(ch_idx.index)
    if len(overlap):
        cur_idx.update(ch_idx.loc[overlap])

    # 2) append new ids (dtypes already aligned)
    new_ids = ch_idx.index.difference(cur_idx.index)
    if len(new_ids):
        cur_idx = pd.concat([cur_idx, ch_idx.loc[new_ids]], axis=0)

    # 3) prune removed (only keep active)
    cur_idx = cur_idx[cur_idx["status"].fillna("active") != "removed"]

    write_current_objects(cur_idx.reset_index())

def append_timeline_events(events: pd.DataFrame) -> Path:
    """
    Append event rows (one per object event).
    Required columns (at minimum):
      day_step/int or step, ts, action, reason, object_id, type/..., etc.
    Partition by day under TIMELINE_OBJECTS_DIR/YYYY-MM/YYYY-MM-DD.parquet
    """

    _ensure_dirs()

    if "ts" not in events.columns:
        raise ValueError("events must include 'ts' column")

    ev = events.copy()

    # Normalize 'ts' to UTC datetime64[ns] robustly
    if pd.api.types.is_numeric_dtype(ev["ts"]):  # e.g., int64 ms
        ev["ts"] = pd.to_datetime(ev["ts"].astype("int64"), unit="ms", utc=True)
    else:  # strings or datetimes -> to UTC
        ev["ts"] = pd.to_datetime(ev["ts"], utc=True)

    # Day routing
    day = ev["ts"].dt.tz_convert("UTC").dt.normalize().iloc[0]
    day_str = day.strftime("%Y-%m-%d")
    month_dir = _timeline_dir() / day_str[:7]
    month_dir.mkdir(parents=True, exist_ok=True)
    out = month_dir / f"{day_str}.parquet"

    try:
        old = pd.read_parquet(out)
        # align columns
        need_old = [c for c in ev.columns if c not in old.columns]
        need_ev  = [c for c in old.columns if c not in ev.columns]
        for c in need_old: old[c] = pd.NA
        for c in need_ev:  ev[c] = pd.NA
        
        # consistent dtypes for numerics
        for c in ["day_step","left","global_x"]:
            if c in old.columns: old[c] = pd.to_numeric(old[c], errors="coerce")
            if c in ev.columns:  ev[c]  = pd.to_numeric(ev[c],  errors="coerce")
        for c in ["y","top","bottom"]:
            if c in old.columns: old[c] = pd.to_numeric(old[c], errors="coerce")
            if c in ev.columns:  ev[c]  = pd.to_numeric(ev[c],  errors="coerce")

        df = pd.concat([old, ev], ignore_index=True, sort=False)
    except FileNotFoundError:
        df = ev

    step_col = "day_step" if "day_step" in df.columns else "step"
    df = df.sort_values([step_col, "ts", "object_id"]).reset_index(drop=True)
    
    # write atomically with retries helper function
    tmp = out.with_name(out.name + ".tmp")
    df.to_parquet(tmp, index=False)
    _replace_with_retries(tmp, out)

    return out

# ───🔹 QUERIES ──────────────────────────────────────────────────────────

def query_current_by_y_range(y_min: float, y_max: float,
                             *, symbol: str | None = None,
                             timeframe: str | None = None,
                             only_active: bool = True) -> pd.DataFrame:
    """
    Return objects whose Y intersects [y_min, y_max], regardless of global_x.
    - Levels: y in range
    - Zones: [min(top,bottom), max(top,bottom)] overlaps range
    """
    cols = ["id","type","left","y","top","bottom","status","symbol","timeframe"]
    df = load_current_objects(columns=cols)

    if symbol:    df = df[df["symbol"] == symbol]
    if timeframe: df = df[df["timeframe"] == timeframe]
    if only_active and "status" in df.columns:
        df = df[df["status"].fillna("active") == "active"]

    is_level = df["y"].notna()
    in_level = is_level & df["y"].between(y_min, y_max)

    is_zone = df["top"].notna() & df["bottom"].notna()
    z_lo = np.minimum(df["top"].astype(float), df["bottom"].astype(float))
    z_hi = np.maximum(df["top"].astype(float), df["bottom"].astype(float))
    in_zone = is_zone & ~( (z_hi < y_min) | (z_lo > y_max) )

    return df[in_level | in_zone].sort_values(["left", "id"]).reset_index(drop=True)

def query_current_by_y_and_x(y_min: float, y_max: float, gx_start: int, gx_end: int,
                             **kwargs) -> pd.DataFrame:
    df = query_current_by_y_range(y_min, y_max, **kwargs)
    return df[(df["left"] >= gx_start) & (df["left"] <= gx_end)].reset_index(drop=True)

def build_asof_snapshot_from_timeline(step: int,
                                      *, symbol: str | None = None,
                                      timeframe: str | None = None) -> pd.DataFrame:
    """
    Reconstruct the last-known state of each object up to 'step' (inclusive)
    from daily-partitioned timeline parquet files.
    """
    parts = sorted(_timeline_dir().rglob("*.parquet"))
    if not parts:
        return pd.DataFrame(columns=["id","type","left","y","top","bottom","status","symbol","timeframe"])

    cols = ["step","ts","action","reason","object_id","type","left","y","top","bottom",
            "status","symbol","timeframe","created_ts","updated_ts","created_step","updated_step"]
    tdfs = []
    for p in parts:
        try:
            tdfs.append(pd.read_parquet(p, columns=[c for c in cols if c in pd.read_parquet(p, nrows=0).columns]))
        except Exception:
            pass
    if not tdfs:
        return pd.DataFrame(columns=["id","type","left","y","top","bottom","status","symbol","timeframe"])

    tl = pd.concat(tdfs, ignore_index=True)
    tl = tl[pd.to_numeric(tl["step"], errors="coerce").fillna(-1).astype(int) <= int(step)]
    if symbol:
        tl = tl[tl["symbol"] == symbol]
    if timeframe:
        tl = tl[tl["timeframe"] == timeframe]

    tl = tl.sort_values(["object_id","step","ts"]).reset_index(drop=True)
    keep = ["object_id","type","left","y","top","bottom","status","symbol","timeframe",
            "created_ts","updated_ts","created_step","updated_step"]
    keep = [c for c in keep if c in tl.columns]
    snap = (tl.groupby("object_id")[keep].last()
              .reset_index()
              .rename(columns={"object_id":"id"}))
    return snap

