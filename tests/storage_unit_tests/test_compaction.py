# tests/storage_unit_tests/test_compaction.py
import importlib, json
from pathlib import Path
import pandas as pd

def test_compact_day_deletes_parts_and_keeps_dayfile(tmp_storage, monkeypatch):
    # Use temp paths from fixture; import after monkeypatch
    parquet_writer = importlib.import_module("storage.parquet_writer")
    compactor = importlib.import_module("tools.compact_parquet")

    # Seed 3 candles (parts) for a day
    for ts in ["2025-09-02T09:45:00-04:00","2025-09-02T10:00:00-04:00","2025-09-02T10:15:00-04:00"]:
        parquet_writer.append_candle("SPY","15m", {
            "timestamp": ts, "open":1, "high":2, "low":0.5, "close":1.5, "volume":100
        })

    tf = "15m"; day = "2025-09-02"
    parts_dir = tmp_storage.DATA_DIR / tf / day
    day_file = tmp_storage.DATA_DIR / tf / f"{day}.parquet"

    assert parts_dir.exists()
    assert len(list(parts_dir.glob("part-*.parquet"))) == 3

    # Run compaction
    res = compactor.compact_day(tf, day, delete_parts=True)
    assert res["ok"]
    assert day_file.exists()
    # Parts folder should be gone or empty
    assert not parts_dir.exists() or len(list(parts_dir.glob("part-*.parquet"))) == 0

    # Verify row count in the compacted file
    df = pd.read_parquet(day_file)
    assert len(df) == 3
    # ensure ordering by ts
    assert list(df["ts"]) == sorted(df["ts"])

def test_compact_month_objects_deletes_parts(tmp_storage, monkeypatch):
    parquet_writer = importlib.import_module("storage.parquet_writer")
    compactor = importlib.import_module("tools.compact_parquet")

    # Seed 2 events in same month
    parquet_writer.append_object_event(
        symbol="SPY", timeframe="15m",
        object_id="z1", object_type="zone", action="create",
        event_ts="2025-09-02T10:00:00-04:00", t_start="2025-09-02T10:00:00-04:00",
        y_min=450, y_max=452, payload={"p":1}
    )
    parquet_writer.append_object_event(
        symbol="SPY", timeframe="15m",
        object_id="z1", object_type="zone", action="close",
        event_ts="2025-09-03T10:00:00-04:00", t_end="2025-09-03T10:00:00-04:00",
        y_min=450, y_max=452, payload={"p":2}
    )

    tf = "15m"; ym = "2025-09"
    month_dir = tmp_storage.OBJECTS_DIR / tf / ym
    assert len(list(month_dir.glob("part-*.parquet"))) == 2

    res = compactor.compact_month_objects(tf, ym, delete_parts=True)
    assert res["ok"]
    events_file = month_dir / "events.parquet"
    assert events_file.exists()
    assert len(list(month_dir.glob("part-*.parquet"))) == 0

    df = pd.read_parquet(events_file)
    assert len(df) == 2
