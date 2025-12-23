# Roadmap

---

## Now

### NEW UI/UX

- **Goal**: Make the UI better than what we had previously.
- **Status**: Completed
- **Description**: Added multi-timeframe Dash tabs (2M/5M/15M + Zones), WS-triggered refreshes, Parquet/DuckDB-powered charts, and PNG exporter separation.

---

## Next

### How To Look

- **Goal**: Let the bot see what the market is interacting with.
- **Status**: Not Started
- **Description**: Log what candles are interacting with on each timeframe and build a consensus view; avoid overfitting while adding more “vision” signals.

---

## Later

### Multi-Buy-In

- **Goal**: Multi-buy into the same order.
- **Status**: Not Started
- **Description**: Implement multi-entry order handling; add sim/tests to validate behavior.

### Adaptive Stop Loss

- **Goal**: Adaptive stop loss using EMAs, zones, and levels.
- **Status**: Not Started
- **Description**: Evaluate best stop anchors (13/48/200 EMA, zones, TPL_lines); experiment and test.

### Candlestick Data Accuracy

- **Goal**: Generate OCHL candlestick data from a 2nd reliable real-time price stream via a sequential setup.
- **Status**: Blocked/Pending
- **Description**: Polygon’s data is unsuitable; need a backup provider to rotate into when the primary fails.

### Refactor Discord Message IDs

- **Goal**: Store and access Discord Message IDs dynamically from a JSON file instead of global variables.
- **Status**: Not Started
- **Description**: Read IDs from JSON on demand to reduce globals/memory and improve modularity.

### Change End Of Day Calculations

- **Goal**: Base EOD calculations entirely on `message_ids.json`.
- **Status**: Not Started
- **Description**: Replace short-term variables with reads from `message_ids.json`; revisit `todays_profit_loss` / `get_profit_loss_orders_list()` flow to remove the mutable variable.

---

## Notes

- Tasks marked **Blocked** require external resolution (e.g., new provider, API access).
- Tasks are arranged by priority: Pending tasks are at the top, completed tasks are at the bottom.
- Update this file regularly as tasks progress or new ones are added.
