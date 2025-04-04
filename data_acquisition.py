#data_aquisition.py
import requests
import pandas as pd
import pandas_market_calendars as mcal
import numpy as np
from chart_visualization import update_2_min
from error_handler import error_log_and_discord_message
from shared_state import price_lock, indent, print_log, safe_read_json
import shared_state
import websockets
from websockets.exceptions import InvalidStatusCode
from requests.exceptions import ConnectionError, Timeout
from urllib3.exceptions import NewConnectionError, MaxRetryError
import asyncio
import cred
import aiohttp
import json
import pytz
import time
import glob
from datetime import datetime, timedelta
import os
import math
import re
from pathlib import Path
import csv

RETRY_INTERVAL = 1  # Seconds between reconnection attempts
should_close = False  # Global variable to signal if the WebSocket should close
active_provider = "tradier" # global variable to track active provider

config_path = Path(__file__).resolve().parent / 'config.json'
LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def read_config(key=None):
    """Reads the configuration file and optionally returns a specific key."""
    with config_path.open("r") as f:
        config = json.load(f)
    if key is None:
        return config  # Return the whole config if no key is provided
    return config.get(key)  # Return the specific key's value or None if key doesn't exist

MESSAGE_IDS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'message_ids.json')

def load_message_ids():
    if os.path.exists(MESSAGE_IDS_FILE_PATH):
        with open(MESSAGE_IDS_FILE_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    else:
        return {}

async def ws_connect_v1(queue, symbol):
    global should_close
    print_log("Starting ws_connect()...")
    should_close = False

    while True:
        try:
            session_id = get_session_id()
            if session_id is None:
                print_log("Failed to get a new session ID. Retrying in 1 second...")
                await asyncio.sleep(1)
                continue

            url = "wss://ws.tradier.com/v1/markets/events"
            async with websockets.connect(url, ssl=True, compression=None) as websocket:
                payload = json.dumps({
                    "symbols": [symbol],
                    "sessionid": session_id,
                    "linebreak": True
                })
                await websocket.send(payload)
                print_log(f">>> {payload}, {datetime.now().isoformat()}")
                print_log("[Hr:Mn:Sc]")

                async for message in websocket:
                    if should_close:
                        print_log("Closing WebSocket connection.")
                        await websocket.close()
                        return

                    await queue.put(message)

        except asyncio.TimeoutError:
            print_log("[SERVER-SIDE TIMEOUT] The WebSocket server did not respond in time. Retrying...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except InvalidStatusCode as e:
            if e.status_code == 502:
                print_log("Encountered a server-side error (HTTP 502). There's nothing we can do about it at this moment.")
            else:
                print_log(f"Encountered a server-side error (HTTP {e.status_code}).")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except websockets.ConnectionClosed:
            print_log("WebSocket connection closed. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except (ConnectionError, NewConnectionError, MaxRetryError, Timeout) as e:
            print_log(f"[INTERNET CONNECTION] Failed to connect at {datetime.now().isoformat()}, retrying...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying
        
        except Exception as e:
            await error_log_and_discord_message(e, "data_acquisition", "ws_connect", "An error occurred. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

async def ws_connect_v2(queue, provider, symbol):
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

def save_to_csv(df, filename):
    df.to_csv(filename, index=False)

async def get_candle_data(api_key, symbol, interval, timescale, start_date, end_date):
    """
    Fetches interval-timescale candle data for a given symbol between start_date and end_date.

    Parameters:
    api_key (str): The API key for Polygon.io.
    symbol (str): The symbol for the financial instrument (e.g., 'AAPL', 'SPY').
    start_date (str): The start date for the data in 'YYYY-MM-DD' format.
    end_date (str): The end date for the data in 'YYYY-MM-DD' format.

    Returns:
    DataFrame: A DataFrame with the 15-minute candle data.
    """

    # Adjust end date to include it in the business day count
    adjusted_end_date = pd.Timestamp(end_date) + pd.Timedelta(days=1)

    # Calculating number of trading days
    start = pd.Timestamp(start_date)
    business_days = np.busday_count(start.date(), adjusted_end_date.date())

    # Calculating limit based on trading days
    intervals_per_day = 26  # Assuming 6.5 trading hours per day
    candle_limit = intervals_per_day * business_days
    limit = 50000  # Temporary static limit
    print_log(f"Candle Limit, Limit and Business Days:\n{candle_limit}, {limit}, {business_days}\n")

    asc_desc = "asc"
    print_log(f"asc_desc = {asc_desc}")

    df = pd.DataFrame()  # Initialize an empty DataFrame to handle cases where data might not be fetched
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{interval}/{timescale}/{start_date}/{end_date}?adjusted=true&sort={asc_desc}&limit={limit}&apiKey={api_key}"
        response = requests.get(url)
        response.raise_for_status()  # This will raise an HTTPError if the HTTP request returned an unsuccessful status code
        
        data = response.json()
        print_log(f"({interval}m) url: {url}")
    
        print_log(f"response: {response}\n") # i want to print conditions somehow

        # Check if 'results' key is in the data
        if 'results' in data:
            #print("Results is true!!!")
            df = pd.DataFrame(data['results'])
            df['t'] = pd.to_datetime(df['t'], unit='ms')
            df.rename(columns={'v': 'volume', 'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'timestamp'}, inplace=True)
            
            if interval == 15:
                corrected_df = await filter_data(df, True, '13:30:00', '19:45:00')
            elif interval==2:
                corrected_df = await filter_data(df, False)
            save_to_csv(corrected_df, f"{symbol}_{interval}_{timescale}_candles.csv")
            return corrected_df
        else:
            print_log("No 'results' key found in the API response.")
            return pd.DataFrame()  # Return an empty DataFrame if no results

    except requests.exceptions.HTTPError as http_err:
        print_log("HTTP error occurred:", http_err)
    except KeyError as key_err:
        print_log("Key error in data conversion:", key_err)
    except Exception as e:
        print_log("An unexpected error occurred:", e)

    return pd.DataFrame()

async def filter_data(df, exclude_today=True, day_time_start = '14:30:00', day_time_end = '21:00:00'):
    """
    Filter the data with the following criteria:
    1) Within the week (Monday to Friday)
    2) During market open hours (not pre-market or after-market)
    3) Optionally exclude current day data
    4) Indexed in order

    Parameters:
    df (DataFrame): The DataFrame to filter.
    exclude_today (bool, optional): Whether to exclude today's data. Defaults to True.
    """
    print_log(f'day_time_start: {day_time_start}; day_time_end: {day_time_end}')
    # Keep data for Monday (0) to Friday (4)
    weekday_df = df[df['timestamp'].dt.dayofweek < 5]

    if exclude_today:
        # Exclude current day data
        today = pd.Timestamp(datetime.now().date())
        weekday_df = weekday_df[weekday_df['timestamp'].dt.date < today.date()]

    # Keep data within market hours
    market_open_time = pd.Timestamp(day_time_start).time()#09:30:00
    market_close_time = pd.Timestamp(day_time_end).time()#16:00:00
    market_hours_df = weekday_df[(weekday_df['timestamp'].dt.time >= market_open_time) & (weekday_df['timestamp'].dt.time <= market_close_time)]
    #market_hours_df = df[(df['timestamp'].dt.time >= market_open_time) & (df['timestamp'].dt.time <= market_close_time)]
    # Reset the index to reorder the DataFrame
    corrected_df = market_hours_df.reset_index(drop=True)
    
    return corrected_df

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
    
def get_current_candle_index(log_file_path = Path(__file__).resolve().parent / 'logs/SPY_2M.log'):
    with open(log_file_path, 'r') as file:
        lines = file.readlines()
    if not lines:
        return None  # Return None if the log file is empty
    # The index of the last candle is the length of the lines list minus 1
    return len(lines) - 1

def candle_zone_handler(candle, type_of_candle, boxes, first_candle = False):
    if boxes:
        for box_name, (x_pos, high_low_of_day, buffer) in boxes.items(): 
            # Determine zone type
            zone_type = "support" if "support" in box_name else "resistance" if "resistance" in box_name else "PDHL"
            PDH_or_PDL = high_low_of_day  # PDH for resistance, PDL for support
            box_top = PDH_or_PDL if zone_type in ["resistance", "PDHL"] else buffer  # PDH or Buffer as top for resistance/PDHL
            box_bottom = buffer if zone_type in ["resistance", "PDHL"] else PDH_or_PDL  # Buffer as bottom for resistance/PDHL
            check_is_in_another_zone = True
            action = None # Initialize action to None or any default value
            # Check if the candle shoots through the zone
            if candle['open'] < box_bottom:
                if candle['close'] > box_top:
                    # Candle shoots up through the zone
                    action = "[START 1]" # CALLS
                    candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
                    check_is_in_another_zone = True
                elif box_bottom < candle['close'] < box_top:
                    # Went up, closed Inside of box
                    action = '[END 2]'
            elif candle['open'] > box_top:
                if candle['close'] < box_bottom:
                    # Candle shoots down through the zone
                    action = "[START 3]" # PUTS
                    candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                    check_is_in_another_zone = True
                elif box_top > candle['close'] > box_bottom:
                    #went down, closed Inside of box
                    action = "[END 4]"
            elif candle['close'] > box_top and candle['open'] <= box_top:
                # Candle closes above the zone, potentially starting an upward trend
                action = "[START 5]" # CALLS
                candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
            elif candle['close'] < box_bottom and candle['open'] >= box_bottom:
                # Candle closes below the zone, potentially starting a downward trend
                action = "[START 6]" # PUTS
                candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                            
            
            # I only want this to run on the first candle
            if 'PDHL_1' in box_name and first_candle: 
                # Above zone
                if candle['open'] > box_top and candle['close'] > box_top:
                    # whole candle is above zone
                    candle_type = "PDH"
                    action = "[START 8]"
                elif candle['open'] < box_top and candle['close'] > box_top:
                    # candle is coming out above zone
                    candle_type = "PDH"
                    action = "[START 9]"
                
                # Below zone
                if candle['open'] < box_bottom and candle['close'] < box_bottom:
                    # whole candle is below zone
                    candle_type = "PDL"
                    action = "[START 10]"
                if candle['open'] > box_bottom and candle['close'] < box_bottom:
                    # candle is coming out below zone
                    candle_type = "PDL"
                    action = "[START 11]"
                check_is_in_another_zone = True

            if check_is_in_another_zone:
                # Additional checks to refine action based on closing inside any other zone
                for other_box_name, (_, other_high_low_of_day, other_buffer) in boxes.items():
                    if other_box_name != box_name:  # Ensure we're not checking the same zone
                        other_box_top = other_high_low_of_day if "resistance" in other_box_name or "PDHL" in other_box_name else other_buffer
                        other_box_bottom = other_buffer if "resistance" in other_box_name or "PDHL" in other_box_name else other_high_low_of_day
                                        
                        # Check if the candle closed inside this other zone
                        if other_box_bottom <= candle['close'] <= other_box_top:
                            # Modify action to [END #] since we closed inside of another zone
                            action = "[END 7]"
                            #print(f"    [MODIFIED ACTION] Candle closed inside another zone ({other_box_name}), changing action to {action}.")
                            break  # Exit the loop since we've found a zone that modifies the action
            
            if action:
                what_type_of_candle = f"{box_name} {candle_type}" if "START" in action else None
                #havent_cleared = True if what_type_of_candle is not None else False
                print_log(f"    [INFO] {action} what_type_of_candle = {what_type_of_candle}")
                return what_type_of_candle 
    else:
        print_log("    [CZH] No Boxes were found...")        
    if type_of_candle is not None:
        return type_of_candle

def candle_ema_handler(candle, option_1_or_2 = 2):
    # option one, we we have to be above or below all emas to be assigning a candle that it is 'bullish' or 'bearish'
    # option two, we use the 200 ema as the decider, when were above the 200 were bullish and below were bearish

    # Initialize the type of the candle as None
    type_candle = None
    
    # Load EMA values
    EMAs = load_json_df('EMAs.json')
    if EMAs.empty:
        print_log("    [CEH] ERROR: 'EMAs.json' data is unavailable.")

    last_EMA = EMAs.iloc[-1]
    last_EMA_dict = last_EMA.to_dict()
    #print(f"    [CEH] Last EMA Values: {last_EMA_dict}, Price: {candle['close']}")

    # Extract EMA values
    ema_13 = last_EMA_dict.get('13')
    ema_48 = last_EMA_dict.get('48')
    ema_200 = last_EMA_dict.get('200')
    
    if ema_13 is None or ema_48 is None or ema_200 is None:
        print_log("        [candle_ema_handler] ERROR: Missing EMA data.")
        return type_candle
    
    # Get the current/closing price of the candle
    current_price = candle['close']

    if option_1_or_2 == 1:
        # Determine the highest and lowest EMA values
        top_ema = max(ema_13, ema_48, ema_200)
        btm_ema = min(ema_13, ema_48, ema_200)

        # Determine the type of candle based on its position relative to the EMAs
        if current_price > top_ema:
            type_candle = "bullish"  # Candle is above all EMAs
        elif current_price < btm_ema:
            type_candle = "bearish"  # Candle is below all EMAs
        else:
            type_candle = None  # Candle is between the EMAs (neutral)
    else: # option 2
        #print(f"    [CEH] 200ema: {ema_200}; close price: {current_price}")
        if current_price > ema_200:
            type_candle = "bullish"
        elif current_price < ema_200:
            type_candle = "bearish"
        else:
            type_candle = None

    return type_candle

def candle_close_in_zone(candle, boxes):
    # If candle close is indetween a zone the return true, else false.
    for box_name, (x_pos, high_low_of_day, buffer) in boxes.items(): 
        # Determine the top and bottom of the box
        box_top = max(high_low_of_day, buffer)
        box_btm = min(high_low_of_day, buffer)

        # Check if the candle's close price is within the box range
        if box_btm < candle['close'] < box_top:
            # Candle closed inside of a zone, so return True
            return True
    
    # Candle did not close inside any of the boxes
    return False

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
    
    log_file_path = Path(__file__).resolve().parent / 'logs/SPY_2M.log'
    
    x_coord = get_current_candle_index(log_file_path) if x is None else x
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

    # Path to markers.json file
    markers_file_path = Path(__file__).resolve().parent / 'markers.json'

    # Ensure the file exists
    if not markers_file_path.exists():
        with open(markers_file_path, 'w') as f:
            json.dump([], f)

    # Read existing markers
    try:
        with open(markers_file_path, 'r') as f:
            markers = json.load(f)
        # Ensure markers is a list
        if not isinstance(markers, list):
            markers = []
    except json.decoder.JSONDecodeError:
        markers = []

    markers.append(marker)
    with open(markers_file_path, 'w') as f:
        json.dump(markers, f, indent=4)
    
    update_2_min()

def get_dates(num_of_days, use_todays_date=False):
    nyse = mcal.get_calendar('NYSE')

    # If using today's date, else use yesterday's date or Friday's date if today is a weekend
    if use_todays_date:
        start = datetime.today()
    else:
        start = datetime.today() - timedelta(days=1)
        if start.weekday() > 4:  # If it's Saturday (5) or Sunday (6)
            start = start - timedelta(days=start.weekday() - 4)

    # Adjust start date if it's a holiday or weekend
    while not nyse.valid_days(start_date=start, end_date=start).empty is False or start.weekday() > 4:
        start -= timedelta(days=1)
        if start.weekday() > 4:  # Adjust if still weekend
            start -= timedelta(days=start.weekday() - 4)

    # Convert start to a pandas Timestamp
    start = pd.Timestamp(start)

    # Calculate business days
    business_days = pd.bdate_range(end=start, periods=num_of_days, freq='B')
    start_date = business_days[0]
    end_date = business_days[-1]

    # Formatting dates to 'YYYY-MM-DD'
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d')

    return start_date_str, end_date_str

async def get_certain_candle_data(api_key, symbol, interval, timescale, start_date, end_date, market_type='ALL', indent_lvl=1):
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
            csv_filename = f"{symbol}_{interval}_{timescale}_{market_type}.csv"
            df.to_csv(csv_filename, index=False)
            print_log(f"{indent(indent_lvl)}[GCCD] Data saved: {csv_filename}; Candles from '{start_time}' to '{end_time}'")
            return df
        else:
            print_log(f"{indent(indent_lvl)}[GCCD] No 'results' key found in the API response.")
    except requests.exceptions.HTTPError as http_err:
        print_log(f"{indent(indent_lvl)}[GCCD] HTTP error occurred: {http_err}")
    except Exception as e:
        print_log(f"{indent(indent_lvl)}[GCCD] An unexpected error occurred: {e}")

    return None

async def get_candle_data_and_merge(candle_interval, candle_timescale, am, pm, merged_file_name, indent_lvl):
    PD_AM, CD_PM = None, None
    
    # Load Aftermarket and Premarket Data
    start_date, end_date = get_dates(1, False)
    PD_AM = await get_certain_candle_data(cred.POLYGON_API_KEY, read_config('SYMBOL'), candle_interval, candle_timescale, start_date, end_date, am, indent_lvl+1)
    
    start_date, end_date = get_dates(1, True)
    CD_PM = await get_certain_candle_data(cred.POLYGON_API_KEY, read_config('SYMBOL'), candle_interval, candle_timescale, start_date, end_date, pm, indent_lvl+1)
    
    # Combine data if both are present
    if PD_AM is not None and CD_PM is not None:
        merged_df = pd.concat([PD_AM, CD_PM], ignore_index=True)
        
        # Calculate EMAs and save to CSV
        for ema_config in read_config('EMAS'):
            window, color = ema_config
            ema_column_name = f"EMA_{window}"
            merged_df[ema_column_name] = merged_df['close'].ewm(span=window, adjust=False).mean()
        
        merged_df.to_csv(merged_file_name, index=False)
        print_log(f"{indent(indent_lvl)}[GCDAM] Data saved with initial EMA calculation: {merged_file_name}")
        
    else:
        print_log(f"{indent(indent_lvl)}[GCDAM] Aftermarket or premarket data not available. EMA calculation skipped.")

def read_log_to_df(log_file_path):
    """Read log data into a DataFrame."""
    return pd.read_json(log_file_path, lines=True)

async def calculate_save_EMAs(candle, X_value):
    """Process a single candle: Adds it to CSV, Recalculate EMAs, Saves EMA's to JSON file"""
    
    merged_file_name = f"{read_config('SYMBOL')}_MERGED.csv"
   
    try:
        df = pd.read_csv(merged_file_name)
    except FileNotFoundError:
        df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close'])  # Adjust columns as needed
    
    # Convert the candle dictionary to a DataFrame and concatenate
    candle_df = pd.DataFrame([candle])
    df = pd.concat([df, candle_df], ignore_index=True)  # Use concat instead of append

    df.to_csv(merged_file_name, mode='w', header=True, index=False) # Save updated DataFrame

    # Calculate EMAs 
    current_ema_values = {}
    for window, _ in read_config('EMAS'): #window, color
        ema_column_name = f"EMA_{window}"
        df[ema_column_name] = df['close'].ewm(span=window, adjust=False).mean()
        current_ema_values[str(window)] = df[ema_column_name].iloc[-1]
    current_ema_values['x'] = X_value #add x value to json
    update_ema_json('EMAs.json', current_ema_values) #add/save ema values to json

def update_ema_json(json_path, new_ema_values):
    """Update the EMA JSON file with new EMA values by appending."""
    try:
        with open(json_path, 'r') as file:
            ema_data = json.load(file)
    except json.JSONDecodeError:
        ema_data = []  # Initialize as empty list if file is corrupt or empty

    # Append new EMA values
    ema_data.append(new_ema_values)

    # Write the updated list back to the file
    with open(json_path, 'w') as file:
        json.dump(ema_data, file, indent=4)

    update_2_min() # updating visual chart

#the functions below were a test to see if i could get the realtime ema data from polygon
async def get_ema_data(timespan, adjusted, window, series_type, order):
    # problem with this polygon api request:
    # i have to pay 200$ a month for realtime data, I currently 
    # have the free plan where i get previous day data
    today = datetime.now()
    start_timestamp = to_unix_timestamp(today.year, today.month, today.day, today.hour, today.minute, today.second) 
    end_timestamp = start_timestamp + 2 * 60 * 1000  # Add 2 minutes in milliseconds
    print_log(f"start: {convert_unix_timestamp_to_time(start_timestamp)}, end: {convert_unix_timestamp_to_time(end_timestamp)}")
    
    closest_value = None
    closest_timestamp = None
    smallest_diff = float('inf')

    url = f"https://api.polygon.io/v1/indicators/ema/{read_config('SYMBOL')}?from={start_timestamp}&to={end_timestamp}&timespan={timespan}&adjusted={adjusted}&window={window}&series_type={series_type}&order={order}&apiKey={cred.POLYGON_API_KEY}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                ema_data = await response.json()
                #print(f"ema_data: {ema_data}\n")
                if 'results' in ema_data and 'values' in ema_data['results']:
                    for data in ema_data['results']['values']:
                        print_log(f"data time: {convert_unix_timestamp_to_time(data['timestamp'])}, data value: {data['value']}")
                        timestamp_diff = abs(data['timestamp'] - start_timestamp)

                        if timestamp_diff < smallest_diff:
                            smallest_diff = timestamp_diff
                            closest_value = data['value']
                            closest_timestamp = data['timestamp']

                    return closest_timestamp, closest_value
                else:
                    print_log("EMA data not found in the response")
                    return None, None
            else:
                print_log(f"Error fetching EMA data: {response.status}")
                return None, None

def to_unix_timestamp(year, month, day, hour, minute, second=0):
    dt = datetime(year, month, day, hour, minute, second)
    return int(time.mktime(dt.timetuple()) * 1000)  # Convert to milliseconds

def convert_unix_timestamp_to_time(unix_timestamp, timezone_offset=-5):
    time = datetime.utcfromtimestamp(unix_timestamp / 1000) + timedelta(hours=timezone_offset)
    return time.strftime('%m/%d %H:%M:%S')

def load_json_df(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return pd.DataFrame(data)

async def above_below_ema(indent_lvl, threshold, price=None):
    # defualt return values 
    ab_condition_met = False
    direction = None
    within_threshold = None
    distance = None

    # Get current price
    if price is None:
        price = await get_current_price()
        # Get price for the live version, we import price into the function for the simulator.

    # Load EMA values
    EMAs = load_json_df('EMAs.json')
    if EMAs.empty:
        print_log("        [EMA] ERROR: data is unavailable.")
        return ab_condition_met, direction, within_threshold, distance  # No EMA data available 
    
    last_EMA = EMAs.iloc[-1]
    last_EMA_dict = last_EMA.to_dict()
    
    # Values for finding direction
    highest_ema = None
    lowest_ema = None

    # Ensure price is correctly positioned relative to all EMAs
    for ema, ema_value in last_EMA_dict.items():
        if ema != 'x':  # 'x' is not an EMA value but an index or timestamp
            if (highest_ema is None) or (ema_value >= highest_ema):
                highest_ema = ema_value
            if (lowest_ema is None) or (ema_value <= lowest_ema):
                lowest_ema = ema_value
            
    if (lowest_ema < price < highest_ema): # If were inbetweem the 3 emas, return empty values
        return ab_condition_met, direction, within_threshold, distance  # Price does not meet EMA position requirements
    else: # price is either above or below emas
        ab_condition_met = True
        direction = 'bull' if price >= highest_ema else 'bear' if price <= lowest_ema else None

    # Calculate distance from the 13 EMA if the price is in the correct position relative to all EMAs
    distance = abs(price - last_EMA_dict.get('13', 0))  # Default to 0 if '13' not present
    print_log(f"{indent(indent_lvl)}[AB-EMA] dir: {direction}; distance = {distance}; {price} - {last_EMA_dict.get('13', 0)};")
    
    # Check if the distance from the 13 EMA is within the allowed threshold if specified
    within_threshold = (distance <= threshold) if threshold is not None else True

    # Return True for correct EMA positioning and the threshold check result
    return ab_condition_met, direction, within_threshold, distance  

def clear_priority_candles(indent_level, json_file='priority_candles.json'):
    with open(json_file, 'w') as file:
        json.dump([], file, indent=4)
    print_log(f"{indent(indent_level)}[RESET] {json_file}; `priority_candles.json` = [];")

async def record_priority_candle(candle, zone_type_candle, json_file='priority_candles.json'):
    # Load existing data or initialize an empty list
    try:
        with open(json_file, 'r') as file:
            candles_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        candles_data = []

    current_candle_index = get_current_candle_index()

    # Append the new candle data along with its type
    candle_with_type = candle.copy()
    candle_with_type['zone_type'] = zone_type_candle
    #candle_with_type['dir_type'] = bull_or_bear_candle
    candle_with_type['candle_index'] = current_candle_index
    candles_data.append(candle_with_type)

    # Save updated data back to the file
    with open(json_file, 'w') as file:
        json.dump(candles_data, file, indent=4)

async def reset_flag_internal_values(indent_level, candle, candle_zone_type):
    clear_priority_candles(indent_level)
    await record_priority_candle(candle, candle_zone_type)
    return [], None, None

def restart_flag_data(indent_level):
    clear_priority_candles(indent_level)
    restart_state_json(indent_level)
    resolve_flags(indent_level)  

def resolve_flags(indent_level, json_file='line_data.json'):
    
    # Load the flags from JSON file
    line_data_path = Path(json_file)
    if line_data_path.exists():
        with open(line_data_path, 'r') as file:
            line_data = json.load(file)
    else:
        print_log(f"{indent(indent_level)}[FLAG ERROR] File {json_file} not found.")
        return

    # Iterate through the flags and resolve opposite flags
    updated_line_data = []
    for flag in line_data:
        #edit this part to take into account null values
        if flag['type'] and flag['status'] == 'active':
            # Mark as complete or remove the flag based on your strategy
            is_point_1_valid = flag['point_1']['x'] is not None and flag['point_1']['y'] is not None
            is_point_2_valid = flag['point_2']['x'] is not None and flag['point_2']['y'] is not None
                
            if is_point_1_valid and is_point_2_valid:
                flag['status'] = 'complete' #mark complete so its no longer edited
                updated_line_data.append(flag)
                print_log(f"{indent(indent_level)}[FLAG] Active flags resolved.")
            # Skip adding the flag to updated_line_data if it's active and has invalid points
        else:
            updated_line_data.append(flag)

    # Save the updated data back to the JSON file
    with open(line_data_path, 'w') as file:
        json.dump(updated_line_data, file, indent=4)

def determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, correct_flag, multi_order_condition_met, time_result):
    reasons = []
    if not ema_condition_met:
        reasons.append("Price not aligned with EMAs")
    if not ema_price_distance_met:
        reasons.append("Price too distant from 13 EMA")
    if not vp_1 or not vp_2:
        point = "Point 1 None" if not vp_1 else "Point 2 None"
        reasons.append(f"Invalid points; {point}")
    if not correct_flag:
        reasons.append("Incorrect Flag values for given flag")
    if not multi_order_condition_met:
        reasons.append("Number of trades limit outside of zone reached")
    if not time_result:
        reasons.append("Trade time conflicts with economic events")
    return "; ".join(reasons) if reasons else "No specific reason"

def restart_state_json(indent_level, state_file_path):
    initial_state = {
        'flag_names': [],
        'flag_type': None,
        'start_point': None,
        'slope': None,
        'intercept': None,
        'candle_points': []
        
    }
    
    with open(state_file_path, 'w') as file:
        json.dump(initial_state, file, indent=4)
    print_log(f"{indent(indent_level)}[RESET] State JSON file has been reset to initial state.")

def initialize_ema_json(json_path):
    """Ensure the EMA JSON file exists and is valid; initialize if not."""
    if not os.path.exists(json_path) or os.stat(json_path).st_size == 0:
        with open(json_path, 'w') as file:
            json.dump([], file)  # Initialize with an empty list
    try:
        with open(json_path, 'r') as file:
            return json.load(file) if isinstance(json.load(file), list) else []
    except json.JSONDecodeError:
        return []

async def read_ema_json(position):
    try:
        with open("EMAs.json", "r") as file:
            emas = json.load(file)
            latest_ema = emas[position]
            return latest_ema
    except FileNotFoundError:
        print_log("EMAs.json file not found.")
        return None
    except KeyError:
        print_log(f"EMA type [{position}] not found in the latest entry.")
        return None
    except Exception as e:
        await error_log_and_discord_message(e, "ema_strategy", "read_last_ema_json")
        return None
    
def get_latest_ema_values(ema_type):
    # ema_type must be a string, Ex: "13" or "48", "200" ect...
    ema_type = str(ema_type)
    filepath = "EMAs.json"

    # Check if the file is empty before reading
    if os.stat(filepath).st_size == 0:
        print_log(f"    [GLEV] EMAs.json is empty.")
        return None, None

    try:
        # Read the EMA data from the JSON file
        with open(filepath, "r") as file:
            emas = json.load(file)

        if not emas:  # Check if the file is empty or contains no data
            print_log("    [GLEV] EMAs.json is empty or contains no data.")
            return None, None
        latest_ema = emas[-1][ema_type]
        #print(f"Latest emas: {latest_ema}")
        index_ema = emas[-1]['x']

        return latest_ema, index_ema
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print_log(f"    [GLEV] EMA error: {e}")
        return None, None

def is_ema_broke(ema_type, symbol, timeframe, cp):
    # Get EMA Data
    latest_ema, index_ema = get_latest_ema_values(ema_type)
    if latest_ema is None or index_ema is None:
        return False
    
    # Get Candle Data
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(filepath, "r") as file:
            lines = file.readlines()
            index_candle = len(lines) - 1
            latest_candle = json.loads(lines[-1])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print_log(f"Log file error: {e}")
        return False

    if index_candle == index_ema:
        open_price = latest_candle["open"]
        close_price = latest_candle["close"]

        # Check conditions based on option type
        if open_price and close_price:
            if cp == 'call' and latest_ema > close_price:
                print_log(f"        [EMA BROKE] {ema_type}ema Hit, Sell rest of call. [CLOSE]: {close_price}; [Last EMA]: {latest_ema}; [OPEN]: {open_price}")
                return True
            elif cp == 'put' and latest_ema < close_price:
                print_log(f"        [EMA BROKE] {ema_type}ema Hit, Sell rest of put. [OPEN]: {open_price}; [EMA {ema_type}]: {latest_ema}; [CLOSE] {close_price}")
                return True
        else:
            print_log(f"    [IEB {ema_type} EMA] unable to get open and close price... Candle OC: {open_price}, {close_price}")
    else:
        # Print the indices to show they don't match and wait before trying again
        print_log(f"    [IEB {ema_type} EMA]\n        index_candle: {index_candle}; Length Lines: {len(lines)}\n        index_ema: {index_ema}; latest ema: {latest_ema}; Indices do not match...")
    
    return False

def read_last_n_lines(file_path, n):
    # Ensure the logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    # Check if the file exists, if not, create an empty file
    if not os.path.isfile(file_path):
        with open(file_path, 'w') as file:
            pass

    with open(file_path, 'r') as file:
        lines = file.readlines()
        last_n_lines = lines[-n:]
        return [json.loads(line.strip()) for line in last_n_lines]

def check_order_type_json(candle_type, file_path = "order_candle_type.json"):
    try:
        with open(file_path, 'r') as file:
            candle_types = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print_log("Error reading the file or file not found. Assuming no orders have been placed.")
        candle_types = []

    # Count how many times the given candle_type appears in the list
    num_of_matches = candle_types.count(candle_type)
    #print(num_of_matches)
    # Compare the count with the threshold
    if num_of_matches >= read_config('ORDERS_ZONE_THRESHOLD'):
        return False, num_of_matches # More or equal matches than the threshold, do not allow more orders

    return True, num_of_matches  # Fewer matches than the threshold, allow more orders

# Function to initialize the CSV file with headers if it doesn't exist
def initialize_order_log(filepath):
    if not os.path.exists(filepath):
        with open(filepath, 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['what_type_of_candle', 'time_entered', 'ema_distance', 'num_of_matches', 'line_degree_angle',
                             'ticker_symbol', 'strike_price', 'option_type', 'order_quantity', 'order_bid_price', 'total_investment',
                             'time_exited', 'lowest_bid', 'max_drawdown', 'highest_bid', 'max_gain', 'avg_sold_bid', 'total_profit', 'total_percentage'])

# Log initial order details
def log_order_details(filepath, what_type_of_candle, time_entered, ema_distance, num_of_matches, line_degree_angle,
                      ticker_symbol, strike_price, option_type, order_quantity, order_bid_price, total_investment):
    with open(filepath, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([what_type_of_candle, time_entered, ema_distance, num_of_matches, line_degree_angle,
                         ticker_symbol, strike_price, option_type, order_quantity, order_bid_price, total_investment])

# Update the CSV file with additional details
def update_order_details(filepath, unique_order_id, **kwargs):
    # UOD means Update Order Details
    df = pd.read_csv(filepath)
    
    # `unique_order_id` is f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
    order_id_parts = unique_order_id.split('-')
    symbol, option_type, strike_price, expiration_date, timestamp = order_id_parts[:5]

    # Convert the timestamp to datetime object
    dt = datetime.strptime(timestamp[:12], "%Y%m%d%H%M")  # Only use up to minutes

    # Format the datetime object to the desired string format (ignore seconds)
    formatted_timestamp = dt.strftime("%m/%d/%Y-%I:%M %p")
    
    row_found = False
    for index, row in df.iterrows():
        # Normalize the row's timestamp for comparison, ensuring AM/PM is preserved
        row_time_formatted = row['time_entered']
        #print_log(f"{indent(indent_lvl+1)}[UOD 1] Checking row at index {index}: {row_time_formatted}")
        
        if (row['ticker_symbol'] == symbol and 
            row['strike_price'] == float(strike_price) and 
            row['option_type'] == option_type and 
            row_time_formatted == formatted_timestamp):  # Compare normalized timestamps
            row_found = True
            for key, value in kwargs.items():
                df.at[index, key] = value
            break  # If the correct row is found, no need to continue looping
    
    if not row_found:
        print_log(f"    [UOD] ERROR: No matching row found for timestamp: {formatted_timestamp}")

    df.to_csv(filepath, index=False)

def add_candle_type_to_json(candle_type, file_path = "order_candle_type.json"):
    # Read the current contents of the file, or initialize an empty list if file does not exist
    try:
        with open(file_path, 'r') as file:
            candle_types = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print_log("File not found or is empty. Starting a new list.")
        candle_types = []

    # Append the new candle_type to the list
    candle_types.append(candle_type)

    # Write the updated list back to the file
    with open(file_path, 'w') as file:
        json.dump(candle_types, file, indent=4)  # Using indent for better readability of the JSON file

def check_valid_points(indent_lvl, line_name, line_type, print_statements=True):
    line_data_path = Path('line_data.json')
    default_structure = {
        "active_flags": [],
        "completed_flags": []
    }

    line_data = safe_read_json(line_data_path, default=default_structure, indent_lvl=indent_lvl+1)
    all_flags = line_data.get("active_flags", []) + line_data.get("completed_flags", [])

    for flag in all_flags:
        if flag.get('name') == line_name:
            point_1 = flag.get('point_1')
            point_2 = flag.get('point_2')

            point_1_valid = point_1 and point_1.get('x') is not None and point_1.get('y') is not None
            point_2_valid = point_2 and point_2.get('x') is not None and point_2.get('y') is not None

            if point_1_valid and point_2_valid:
                x_diff = point_2['x'] - point_1['x']
                y_diff = point_2['y'] - point_1['y']
                angle = math.degrees(math.atan2(y_diff, x_diff))

                is_greater = point_1['y'] >= point_2['y']
                is_less = point_1['y'] <= point_2['y']
                correct_flag = None

                if print_statements:
                    print_log(f"{indent(indent_lvl)}[CVP] line_type = {line_type}; p1>=p2: {is_greater}; p1<=p2: {is_less}")

                if line_type == 'bull':
                    correct_flag = (point_1['x'] < point_2['x']) and is_greater
                elif line_type == 'bear':
                    correct_flag = (point_1['x'] < point_2['x']) and is_less

                return point_1_valid, point_2_valid, angle, correct_flag

            return point_1_valid, point_2_valid, None, None

    return False, False, None, None

    
def reset_json(file_path, contents):
    with open(file_path, 'w') as f:
        json.dump(contents, f, indent=4)
        print_log(f"[RESET] Cleared file: {file_path}")

def empty_log(filename):
    """
    Empties the contents of the specified log file.

    Args:
    filename (str): The base name of the log file without extension.
    """
    # Ensure the logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    
    # Path to the log file
    log_file_path = os.path.join(LOGS_DIR, f'{filename}.log')

    # Open the file in write mode to truncate it
    with open(log_file_path, 'w') as file:
        pass  # Opening in write mode ('w') truncates the file automatically

    print_log(f"[CLEARED]'{filename}.log' has been emptied.")

def clear_states_folder(directory="states"):
    """
    Deletes all JSON files in the specified directory.
    
    Args:
        directory (str): The folder containing the state files to clear. Default is "states".
    """
    if not os.path.exists(directory):
        print_log(f"Folder '{directory}' does not exist.")
        return

    # Get all JSON files in the directory
    json_files = glob.glob(os.path.join(directory, "*.json"))

    if not json_files:
        print_log(f"[RESET] No JSON files found in '{directory}'.")
        return

    # Delete each file
    for file in json_files:
        try:
            os.remove(file)
            print_log(f" - Deleted: {file}")
        except Exception as e:
            print_log(f" - Error deleting {file}: {e}")

    print_log(f"[RESET] All JSON files in '{directory}' have been cleared.")

def get_test_data_and_allocate(folder_name):
    # Define paths to the test data directory and the target files
    test_data_dir = Path(LOGS_DIR) / 'test_data' / folder_name
    boxes_tpls_path = test_data_dir / 'Boxes_tpls.log'
    ema_source_path = test_data_dir / 'EMAs.json'
    candle_source_path = test_data_dir / 'SPY_2M.log'

    # Define paths for target files to clear and populate
    all_emas_path = Path(LOGS_DIR) / 'all_EMAs.json'
    all_candles_path = Path(LOGS_DIR) / 'all_candles.log'

    # Clear the contents of 'all_EMAs.json' and 'all_candles.log' to prevent mixing old data with new
    all_emas_path.write_text('[]')
    all_candles_path.write_text('')

    # Read and parse 'Boxes_tpls.log' to extract zones and TPLs
    with open(boxes_tpls_path, 'r') as boxes_tpls_file:
        lines = boxes_tpls_file.readlines()
        # Assume zones are always on line 2 and TPLs are on line 4
        zones = eval(lines[1].strip())  # Convert string representation of dict to an actual dict
        
        # Extract dictionary from TPL lines using regex
        tpl_lines = None
        if len(lines) > 3 and lines[3].strip() != '{}':
            match = re.search(r'\{.*\}', lines[3].strip())
            if match:
                tpl_lines = eval(match.group(0))  # Safely extract and evaluate only the dictionary part

    # Copy data from 'EMAs.json' in the folder to 'all_EMAs.json'
    with open(ema_source_path, 'r') as ema_source_file:
        ema_data = ema_source_file.read()
        with open(all_emas_path, 'w') as all_emas_file:
            all_emas_file.write(ema_data)

    # Copy data from 'SPY_2M.log' in the folder to 'all_candles.log'
    with open(candle_source_path, 'r') as candle_source_file:
        candle_data = candle_source_file.read()
        with open(all_candles_path, 'w') as all_candles_file:
            all_candles_file.write(candle_data)

    return zones, tpl_lines