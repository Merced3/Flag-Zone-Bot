# Objects – Event Log Schema

Objects (zones, levels, markers, flags) are stored as **events**. Last event for an `object_id` is the current state.

### Path pattern

```
storage/objects/<tf>/<YYYY-MM>/part-*.parquet
# after compaction → storage/objects/<tf>/<YYYY-MM>/events.parquet
```

### Columns

- `symbol` (str)
- `timeframe` (str)
- `event_ts` (ISO8601 str) – when the event occurred
- `object_id` (str) – stable UUID/string for the object across its life
- `object_type` (str) – zone|level|marker|flag
- `action` (str) – create|update|close
- `t_start` (ISO str | null) – candle-time where the object becomes active
- `t_end` (ISO str | null) – last candle-time where object is active (null if open)
- `y_min` (float | null)
- `y_max` (float | null)
- `payload` (JSON str) – free-form metadata

### Rules & semantics

- **Event-sourced:** render latest row by `event_ts` per `object_id`.
- **Overlap:** an object is considered visible in a viewport if `COALESCE(t_end, t1) >= t0`.
- Optional **price window filter** using `y_min`/`y_max`.
