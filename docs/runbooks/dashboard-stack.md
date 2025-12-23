# Runbook — Dashboard Stack

**Goal**: Start the WebSocket broadcaster and the Dash UI, and verify charts refresh on demand.

## Prereqs

- Repo env set up; dependencies installed.
- Ensure `config.json` has the correct `SYMBOL`, `TIMEFRAMES`, `LIVE_BARS`, `LIVE_ANCHOR`.

## Steps

1) **Start WebSocket server (port 8000)**

   ```bash
   uvicorn web_dash.ws_server:app --host 127.0.0.1 --port 8000
   ```

    - On client connect it seeds: `chart:2M`, `chart:5M`, `chart:15M`, `chart:zones`.

2) **Start Dash UI (port 8050)**

   ```bash
   python -m web_dash.dash_app
   ```

    - Open <http://127.0.0.1:8050> and confirm tabs for Zones, 15M, 5M, 2M render.

3) **(Optional) Regenerate PNG + broadcast**

   ```bash
   python - <<'PY'
   from web_dash.chart_updater import update_chart
   update_chart("5M", chart_type="live", notify=True)
   PY
   ```

    - `notify=True` POSTs `/trigger-chart-update` after saving the PNG.

## Verification

- After both services are up, the browser should render all four tabs once (seed messages).
- Trigger a refresh manually:

  ```bash
  curl -X POST http://127.0.0.1:8000/trigger-chart-update \
    -H "Content-Type: application/json" \
    -d '{"timeframes":["2M","zones"]}'
  ```

  - The 2M and Zones tabs should re-render in the browser without a page reload.

## Notes

- Ports: WS server on 8000, Dash on 8050.
- Timeframes are upper-case (`2M/5M/15M`); there is a `zones` channel for the history tab.
- If Dash isn’t running, broadcasts are harmless; reconnecting will still get the seed messages.
