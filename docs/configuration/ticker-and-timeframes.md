# Configuration — Symbol & Timeframes

**Purpose:** Pick the market instrument we operate on and which bar intervals we build and display. One symbol at a time; the app is otherwise ticker-agnostic.

---

## 1) What to set (and where)

Edit `config.json`:

```json
{
  "SYMBOL": "SPY",
  "TIMEFRAMES": ["2M", "5M", "15M"],
  "LIVE_BARS": {"2M": 195, "5M": 78, "15M": 26},
  "LIVE_ANCHOR": "latest"
}
```

* `SYMBOL` — the instrument to trade/visualize (e.g., `SPY`, `QQQ`, `AAPL`).
* `TIMEFRAMES` — which chart intervals to use; upper-case values (e.g., `2M`, `5M`, `15M`).
* `LIVE_BARS` — per-timeframe window size for live charts (bars to show in the Dash live view).
* `LIVE_ANCHOR` — how to anchor the live window: `"now"`, `"latest"`, or `"date:YYYY-MM-DD"`.

---

## 2) What this changes

* **Ingestion & storage**: we only build/write candles for the listed timeframes.
* **Frontend tabs**: charts are generated for each configured timeframe (tabs labeled `2M/5M/15M`).
* **Viewport API**: queries expect the timeframe you configured (case-insensitive, but config is upper-case).
* **Live chart window**: `LIVE_BARS` controls how many bars to show; `LIVE_ANCHOR` controls the right edge of the window.

---

## 3) Rules & tips (no fluff)

* **Upper-case** timeframes in config (`"2M"`, `"5M"`, `"15M"`). The code reads them case-insensitively, but config is upper by convention.
* Use **valid** intervals we support (start with `2M`, `5M`, `15M`).
* Don’t hard-code the symbol or timeframes elsewhere; read them from config.
* If you remove a timeframe from config, its chart/ingest disappears accordingly (old data remains on disk).
* For live charts, set `LIVE_ANCHOR` to `"latest"` to align to the most recent part; use `"now"` if you want a moving wall-clock anchor; `"date:YYYY-MM-DD"` to anchor to a fixed day.

---

## 4) Quick sanity checks

* Do you see one tab per configured timeframe in the web UI?
* Does `viewport.load_viewport(symbol, timeframe, t0, t1, ...)` return rows for that timeframe? (It is case-insensitive, but config uses `"15M"`, `"5M"`, `"2M"`.)
