# tests\storage_unit_tests\test_viewport.py
import importlib
import duckdb

def test_load_viewport_filters_time_and_price(tmp_storage):
    # Import modules after patching paths
    parquet_writer = importlib.import_module("storage.parquet_writer")
    viewport = importlib.import_module("storage.viewport")

    # Seed two candles, two objects
    parquet_writer.append_candle("SPY", "15m", {
        "timestamp":"2025-09-02T09:45:00-04:00","open":450,"high":451,"low":449.5,"close":450.5,"volume":100
    })
    parquet_writer.append_candle("SPY", "15m", {
        "timestamp":"2025-09-02T10:00:00-04:00","open":450.5,"high":452,"low":450,"close":451.5,"volume":120
    })
    parquet_writer.append_object_event(
        symbol="SPY", timeframe="15m",
        object_id="lvl-1", object_type="level", action="create",
        event_ts="2025-09-02T09:50:00-04:00",
        t_start="2025-09-02T09:50:00-04:00", t_end=None,
        y_min=451.0, y_max=451.0, payload={"note":"test"}
    )
    parquet_writer.append_object_event(
        symbol="SPY", timeframe="15m",
        object_id="zone-omit", object_type="zone", action="create",
        event_ts="2025-09-02T08:00:00-04:00",
        t_start="2025-09-02T08:00:00-04:00", t_end="2025-09-02T08:30:00-04:00",
        y_min=440.0, y_max=441.0, payload={}
    )

    # Ask for a viewport that covers 09:45–10:00 and price ~450.8–451.2
    df_c, df_o = viewport.load_viewport(
        symbol="SPY", timeframe="15m",
        t0_iso="2025-09-02T09:45:00-04:00", t1_iso="2025-09-02T10:00:00-04:00",
        y0=450.8, y1=451.2
    )

    # Candles in range = both
    assert len(df_c) == 2
    # Only the level at 451 intersects price band and is active in time window
    assert len(df_o) == 1
    assert df_o["object_id"][0] == "lvl-1"
