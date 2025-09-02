# tests\storage_unit_tests\test_parquet_writer.py
import duckdb
import importlib
from datetime import datetime, timezone, timedelta

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
