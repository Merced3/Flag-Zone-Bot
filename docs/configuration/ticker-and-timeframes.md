# Configuration — Symbol & Timeframes

**Purpose:** Pick the market instrument we operate on and which bar intervals we build and display. One symbol at a time; the app is otherwise ticker-agnostic. :contentReference[oaicite:0]{index=0}

---

## 1) What to set (and where)

Edit `config.json`:

```json
{
  "symbol": "SPY",
  "timeframes": ["2m", "5m", "15m"]
}

```

* `symbol` — the instrument to trade/visualize (e.g., `SPY`, `QQQ`, `AAPL`).
* `timeframes` — which chart intervals to use; lowercase values (e.g., `2m`, `5m`, `15m`).

---

## 2) What this changes

* **Ingestion & storage**: we only build/write candles for the listed timeframes.
* **Frontend tabs**: charts are generated for each configured timeframe.
* **Viewport API**: queries expect the timeframe you configured (lowercase).

---

## 3) Rules & tips (no fluff)

* **Lowercase** timeframes in config (`"2m"`, `"5m"`, `"15m"`). The code and docs assume this.
* Use **valid** intervals we actually support (start with `2m`, `5m`, `15m`).
* Don’t hard-code the symbol elsewhere; read it from config.
* If you remove a timeframe from config, its chart/ingest disappears accordingly (old data remains on disk).

---

## 4) Quick sanity checks

* Do you see one tab per configured timeframe in the web UI?
* Does `viewport.load_viewport(symbol, timeframe, t0, t1, …)` return rows for that timeframe? (It expects lowercase like `"15m"`, `"5m"`, `"2m"`.)
