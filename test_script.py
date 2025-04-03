import asyncio
from queue import SimpleQueue
from data_acquisition import ws_connect_v2, is_market_open, get_market_hours, read_config, get_current_price, get_dates, get_certain_candle_data
import datetime

import asyncio
import websockets
import json
from datetime import datetime
from data_acquisition import print_log  # Ensure this function is available in your script
import cred  # Replace with actual credentials import

async def test_if_market_is_open():
    print("\nTESTING 'is_market_open()':")
    if await is_market_open():
        print(f"Markets are open today.\n")
    else:
        print(f"Markets are closed today, waiting for tomorrow.\n")
    await asyncio.sleep(0.05)

async def test_market_hours(): 
    print("\nTESTING 'get_market_hours()':")
    today_date = datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        market_hours = await get_market_hours(today_date)
        if market_hours:
            print(f"Market opens at: {market_hours['open_time_et']} ET")
            print(f"Market closes at: {market_hours['close_time_et']} ET")
        else:
            print(f"Failed to fetch market hours.")
    except Exception as e:
       print(f"[ERROR] Failed to fetch market hours: {e}")
    await asyncio.sleep(0.05)

async def test_get_current_price():
    print("\nTESTING 'get_current_price()':")
    print(f"gettings SPY current price: {await get_current_price(read_config('SYMBOL'))}")

async def test_provider_switching(symbol):
    queue = SimpleQueue()
    providers = ["tradier", "polygon"]

    for i in range(5):
        provider = providers[i % 2]
        print(f"\n Testing provider[{i}]: {provider}")
        try:
            await ws_connect_v2(queue, provider, symbol)
            print(f"Successfully connected to {provider} WebSocket.")
        except Exception as e:
            print(f"Error during WebSocket connection for {provider}: {e}")
            print("Switching to the next provider...")
            # Simulate provider switching
            await asyncio.sleep(1)

async def test_polygon_websocket(symbol):
    url = "wss://delayed.polygon.io/stocks"
    auth_payload = json.dumps({
        "action": "auth",
        "params": cred.POLYGON_API_KEY
    })
    subscribe_payload = json.dumps({
        "action": "subscribe",
        "params": f"AM.{symbol}"  # Example: "T.SPY" for SPY trades
    })

    try:
        print_log("[POLYGON] Starting WebSocket connection...")
        async with websockets.connect(url, ssl=True, compression=None) as websocket:
            # Send authentication payload
            await websocket.send(auth_payload)
            print_log(f"[POLYGON] Sent auth payload: {auth_payload}, {datetime.now().isoformat()}")

            # Send subscription payload
            await websocket.send(subscribe_payload)
            print_log(f"[POLYGON] Sent subscribe payload: {subscribe_payload}")

            print_log("[POLYGON] WebSocket connection established. Waiting for messages...")

            # Receive and log messages
            async for message in websocket:
                print_log(f"[POLYGON] Received message: {message}")

    except Exception as e:
        print_log(f"[POLYGON] WebSocket failed: {e}")

async def testing_AfterPre_Market_get_dates():
    candle_interval = 2
    candle_timescale = "minute"
    AM = "AFTERMARKET"
    PM = "PREMARKET"
    # 'AM' Means After Market; 'PM' Means Pre-Market
    AM_start_date, AM_end_date = get_dates(1, False)
    print(f"After Market: {AM_start_date}, {AM_end_date}")
    PD_AM = await get_certain_candle_data(cred.POLYGON_API_KEY, read_config('SYMBOL'), candle_interval, candle_timescale, AM_start_date, AM_end_date, AM, 1)
    
    PM_start_date, PM_end_date = get_dates(1, True)
    print(f"PRE Market: {PM_start_date}, {PM_end_date}")
    CD_PM = await get_certain_candle_data(cred.POLYGON_API_KEY, read_config('SYMBOL'), candle_interval, candle_timescale, PM_start_date, PM_end_date, PM, 1)
    

if __name__ == "__main__":
    #asyncio.run(test_polygon_websocket(read_config('SYMBOL')))
    asyncio.run(testing_AfterPre_Market_get_dates())
    