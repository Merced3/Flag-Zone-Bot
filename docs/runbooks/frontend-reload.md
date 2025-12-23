# Frontend Reload While Backend Stays Running

How to refresh the dashboard stack (uvicorn + Dash) without stopping the main `python main.py` data feed, and why each step matters.

## Why this exists

- `main.py` auto-spawns uvicorn (`web_dash.ws_server`) on port 8000. That process loads the Python files once and keeps running.
- When you edit frontend code (e.g., `web_dash/charts/live_chart.py`), uvicorn won’t see the changes until it’s restarted.
- If uvicorn keeps an old copy, `/refresh-chart` can fail (e.g., `AttributeError: 'list' object has no attribute 'empty'`), and PNG exports won’t update.
- We want to restart uvicorn without interrupting the live data feed in `main.py`.

## Quick command sequence (PowerShell, venv active)

1) **Find what’s on port 8000**

   ```powershell
   netstat -ano | findstr :8000
   ```

   Note the PID in the last column (example: `17360`).

2) **Stop that uvicorn**

   ```powershell
   taskkill /PID <PID_FROM_STEP1> /F
   ```

   Optional check: `netstat -ano | findstr :8000` should now show no LISTENING entry (TIME_WAIT is fine).

3) **Start a fresh uvicorn with reload**

   ```powershell
   uvicorn web_dash.ws_server:app --host 127.0.0.1 --port 8000 --reload
   ```

   - `--reload` hot-reloads on file changes during frontend dev.
   - Keep this running in its own terminal.

4) *(Optional)* **Start Dash UI** if you want the browser view:

   ```powershell
   python -m web_dash.dash_app
   ```

The main `python main.py` can stay running the whole time. Only the uvicorn process on port 8000 is replaced.

## What this fixes

- Clears stale code in uvicorn so `/refresh-chart` and PNG exports use the latest files.
- Removes errors like `list has no attribute empty` that come from old code still in memory.
- Restores PNG saving for EOD Discord uploads (`storage/images/SPY_<TF>_chart.png`).

## Signs it worked

- uvicorn startup shows: `Application startup complete.` and no “only one usage of each socket” error.
- Backend logs show `/refresh-chart` without exceptions.
- PNGs in `storage/images/` update at refresh times.

## If you hit the “address already in use” error

- It means an old uvicorn is still bound to 8000. Repeat steps 1–3 to kill it and start fresh.

## Optional tweaks

- If you don’t want `main.py` to auto-spawn uvicorn during frontend work, temporarily comment out the `subprocess.Popen(["uvicorn", "web_dash.ws_server:app"])` line in `main.py` and start uvicorn manually (step 3). Remember to restore it when done.
