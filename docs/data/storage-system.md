# Storage System — Overview & Contracts

## Why

Fast reads, safe incremental writes, and small files during the session. We write **Parquet parts** and compact them later; DuckDB reads via simple globs.

## Key goals

- Append-only during market hours
- Zero-downtime compaction after close
- Time-window queries (and optional price-window for objects)
- Simple contracts (algos/UI don’t care about physical layout)

## What lives where

```bash
Flag-Zone-Bot/
├── storage/
│   ├── data/
│   │   ├── 2m/
│   │   │   ├── 2025-10-22/
│   │   │   │   ├── part-20251022_133001.290000-c24f98a7.parquet
│   │   │   │   └── ... more candle parts ...
│   │   │   ├── 2025-10-21.parquet   # compacted dayfile
│   │   │   └── ...
│   │   ├── 5m/
│   │   │   └── (same pattern as above)
│   │   └── 15m/
│   │       └── (same pattern as above)
│   ├── objects/
│   │   ├── current/
│   │   │   └── objects.parquet      # latest state of all objects
│   │   └── timeline/
│   │       └── YYYY-MM/
│   │           └── YYYY-MM-DD.parquet  # append-only events for that day
│   └── images/ …, emas/ …, flags/ …   # see dedicated docs
```

## Write-path summary

- **Candles:** each finalized candle → single-row Parquet part in `.../<TF>/<YYYY-MM-DD>/`.
- **Objects:** each create/update/close → single-row Parquet **event** in `objects/timeline/YYYY-MM/`.
- **Compaction:** merges candle parts to a **dayfile** `.../<TF>/<YYYY-MM-DD>.parquet`. (Object compaction is optional/by-month later.)

## Read-path summary
- Call `viewport.load_viewport(t0, t1, ...)` to get:
    - a time-bounded candles frame
    - the **last-known state** of each object overlapping the viewport (optionally constrained to a price band using top/bottom)

## Time & TZ

- `t0/t1` bounds may be ISO with **or** without an offset; we normalize them to a local-naive ISO in the market timezone before querying.
- All canonical timestamps persisted in Parquet are ISO strings **with** a TZ offset so DuckDB can compare them lexicographically.
- The UI may present data in the market timezone (e.g., America/Chicago) for consistency.

## Contracts (high level)

- **Candles** are append-only; compaction rewrites files but not values.
- **Objects** are event-sourced; render latest snapshot rows where `status != "removed"`. For price-window queries, overlap via `top/bottom.`

## Retention

- Keep compacted dayfiles; keep parts only for recovery/debugging.

## Failure model

- If a part write fails, you lose one row, not the day.
- Compaction writes to a temp file then renames; if it fails, the original parts remain.

## Related docs

- `docs/data/candles_schema.md`
- `docs/data/objects_schema.md`
- `docs/api/storage-viewport.md`
- `docs/runbooks/end-of-day-compaction.md`
- `docs/adr/0002-parquet-append-and-duckdb-reads.md`
