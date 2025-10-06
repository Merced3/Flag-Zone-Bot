# Architecture Overview

```bash
             ┌────────────────────────────────────────────────────────┐
             │                        Backend                         │
             │                                                        │
Market Data  │  ws_auto_connect (Tradier/Polygon)  →  process_data    │
 (Trades) ───┼── streams → build candles → write logs (per timeframe) │
             │                ↑ latest_price in shared_state          │
             │                └→ update_ema → update_chart (PNG)      │
             └────────────────────────────────────────────────────────┘
                                │               ▲
                                │ HTTP trigger  │ WebSocket push
                                ▼               │
             ┌────────────────────────────────────────────────────────┐
             │                        Services                        │
             │  FastAPI (ws_server):                                  │
             │   - POST /trigger-chart-update → broadcast "chart:TF"  │
             │   - WS /ws/chart-updates → clients subscribe           │
             └────────────────────────────────────────────────────────┘
                                │
                                ▼
             ┌────────────────────────────────────────────────────────┐
             │                         UI (Dash)                      │
             │  Tabs: Zones (15M history), Live 15M/5M/2M charts      │
             │  On WS message "chart:TF" → regenerates that figure    │
             └────────────────────────────────────────────────────────┘
```

### Module breakdown

* **Data acquisition**: websocket client, candle builder, EMA updates
* **Storage**: Parquet parts → daily/monthly compaction; DuckDB for reads
* **Objects**: event‑sourced zones/levels/markers/flags
* **Services**: FastAPI WS broadcaster; Dash client subscriptions
* **Strategies**: run against shared state; produce signals/orders

### Data flow & storage locations

* Candles: `storage/data/<tf>/<YYYY-MM-DD>/*.parquet` (compaction → day file)
* Objects: `storage/objects/<tf>/<YYYY-MM>/*.parquet` (compaction → events.parquet)
* EMA/flags/markers snapshots: `storage/*/*.json` (UI tails, optional)
