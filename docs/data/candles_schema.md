# Candles – Schema & Layout

### Path pattern

```bash
storage/data/<tf>/<YYYY-MM-DD>/part-*.parquet
# after compaction → storage/data/<tf>/<YYYY-MM-DD>.parquet
```

### Columns

- `symbol` (str) – e.g., "SPY"
- `timeframe` (str) – e.g., "2M", "5M", "15M"
- `ts` (ISO-8601 **with TZ offset**; lexicographically comparable in DuckDB.) – candle open time (canonical timestamp)
- `open, high, low, close` (float)
- `volume` (float)

### Rules

- Append-only during session.
- Each file is 1 row (part) until compaction.
- Compaction preserves sort by `ts`.

### Notes

- Consumers **must tolerate short gaps** (network hiccups). Strategies should not assume perfect continuity.
- Directories use `2m/5m/15m`; the `timeframe` column may appear as `2M/5M/15M`—consumers should be case-insensitive.”.
