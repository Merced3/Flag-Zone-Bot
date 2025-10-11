# tests\storage_unit_tests\test_parquet_writer.py
import duckdb
from datetime import datetime, timezone, timedelta
import importlib, pandas as pd
from pathlib import Path

def test_append_candle_creates_daily_parquet(tmp_storage):
    # Import after monkeypatch so parquet_writer sees patched paths
    parquet_writer = importlib.import_module("storage.parquet_writer")

    # Make a candle
    ts = "2025-09-02T09:45:00-04:00"   # any ISO-like string your bot uses
    candle = {"timestamp": ts, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1000}

    parquet_writer.append_candle("SPY", "15m", candle)

    # Verify file exists and row is there
    con = duckdb.connect(":memory:")
    df = con.execute("""
      SELECT COUNT(*) AS c
      FROM read_parquet($p)
    """, {"p": str(tmp_storage.DATA_DIR / "15m" / "2025-09-02" / "*.parquet")}).fetchdf()
    assert df["c"][0] == 1

    # sanity check schema columns
    cols = con.execute("""
      SELECT *
      FROM read_parquet($p)
    """, {"p": str(tmp_storage.DATA_DIR / "15m" / "2025-09-02" / "*.parquet")}).fetchdf().columns
    for col in ["symbol","timeframe","ts","open","high","low","close","volume"]:
        assert col in cols

def test_append_object_event_writes_monthly_partition(tmp_storage):
    parquet_writer = importlib.import_module("storage.parquet_writer")
    # Single event
    parquet_writer.append_object_event(
        symbol="SPY",
        timeframe="15m",
        object_id="zone-123",
        object_type="zone",
        action="create",
        event_ts="2025-09-02T10:00:00-04:00",
        t_start="2025-09-02T09:45:00-04:00",
        t_end=None,
        y_min=450.0,
        y_max=452.5,
        payload={"label":"PDHL"}
    )
    con = duckdb.connect(":memory:")
    df = con.execute("""
      SELECT object_id, object_type, action, y_min, y_max
      FROM read_parquet($glob)
    """, {"glob": str(tmp_storage.OBJECTS_DIR / "15m" / "2025-09" / "*.parquet")}).fetchdf()

    assert len(df) == 1
    assert df["object_id"][0] == "zone-123"
    assert df["action"][0] == "create"

def test_append_candle_normalizes_ts_ms(tmp_storage):
    pw = importlib.import_module("storage.parquet_writer")
    # mixed inputs: ISO and ms
    iso = "2025-09-02T09:45:00-04:00"
    ms  = 1756811100000  # any plausible ms
    pw.append_candle("SPY","15m",{"timestamp": iso,"open":1,"high":2,"low":0.5,"close":1.5,"volume":0})
    pw.append_candle("SPY","15m",{"timestamp": ms, "open":1,"high":2,"low":0.5,"close":1.5,"volume":0})

    day = "2025-09-02"
    files = sorted((tmp_storage.DATA_DIR / "15m" / day).glob("part-*.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in files], ignore_index=True)

    assert "ts" in df.columns and df["ts"].dtype.kind in ("i","u")  # int-like
    assert "ts_iso" in df.columns
    # ISO must end with Z (UTC canonical)
    assert all(str(s).endswith("Z") for s in df["ts_iso"])

def test_compact_day_sorts_on_ts_and_stamps_global_x(tmp_storage):
    pw = importlib.import_module("storage.parquet_writer")
    comp = importlib.import_module("tools.compact_parquet")

    for t in ["2025-09-02T09:45:00-04:00","2025-09-02T10:00:00-04:00","2025-09-02T09:30:00-04:00"]:
        pw.append_candle("SPY","15m",{"timestamp": t,"open":1,"high":2,"low":0.5,"close":1.5,"volume":0})

    res = comp.compact_day("15m","2025-09-02", delete_parts=True)
    assert res["ok"]
    df = pd.read_parquet(tmp_storage.DATA_DIR / "15m" / "2025-09-02.parquet")
    # sorted by ts ascending
    assert list(df["ts"]) == sorted(df["ts"])
    # global_x is contiguous starting from 0 if no prior day exists
    assert df["global_x"].tolist() == list(range(len(df)))
