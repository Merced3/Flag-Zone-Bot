# tests/storage_unit_tests/test_viewport.py
import importlib
import pandas as pd  # ← add this

def test_load_viewport_filters_time_and_price(tmp_storage):
    parquet_writer = importlib.import_module("storage.parquet_writer")
    viewport = importlib.import_module("storage.viewport")
    from storage.objects.io import upsert_current_objects  # ← write to snapshot

    # Seed two candles
    parquet_writer.append_candle("SPY", "15m", {
        "timestamp":"2025-09-02T09:45:00-04:00","open":450,"high":451,"low":449.5,"close":450.5,"volume":100
    })
    parquet_writer.append_candle("SPY", "15m", {
        "timestamp":"2025-09-02T10:00:00-04:00","open":450.5,"high":452,"low":450,"close":451.5,"volume":120
    })

    # Seed CURRENT snapshot objects directly (1 inside the band, 1 outside)
    upsert_current_objects(pd.DataFrame([
        {"id":"90001","type":"support","left":22815,"y":451.0,
         "top":pd.NA,"bottom":pd.NA,"status":"active","symbol":"SPY","timeframe":"15m"},
        {"id":"90002","type":"support","left":22849,"y":444.0,
         "top":pd.NA,"bottom":pd.NA,"status":"active","symbol":"SPY","timeframe":"15m"},
    ]))

    # Query viewport over 09:45–10:00 with price band 450.8–451.2
    df_c, df_o = viewport.load_viewport(
        symbol="SPY", timeframe="15m",
        t0_iso="2025-09-02T09:45:00-04:00", t1_iso="2025-09-02T10:00:00-04:00",
        y0=450.8, y1=451.2
    )

    # Candles in range = both
    assert len(df_c) == 2

    # We expect at least one object (we injected one in-range)
    assert not df_o.empty

    # Property checks: every returned object overlaps price band and matches symbol/timeframe
    lo, hi = 450.8, 451.2

    def overlaps(row):
        y = row.get("y")
        top = row.get("top")
        bottom = row.get("bottom")
        if pd.notna(y):
            return lo - 1e-9 <= float(y) <= hi + 1e-9
        if pd.isna(top) or pd.isna(bottom):
            return False
        a, b = float(min(top, bottom)), float(max(top, bottom))
        return b >= lo - 1e-9 and a <= hi + 1e-9

    assert all(overlaps(r) for _, r in df_o.iterrows())
    assert set(df_o["symbol"].unique()) <= {"SPY"}
    if "status" in df_o.columns:
        assert (df_o["status"] != "removed").all()
