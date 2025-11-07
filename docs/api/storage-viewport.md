# API - `viewport.load_viewport()`

**Purpose:** return a candle slice and the current object states for a time/price window.

```bash
load_viewport(
    symbol: str,
    timeframe: str, # "15m", "5m", "2m"
    t0_iso: str, # inclusive lower bound
    t1_iso: str, # inclusive/semantic upper bound
    y0: float | None = None, # optional price min
    y1: float | None = None # optional price max
) -> (pd.DataFrame, pd.DataFrame)
```

### Behavior

- **Candles:** `SELECT … FROM read_parquet(glob) WHERE symbol=? AND timeframe=? AND ts BETWEEN ? AND ? ORDER BY ts`.

- **Objects (snapshot-based):**
  Read `storage/objects/current/objects.parquet` and keep rows where:
  - `symbol = ?` and `timeframe = ?`
  - `status != "removed"`
  - if a price band is given: `top >= y0` and `bottom <= y1`


### Gotchas

- `t0_iso` / `t1_iso` may be given with or without a timezone offset; we normalize them before querying so ISO strings compare correctly.
- The on-disk folders are lowercase (`2m/5m/15m`) and the `timeframe` column may be cased differently; treat it case-insensitively.
