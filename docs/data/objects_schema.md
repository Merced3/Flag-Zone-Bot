# Objects — Event Log & Snapshot Schemas

Objects (zones, levels, markers, flags) are **event-sourced** and also materialized into a current-state snapshot for fast UI/strategy reads.

## Path pattern

- **Current snapshot**: `storage/objects/current/objects.parquet`
- **Timeline events**: `storage/objects/timeline/YYYY-MM/YYYY-MM-DD.parquet`

## Columns

### Current snapshot (`objects/current/objects.parquet`)

These columns are enforced on read/write (nullable Pandas dtypes for stability):

- `id` (string) — stable object id
- `type` (string) — e.g., `zone|level|marker|flag`
- `left` (Int64) — x/index positioning hint
- `y` (Float64) — anchor price
- `top` (Float64) — max price bound (for price-window filtering)
- `bottom` (Float64) — min price bound (for price-window filtering)
- `status` (string) — e.g., `active|removed`
- `symbol` (string) — e.g., `SPY`
- `timeframe` (string) — e.g., `2M|5M|15M`
- `created_ts` (Int64) — integer timestamp
- `updated_ts` (Int64) — integer timestamp
- `created_step` (Int64) — engine step index at create
- `updated_step` (Int64) — engine step index at last update

### Timeline events (`objects/timeline/YYYY-MM/YYYY-MM-DD.parquet`)

Each row is a single event (append-only):

- `step` (Int64) — engine step index
- `ts` (Int64 or ISO) — event time (writer may normalize upstream)
- `action` (string) — `create|update|close`
- `reason` (string) — free-form reason/explanation
- `object_id` (string) — id the event refers to (same as `id` in snapshot)
- `type` (string)
- `left, y, top, bottom` (numeric) — geometry/price info
- `status` (string)
- `symbol` (string)
- `timeframe` (string)

## Rules & semantics

- **Event-sourced**: the latest event per `object_id` defines the current state that’s mirrored in the snapshot.
- **Visibility (UI/strategies)**: render objects where `status != "removed"`. If a price window is provided, filter by overlap using `top/bottom` (not `y_min/y_max`).
- **Partitioning** (timeline): events are written under `timeline/YYYY-MM/` with one Parquet file per day (`YYYY-MM-DD.parquet`), append-only.
- **Schema enforcement**: snapshot reads/writes coerce missing columns and cast to the nullable dtypes above to keep DuckDB/Parquet consistent.

## Typical queries

- **Latest state for a viewport**: read the snapshot and filter by `symbol`, `timeframe`, and optional price band `[pmin,pmax]` using `top >= pmin AND bottom <= pmax`.  
- **Audit/history**: read `timeline/2025-10/2025-10-22.parquet` for all events that day; union globs for multi-day windows.
