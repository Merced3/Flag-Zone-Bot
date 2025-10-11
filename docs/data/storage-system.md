# Storage System – Overview & Contracts

## Why

We redesigned storage so strategies and UIs can read fast, write safely, and scale without giant CSVs. Candles and “objects” (zones/levels/markers/flags) are written as small Parquet parts and compacted later. Reads use DuckDB over file globs for speed and SQL ergonomics.

## Key goals

- **Append-only writes** during market hours (safe, atomic-ish).
- **Zero downtime compaction** after close.
- **Query by time-window** (and optionally by price range for objects).
- **Simple contracts** so algos and UIs don’t care how data is physically laid out.

## What lives where

```bash
Flag-Zone-Bot/
├── Other stuff...
├── storage/
│   ├── csv/ 
│   │   ├── order_log.csv
│   ├── data/ 
│   │   ├── 2m/
│   │   │   └── 2025-09-02.parquet # Alot of Parquet Files
│   │   ├── 5m/
│   │   │   └── 2025-09-02.parquet # Alot of Parquet Files
│   │   └── 15m/
│   │       └── 2025-09-02.parquet # Alot of Parquet Files
│   ├── emas/ # Exponential Moving Average indicator, for differnt TimeFrames
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   ├── 15M.json
│   │   └── ema_state.json
│   ├── flags/ # BEAR/BULL Flag indicator, for differnt TimeFrames
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   └── 15M.json
│   ├── images/ # this is where everything chart/image-wise is saved
│   │   ├── SPY_2M_chart.png
│   │   ├── SPY_5M_chart.png
│   │   ├── SPY_15M_chart.png
│   │   └── SPY_15M-zone_chart.png
│   ├── markers/ # UI chart will read this and show on frontend
│   │   ├── 2M.json
│   │   ├── 5M.json
│   │   └── 15M.json
│   ├── objects/ 
│   ├── duck.py
│   ├── message_ids.json # Keeps track of messages being sent to discord
│   ├── parquet_writer.py
│   ├── viewport.py
│   ├── week_ecom_calendar.json # Somewhat of a "Indicator"
│   └── week_performances.json 
├── Other Not important stuff...
```

## Write-path summary

- **Candles:** each finalized candle → single-row Parquet part (atomic file create).
- **Objects:** each object event (create/update/close) → single-row Parquet part.
- **Compaction:** merges parts into a day/month file; optional deletion of parts.

## Read-path summary
- Use `viewport.load_viewport()` to materialize:
    - a time-bounded candles frame
    - the **last-known state** of each object overlapping the viewport (and optional price window)

## Time & TZ

- All canonical timestamps in Parquet are stored as **ISO strings** with TZ offset when written, and compared lexicographically in DuckDB (consistent because ISO8601 sorts correctly).
- UI may convert to America/New_York for plotting.

## Contracts (high level)

- **Candles** are **append-only** and immutable post-write (compaction rewrites but values don’t change).
- **Objects** are event-sourced; last event wins. Consumers (UI/strategy) should render the latest state where `t_end` is null or overlaps the query window.

## Retention

- Keep compacted day files indefinitely; keep parts only for recovery/debug (optional).

## Failure model

- If a part write fails, you lose a single row—not the whole day.
- Compaction writes to a temp file and renames it; if that fails you still have the parts.

## Related docs

- `docs/data/candles_schema.md`
- `docs/data/objects_schema.md`
- `docs/api/storage-viewport.md`
- `docs/runbooks/end-of-day-compaction.md`
- `docs/adr/0002-parquet-append-and-duckdb-reads.md`ß
