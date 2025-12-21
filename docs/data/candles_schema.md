# Candles — Schema & Layout

## Path pattern

```bash
storage/data/<tf>/<YYYY-MM-DD>/part-*.parquet
# after compaction -> storage/data/<tf>/<YYYY-MM-DD>.parquet
```

## Columns

- `symbol` (str) — e.g., "SPY"
- `timeframe` (str) — e.g., "2M", "5M", "15M"
- `ts` (int64 ms, UTC) — canonical candle open time
- `ts_iso` (ISO-8601 with offset, UTC) — human/duckdb-friendly; lexically comparable
- `open, high, low, close` (float)
- `volume` (float)
- `global_x` (int, optional) — only on compacted 15m dayfiles; continuous index for zones/levels alignment

## Rules

- Append-only during session.
- Each part file holds 1 row under its dated folder.
- Compaction merges parts into the dayfile `storage/data/<tf>/<YYYY-MM-DD>.parquet`.
- 15m compaction stamps `global_x` sequentially across days.
- Compaction preserves sort by `ts` (or `ts_iso` fallback).

### Notes

- Consumers **must tolerate short gaps** (network hiccups). Strategies should not assume perfect continuity.
- Directories use lowercase (`2m/5m/15m`); the `timeframe` column may appear as `2M/5M/15M` — treat it case-insensitively.
- DuckDB reads should use `union_by_name=1` and `hive_partitioning=1` with `read_parquet` to handle schema drift and date-folder layout.
