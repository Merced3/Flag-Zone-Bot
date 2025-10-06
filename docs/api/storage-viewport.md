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
- Objects: pick latest event per object with `event_ts <= t1`, then filter by time overlap and optional price clause.

### Gotchas

- `timeframe` is lowercase in the on-disk layout (e.g., `15m`).
- Ensure `t0_iso/t1_iso` use the same timezone format as stored rows (ISO strings sort correctly).