#data_aquisition.py
import requests
import pandas as pd
import shared_state
import websockets
import asyncio
import cred
import aiohttp
import json
import pytz
import time
from datetime import datetime
from chart_visualization import update_2_min
from error_handler import error_log_and_discord_message
from shared_state import price_lock, indent, print_log
from utils.json_utils import read_config
from utils.data_utils import get_dates
from utils.file_utils import get_current_candle_index
from paths import MARKERS_PATH, AFTERMARKET_EMA_PATH, PREMARKET_EMA_PATH, MERGED_EMA_PATH

RETRY_INTERVAL = 1  # Seconds between reconnection attempts
should_close = False  # Global variable to signal if the WebSocket should close
active_provider = "tradier" # global variable to track active provider

async def ws_auto_connect(queue, provider, symbol):
    """
    Sequential WebSocket connection logic for both Tradier and Polygon providers.
    """
    global should_close
    global active_provider
    print_log(f"Starting ws_connect() for {provider}...")

    # Define the WebSocket URL based on the provider
    url = {
        "tradier": "wss://ws.tradier.com/v1/markets/events",
        "polygon": "wss://delayed.polygon.io/stocks"  # Updated to match your plan
    }.get(provider)

    # Define headers only for Tradier; Polygon does not need extra headers
    headers = {
        "tradier": {
            "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
            "Accept": "application/json"
        }
    }.get(provider)

    # Ensure the configuration is valid
    if not url:
        raise ValueError(f"[{provider.upper()}] Invalid provider configuration. Check URL.")

    should_close = False

    while True:
        try:
            # Ensure session_id is valid
            session_id = get_session_id() if provider == "tradier" else None
            if provider == "tradier" and not session_id:
                print_log("[TRADIER] Unable to get session ID. Retrying...")
                await asyncio.sleep(RETRY_INTERVAL)
                retry_count += 1
                continue  # Retry the loop
            
            # Define payloads for authentication and subscription
            payloads = {
                "tradier": json.dumps({
                    "symbols": [symbol],
                    "sessionid": session_id, # if tradier else none
                    "linebreak": True
                }),
                "polygon_auth": json.dumps({
                    "action": "auth",
                    "params": cred.POLYGON_API_KEY
                }),
                "polygon_subscribe": json.dumps({
                    "action": "subscribe",
                    "params": f"AM.{symbol}"
                })
            }

            # Validate Tradier payload
            if provider == "tradier" and not payloads.get("tradier"):
                print_log("[TRADIER] Payload construction failed. Retrying...")
                await asyncio.sleep(RETRY_INTERVAL)
                continue  # Retry the loop

            # Validate Polygon payloads
            if provider == "polygon" and (not payloads.get("polygon_auth") or not payloads.get("polygon_subscribe")):
                print_log("[POLYGON] Payload construction failed. Retrying...")
                await asyncio.sleep(RETRY_INTERVAL)
                continue  # Retry the loop

            async with websockets.connect(url, ssl=True, compression=None, extra_headers=headers) as websocket:
                if provider == "polygon":
                    await websocket.send(payloads["polygon_auth"])
                    print_log(f"[{provider.upper()}] Sent auth payload: {payloads['polygon_auth']}, {datetime.now().isoformat()}")

                    await asyncio.sleep(1)  # Wait for auth acknowledgment
                    await websocket.send(payloads["polygon_subscribe"])
                    print_log(f"[{provider.upper()}] Sent subscribe payload: {payloads['polygon_subscribe']}, {datetime.now().isoformat()}")

                elif provider == "tradier":
                    await websocket.send(payloads["tradier"])
                    print_log(f"[{provider.upper()}] Sent payload: {payloads['tradier']}, {datetime.now().isoformat()}")

                print_log(f"[{provider.upper()}] WebSocket connection established.")
                print_log("[Hr:Mn:Sc]")

                async for message in websocket:
                    if should_close:
                        print_log(f"[{provider.upper()}] Closing WebSocket connection.")
                        await websocket.close()
                        return
                    await queue.put(message)

        except Exception as e:
            print_log(f"[{provider.upper()}] WebSocket failed: {e}")
            # Switch providers locally
            provider = "polygon" if provider == "tradier" else "tradier"
            print_log(f"[INFO] Switching to {active_provider.capitalize()} WebSocket...")
            await asyncio.sleep(RETRY_INTERVAL)

def get_session_id(retry_attempts=3, backoff_factor=1):
    """Retrieve a session ID from Tradier API."""
    url = "https://api.tradier.com/v1/markets/events/session"
    headers = {
        "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
        "Accept": "application/json"
    }
    for attempt in range(retry_attempts):
        try:
            response = requests.post(url, data={}, headers=headers, timeout=10)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx, 5xx)
            session_data = response.json()
            session_id = session_data.get("stream", {}).get("sessionid")
            if session_id:
                return session_id
            else:
                print_log(f"[TRADIER] Invalid session response: {session_data}")
        except requests.exceptions.RequestException as e:
            print_log(f"[TRADIER] Error fetching session ID: {e}. Attempt {attempt + 1}/{retry_attempts}")
            time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff

    print_log("[TRADIER] Failed to get session ID after retries.")
    return None

