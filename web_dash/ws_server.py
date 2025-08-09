from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import List
import asyncio

app = FastAPI()

# Store active WebSocket connections
clients: List[WebSocket] = []

"""
This is loaded by `main.py` - so restart of `main.py` would be necessary.
"""

@app.websocket("/ws/chart-updates")
async def chart_updates(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)

    # 👇 Send one “kick” per TF so Dash callbacks render right away
    try:
        for tf in ["2M", "5M", "15M"]:
            await websocket.send_text(f"chart:{tf}")

        while True:
            await asyncio.sleep(60*60)  # keepalive
    except WebSocketDisconnect:
        clients.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in clients:
            clients.remove(websocket)

@app.post("/trigger-chart-update")
async def trigger_chart_update(data: dict):
    # Allow a single timeframe string or a list
    timeframes = data.get("timeframes") or data.get("timeframe") or ["2M"]

    if isinstance(timeframes, str):
        timeframes = [timeframes]  # normalize to list

    print(f"    [/trigger-chart-update] charts:{timeframes} → {len(clients)} clients")
    dead_clients = []

    for client in clients:
        for tf in timeframes:
            try:
                await client.send_text(f"chart:{tf}")
            except Exception:
                dead_clients.append(client)
                break  # stop sending to this client if it's dead

    for client in dead_clients:
        if client in clients:
            clients.remove(client)

    return JSONResponse({
        "status": "broadcasted",
        "timeframes": timeframes,
        "clients": len(clients)
    })
