# storage/parquet_writer.py
from __future__ import annotations
import json, uuid
from typing import Optional
import pandas as pd
import paths                      # <- central paths
#from storage.duck import conn     # <- single DuckDB connection
from utils.time_utils import to_ms, to_iso 

def _safe_file_name_from_iso(ts_iso: str) -> str:
    # Create a stable-ish unique suffix (avoid ':' for Windows paths)
    return ts_iso.replace(":", "").replace("-", "").replace("T", "_").replace("+", "").replace("Z","")

def _day_from_ms(ts_ms: int) -> str:
    return pd.to_datetime(ts_ms, unit="ms").strftime("%Y-%m-%d")

def append_candle(symbol: str, timeframe: str, candle: dict):
    """
    Append one finalized candle by writing a 1-row parquet file into:
      storage/data/<tf>/<YYYY-MM-DD>/part-*.parquet
    """

    # Normalize whatever we get to int64 ms + a readable ISO
    ts_ms  = to_ms(candle["timestamp"])          # <— normalized int64 ms
    ts_iso = to_iso(ts_ms)                        # <— stable, UTC ISO for humans/tools

    day = _day_from_ms(ts_ms)
    day_dir = paths.DATA_DIR / timeframe.lower() / day
    day_dir.mkdir(parents=True, exist_ok=True)

    # 1-row dataframe
    df = pd.DataFrame([{
        "symbol": symbol,
        "timeframe": timeframe,
        "ts":        ts_ms,                       # <— canonical time
        "ts_iso":    ts_iso,                      # <— convenience for humans/tools
        "open": float(candle.get("open", 0)),
        "high": float(candle.get("high", 0)),
        "low": float(candle.get("low", 0)),
        "close": float(candle.get("close", 0)),
        "volume": float(candle.get("volume", 0)),
    }])

    # unique file per row
    out = day_dir / f"part-{_safe_file_name_from_iso(ts_iso)}-{uuid.uuid4().hex[:8]}.parquet"
    df.to_parquet(out, index=False)

def append_object_event(
        *,
        symbol: str,
        timeframe: str,                 # e.g., "15m"
        object_id: str,
        object_type: str,               # 'zone'|'level'|'marker'|'flag'
        action: str,                    # 'create'|'update'|'close'
        event_ts: str,                  # ISO timestamp for the event
        t_start: Optional[str] = None,
        t_end: Optional[str] = None,
        y_min: Optional[float] = None,
        y_max: Optional[float] = None,
        payload: Optional[dict] = None,
    ) -> None:
    """
    Append one object event by writing a 1-row parquet file into:
      storage/objects/<tf>/YYYY-MM/part-*.parquet
    """
    month = event_ts[:7]  # "YYYY-MM"
    month_dir = paths.OBJECTS_DIR / timeframe.lower() / month
    month_dir.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame([{
        "symbol": symbol,
        "timeframe": timeframe,
        "event_ts": event_ts,
        "object_id": object_id,
        "object_type": object_type,
        "action": action,
        "t_start": t_start,
        "t_end": t_end,
        "y_min": float(y_min) if y_min is not None else None,
        "y_max": float(y_max) if y_max is not None else None,
        "payload": json.dumps(payload or {}, ensure_ascii=False),
    }])

    out = month_dir / f"part-{_safe_file_name_from_iso(event_ts)}-{uuid.uuid4().hex[:8]}.parquet"
    df.to_parquet(out, index=False)
