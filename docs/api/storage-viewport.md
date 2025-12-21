# API - `viewport.load_viewport()`

**Purpose:** return a candle slice and the current object states for a time/price window.

```bash
load_viewport(
    symbol: str,
    timeframe: str,          # "15m", "5m", "2m"
    t0_iso: str,             # inclusive lower bound
    t1_iso: str,             # inclusive/semantic upper bound
    include_parts: bool = True,  # read intraday part-*.parquet
    include_days: bool = True,   # read compacted dayfiles
    y0: float | None = None,     # optional price min
    y1: float | None = None      # optional price max
) -> (pd.DataFrame, pd.DataFrame)
```

## Behavior

- **Candles:** reads Parquet from the tf folder using the flags (include_parts, include_days). Drops duplicate bars when parts + dayfiles overlap (by symbol,timeframe,ts). If compacted 15m files have a `global_x` column, it is returned (else NULL). Results are ordered by ts.

Trialing SQL Snippet Example: `SELECT … FROM read_parquet(glob) WHERE symbol=? AND timeframe=? AND ts BETWEEN ? AND ? ORDER BY ts`.

- **Objects (snapshot-based):**
  Reads `storage/objects/current/objects.parquet` via `query_current_by_y_range`:
  - Always pulls the `15m` snapshot, filtered by symbol/timeframe and the price band.
  - Price band: if `y0/y1` are not provided, it derives `min/max` from the returned candles (with a small pad).
  - Excludes rows where `status == "removed"`; de-dupes by `id` if present.

## Helpers used by charts

- `days_window(tf, days)`: picks the last N trading dates from dayfiles (no parts) and returns t0/t1; used by zones_chart.
- `get_timeframe_bounds(tf, include_days, include_parts)`: finds min/max ts across the selected files; used to anchor live charts to the latest part when needed.

## Gotchas

- `t0_iso` / `t1_iso` may include or omit timezone offsets; they are normalized to local market time before filtering.
- On-disk folders are lowercase (`2m/5m/15m`); `timeframe` column casing may vary — treat it case-insensitively.
- include_parts/include_days let you target intraday parts vs compacted dayfiles; mixing them is fine (duplicates are dropped by ts).
