# tests/storage_unit_tests/test_csv_to_parquet_days.py
from pathlib import Path
import sys
import pandas as pd

# Ensure repo root on path so we can import tools.csv_to_parquet_days
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.csv_to_parquet_days import csv_15m_to_days

def _make_synthetic_csv(csv_path: Path):
    """
    Make a tiny CSV with 3 days of 15m candles.
    Columns: timestamp,open,close,high,low   (no volume)
    """
    rows = [
        # Day 1
        ("2020-05-26 13:30:00", 301.93, 301.63, 302.19, 300.92),
        ("2020-05-26 13:45:00", 301.63, 300.84, 301.71, 300.66),
        ("2020-05-26 14:00:00", 300.83, 300.76, 301.11, 300.37),
        # Day 2
        ("2020-05-27 09:30:00", 303.10, 303.40, 303.90, 302.75),
        ("2020-05-27 09:45:00", 303.40, 303.05, 303.85, 302.90),
        # Day 3
        ("2020-05-28 10:00:00", 304.00, 304.25, 304.60, 303.80),
        ("2020-05-28 10:15:00", 304.25, 304.10, 304.50, 303.95),
    ]
    df = pd.DataFrame(rows, columns=["timestamp", "open", "close", "high", "low"])
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

def test_csv_to_parquet_days_basic(tmp_path: Path):
    # Arrange: synthetic CSV with 3 days
    csv_path = tmp_path / "SPY_15_minute_candles.csv"
    _make_synthetic_csv(csv_path)

    out_dir = tmp_path / "out"

    # Act: convert with global_x and limit to first 2 days
    res = csv_15m_to_days(
        csv_path=csv_path,
        symbol="SPY",
        timeframe="15m",
        write_global=True,
        start_global=0,
        out_dir=out_dir,
        limit_days=2,
    )

    # Assert basic payload
    assert res["ok"] is True
    assert res["days"] == 2

    # Check files written
    tf_dir = out_dir / "15m"
    files = sorted(tf_dir.glob("*.parquet"))
    assert len(files) == 2, "Should have written exactly 2 day files"

    # Read and verify columns + data
    dfs = []
    for f in files:
        df = pd.read_parquet(f)
        # Required columns
        for col in ["symbol", "timeframe", "ts", "open", "high", "low", "close", "volume", "global_x"]:
            assert col in df.columns, f"Missing column: {col}"
        # Volume should be zeros (CSV had no volume)
        assert (df["volume"] == 0).all()
        dfs.append(df[["ts", "global_x"]])

    # Verify global_x contiguity across concatenated days
    full = pd.concat(dfs).sort_values("ts").reset_index(drop=True)
    assert (full["global_x"] == range(len(full))).all(), "global_x must be contiguous from 0..N-1"

def test_csv_to_parquet_days_all_three_days(tmp_path: Path):
    csv_path = tmp_path / "SPY_15_minute_candles.csv"
    _make_synthetic_csv(csv_path)

    out_dir = tmp_path / "out2"

    res = csv_15m_to_days(
        csv_path=csv_path,
        symbol="SPY",
        timeframe="15m",
        write_global=True,
        start_global=0,
        out_dir=out_dir,
        limit_days=0,  # all days
    )

    assert res["ok"] is True
    assert res["days"] == 3

    files = sorted((out_dir / "15m").glob("*.parquet"))
    assert len(files) == 3, "Should have written exactly 3 day files"

    # Quick sanity check on last global index
    # Total rows in synthetic csv = 7 → last global_x should be 6
    assert res["final_global"] == 7, "final_global should be number of rows written (start_global=0)"
