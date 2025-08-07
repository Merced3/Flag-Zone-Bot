from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from typing import List
import asyncio

app = FastAPI()

# Store active WebSocket connections
clients: List[WebSocket] = []

@app.websocket("/ws/chart-updates")
async def chart_updates(websocket: WebSocket):
    await websocket.accept()
    clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(60*60)  # keep it alive, do nothing
    except WebSocketDisconnect:
        clients.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in clients:
            clients.remove(websocket)

@app.post("/trigger-chart-update")
async def trigger_chart_update(data: dict):
    timeframe = data.get("timeframe", "2M")
    print(f"[/trigger-chart-update] chart:{timeframe} \u2192 {len(clients)} clients")
    dead_clients = []
    for client in clients:
        try:
            await client.send_text(f"chart:{timeframe}")
        except Exception as e:
            dead_clients.append(client)
    for client in dead_clients:
        clients.remove(client)
    return JSONResponse({"status": "broadcasted", "timeframe": timeframe, "clients": len(clients)})
