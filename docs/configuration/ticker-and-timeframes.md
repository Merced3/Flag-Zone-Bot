# Configuration — Symbol & Timeframes

**StratForge is single‑asset** at runtime, but **ticker‑agnostic**: you can set any instrument your data provider/websocket supports. SPY is just the default.

## Choose a symbol

Edit `config.json`:

```json
{
  "symbol": "SPY",
  "timeframes": ["2m", "5m", "15m"],
  "provider": {
    "name": "polygon",
    "api_key": "YOUR_KEY"
  }
}
```

* **symbol**: Any supported ticker (e.g., `QQQ`, `AAPL`, `ES=F`).
* **provider**: Must support your chosen symbol on the live websocket endpoint.
* **timeframes**: Lowercase on disk (`2m`, `5m`, `15m`) to match storage layout.

## Provider compatibility checklist

* Does the **websocket** stream trades/quotes for the symbol?
* Are there **rate limits** or **entitlements** (e.g., options vs equities) you must enable?
* Are timestamps and sessions aligned with your **market hours** logic?

## Notes

* If you change `symbol`, old SPY Parquet files remain valid; you’ll just write new files under the same tree with a different `symbol` column value.
* Strategies should never hard‑code `SPY`; they read `symbol` from config or shared state.
