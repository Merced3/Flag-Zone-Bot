# Testing — Storage

## Unit tests (suggested)

- `test_parquet_writer.py`: appends create files with correct columns/types (`ts` int64 ms + `ts_iso`).
- `test_compaction.py`:
  - Candles: parts -> compacted dayfile, row counts and min/max `ts/ts_iso` preserved.
  - 15m: `global_x` stamped sequentially across days; monotonic increasing and contiguous.
  - Objects (optional): parts -> monthly events parquet, row counts preserved.
- `test_viewport.py`:
  - Time-window filtering with mixed parts + dayfiles; dedupes by `(symbol,timeframe,ts)`.
  - Price-window filtering for objects (snapshot) via `query_current_by_y_range`; excludes `status="removed"`.
  - Handles optional `global_x` column (15m compaction) without breaking.
- `test_days_window.py`:
  - `days_window(tf, N)` picks the last N trading dates from dayfiles; respects anchor date if provided.
- `test_csv_to_parquet_days.py`: (if used) historical CSV -> day Parquets.

## Fixtures

- Minimal synthetic SPY candles across two days with overlapping parts/dayfiles to exercise dedup.
- 15m compacted dayfile fixture with `global_x` present for continuity tests.
- Overlapping objects snapshot with price bands to exercise inclusion/exclusion in viewport object filtering.