async def is_market_open():
    """Check if the stock market is open today using Polygon.io API."""
    url = "https://api.polygon.io/v1/marketstatus/now"
    params = {"apiKey": cred.POLYGON_API_KEY}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    print_log(f"\n[DATA_AQUISITION] 'is_market_open()' DATA: \n{data}\n")
                    market_status = data.get("market", "closed")
                    return market_status in ["open", "extended-hours"]
                else:
                    print_log(f"[ERROR] Polygon API request failed with status {response.status}: {await response.text()}")
                    return False
    except Exception as e:
        print_log(f"[ERROR] Exception in is_market_open: {e}")
        return False

async def get_market_hours(date):
    """Get the market open and close times for the given date using Polygon.io API."""
    url = f"https://api.polygon.io/vX/reference/markets/hours"
    params = {
        "apiKey": cred.POLYGON_API_KEY,
        "market": "stocks",  # Specify the market type
        "date": date  # Date in YYYY-MM-DD format
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                # Log the response MIME type and content for debugging
                print_log(f"[DEBUG] Response MIME type: {response.content_type}")
                raw_data = await response.text()
                print_log(f"[DEBUG] Raw response content: {raw_data}")

                if response.content_type == "application/json":
                    data = await response.json()
                    print_log(f"[DATA_AQUISITION] 'get_market_hours()' DATA: \n{data}\n")

                    if "results" in data:
                        open_time = data["results"].get("open")
                        close_time = data["results"].get("close")

                        if open_time and close_time:
                            return {
                                "open_time_et": open_time,
                                "close_time_et": close_time
                            }
                        else:
                            raise KeyError(f"Missing keys in API response: 'open' or 'close'")
                else:
                    raise ValueError(f"Unexpected response type: {response.content_type}")
    except Exception as e:
        print_log(f"[ERROR] Exception in get_market_hours: {e}")
        return None

async def get_account_balance(is_real_money, bp=None):
    if is_real_money:
        endpoint = f'{cred.TRADIER_BROKERAGE_BASE_URL}accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/balances'
        headers = {'Authorization': f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",'Accept': 'application/json'}
    else:
        endpoint = f'{cred.TRADIER_SANDBOX_BASE_URL}accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/balances'
        headers = {'Authorization': f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}",'Accept': 'application/json'}

    response = requests.get(endpoint, headers=headers)
    try:
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()  # Raises a HTTPError if the HTTP request returned an unsuccessful status code

        try:
            json_response = response.json()
            # Assuming 'balances' is a top-level key in the JSON response:
            balances = json_response.get('balances', {})
            #print(f"balances:\n{balances}\n")

            if is_real_money and bp is None:
                return balances['total_cash']
            elif is_real_money==False:
                return balances['margin']['option_buying_power']
            elif bp is not None and True:
                return balances['cash']['cash_available']
        
        except json.decoder.JSONDecodeError as json_err:
            # Print response text to inspect what was returned
            await error_log_and_discord_message(json_err, "data_acquisition", "get_account_balance", f"JSON decode error occurred: {json_err}\nResponse text that failed to decode: {response.text}")
            return None
    except requests.exceptions.HTTPError as http_err:
        # Log additional details for the HTTP error
        await error_log_and_discord_message(http_err, "data_acquisition", "get_account_balance", f"Status code: {response.status_code}\nResponse headers: {response.headers}")
        return None
    except Exception as err:
        await error_log_and_discord_message(err, "data_acquisition","get_account_balance")
        return None

async def get_current_price() -> float:
    try:
        async with price_lock:
            if shared_state.latest_price is not None:
                return shared_state.latest_price
            else:
                print_log("[WARNING] No price data available yet.")
                return 0.0
    except Exception as e:
        print_log(f"[ERROR] Error fetching current price: {e}")
        return 0.0

async def add_markers(event_type, x=None, y=None, percentage=None):
    
    x_coord = get_current_candle_index() if x is None else x
    y_coord = y if y else await get_current_price()
    print_log(f"    [MARKER] {x_coord}, {y_coord}, {event_type}")

    x_coord += 1

    marker_styles = {
        'buy': {'marker': '^', 'color': 'blue'},
        'trim': {'marker': 'o', 'color': 'red'},
        'sell': {'marker': 'v', 'color': 'red'},
        'sim_trim_lwst': {'marker': 'o', 'color': 'orange'},
        'sim_trim_avg': {'marker': 'o', 'color': 'yellow'},
        'sim_trim_win': {'marker': 'o', 'color': 'green'}
    }
    
    marker = {
        'event_type': event_type,
        'x': x_coord,
        'y': y_coord,
        'style': marker_styles[event_type],
        'percentage': percentage
    }

    # Ensure the file exists
    if not MARKERS_PATH.exists():
        with open(MARKERS_PATH, 'w') as f:
            json.dump([], f)

    # Read existing markers
    try:
        with open(MARKERS_PATH, 'r') as f:
            markers = json.load(f)
        # Ensure markers is a list
        if not isinstance(markers, list):
            markers = []
    except json.decoder.JSONDecodeError:
        markers = []

    markers.append(marker)
    with open(MARKERS_PATH, 'w') as f:
        json.dump(markers, f, indent=4)
    
    update_2_min()

async def get_candle_data_and_merge(candle_interval, candle_timescale, am, pm, indent_lvl):
    PD_AM, CD_PM = None, None
    
    # Load Aftermarket and Premarket Data
    start_date, end_date = get_dates(1, False)
    PD_AM = await get_certain_candle_data(
        cred.POLYGON_API_KEY, 
        read_config('SYMBOL'), 
        candle_interval, candle_timescale, 
        start_date, end_date, 
        AFTERMARKET_EMA_PATH,
        am, indent_lvl+1
    )
    
    start_date, end_date = get_dates(1, True)
    CD_PM = await get_certain_candle_data(
        cred.POLYGON_API_KEY, 
        read_config('SYMBOL'), 
        candle_interval, candle_timescale, 
        start_date, end_date, 
        PREMARKET_EMA_PATH,
        pm, indent_lvl+1
    )
    
    # Combine data if both are present
    if PD_AM is not None and CD_PM is not None:
        merged_df = pd.concat([PD_AM, CD_PM], ignore_index=True)
        
        # Calculate EMAs and save to CSV
        for ema_config in read_config('EMAS'):
            window, color = ema_config
            ema_column_name = f"EMA_{window}"
            merged_df[ema_column_name] = merged_df['close'].ewm(span=window, adjust=False).mean()
        
        merged_df.to_csv(MERGED_EMA_PATH, index=False)
        print_log(f"{indent(indent_lvl)}[GCDAM] Data saved with initial EMA calculation: {MERGED_EMA_PATH}")
        
    else:
        print_log(f"{indent(indent_lvl)}[GCDAM] Aftermarket or premarket data not available. EMA calculation skipped.")

async def get_certain_candle_data(api_key, symbol, interval, timescale, start_date, end_date, output_path, market_type='ALL', indent_lvl=1):
    """
    Fetches interval-timescale candle data for a given symbol on a specific date, filtered by market type.

    Parameters:
    api_key (str): The API key for Polygon.io.
    symbol (str): The symbol for the financial instrument (e.g., 'AAPL', 'SPY').
    interval (int): The interval of the candles in minutes.
    timescale (str): The timescale of the candles (e.g., 'minute').
    start_date (str): The start date for the data in 'YYYY-MM-DD' format.
    end_date (str): The end date for the data in 'YYYY-MM-DD' format.
    market_type (str): The market type for filtering ('ALL', 'PREMARKET', 'MARKET', 'AFTERMARKET').

    Returns:
    None: Saves the data to a CSV file.
    """

    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{interval}/{timescale}/{start_date}/{end_date}?adjusted=true&sort=asc&apiKey={api_key}"

    try:
        response = requests.get(url)
        response.raise_for_status()

        data = response.json()
        if 'results' in data:
            df = pd.DataFrame(data['results'])
            df['timestamp'] = pd.to_datetime(df['t'], unit='ms').dt.tz_localize('UTC').dt.tz_convert(pytz.timezone('America/New_York'))

            # Filter DataFrame based on market type using full datetime boundaries
            market_open_dt = df['timestamp'].dt.normalize() + pd.Timedelta(hours=9, minutes=30)
            market_close_dt = df['timestamp'].dt.normalize() + pd.Timedelta(hours=16)
            
            if market_type == 'PREMARKET':
                df = df[df['timestamp'] <= market_open_dt]
            elif market_type == 'MARKET':
                df = df[(df['timestamp'] >= market_open_dt) & (df['timestamp'] < market_close_dt)] 
            elif market_type == 'AFTERMARKET':
                df = df[df['timestamp'] >= market_close_dt]
            # For 'ALL', no filtering is needed

            start_time = df['timestamp'].iloc[0].strftime('%H:%M:%S')
            end_time = df['timestamp'].iloc[-1].strftime('%H:%M:%S')
            df.rename(columns={'v': 'volume', 'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'timestamp'}, inplace=True)
            df.to_csv(output_path, index=False)
            print_log(f"{indent(indent_lvl)}[GCCD] Data saved: {output_path}; Candles from '{start_time}' to '{end_time}'")
            return df
        else:
            print_log(f"{indent(indent_lvl)}[GCCD] No 'results' key found in the API response.")
    except requests.exceptions.HTTPError as http_err:
        print_log(f"{indent(indent_lvl)}[GCCD] HTTP error occurred: {http_err}")
    except Exception as e:
        print_log(f"{indent(indent_lvl)}[GCCD] An unexpected error occurred: {e}")

    return None
