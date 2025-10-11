# Testing – Storage

## Unit tests (suggested)

- `test_parquet_writer.py`: appends create files with correct columns/types.
- `test_compaction.py`: parts → compacted day/month, row counts and min/max `ts` preserved.
- `test_viewport.py`: time-window filtering; last-event-per-object selection; price-window filtering.
- `test_csv_to_parquet_days.py`: (if used) historical CSV → day Parquets.

## Fixtures

- Minimal synthetic SPY candles across two days and overlapping objects with open-ended `t_end`.
