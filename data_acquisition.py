#data_aquisition.py
import requests
import pandas as pd
import pandas_market_calendars as mcal
import numpy as np
from error_handler import error_log_and_discord_message
import websockets
from websockets.exceptions import InvalidStatusCode, ConnectionClosedError
import asyncio
import cred
import aiohttp
import json
from typing import Optional
import pytz
import time
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path

RETRY_INTERVAL = 1  # Seconds between reconnection attempts
should_close = False  # Global variable to signal if the WebSocket should close

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config

config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
SYMBOL = config["SYMBOL"]
EMA = config["EMAS"]

async def ws_connect(queue, symbol):
    global should_close
    print("Starting ws_connect()...")
    should_close = False

    while True:
        try:
            session_id = get_session_id()
            if session_id is None:
                print("Failed to get a new session ID. Retrying in 1 second...")
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
                print(f">>> {payload}, {datetime.now().isoformat()}")
                print("[Hr:Mn:Sc]")

                async for message in websocket:
                    if should_close:
                        print("Closing WebSocket connection.")
                        await websocket.close()
                        return

                    await queue.put(message)

        except InvalidStatusCode as e:
            if e.status_code == 502:
                print("Encountered a server-side error (HTTP 502). There's nothing we can do about it at this moment.")
            else:
                print(f"Encountered a server-side error (HTTP {e.status_code}).")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except websockets.ConnectionClosed:
            print("WebSocket connection closed. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except Exception as e:
            await error_log_and_discord_message(e, "data_acquisition", "ws_connect", "An error occurred. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

def get_session_id(retry_attempts=3, backoff_factor=1):
    url = "https://api.tradier.com/v1/markets/events/session"
    headers = {
        "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
        "Accept": "application/json"
    }
    for attempt in range(retry_attempts):
        response = requests.post(url, data={}, headers=headers)
        if response.status_code == 200:
            return response.json()["stream"]["sessionid"]
        else:
            print(f"Error: Unable to get session ID: {response.text}, retrying...")
            time.sleep(backoff_factor * (2 ** attempt))  # Exponential backoff
    print("Failed to get a new session ID after retries.")
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
    print(f"Candle Limit, Limit and Business Days:\n{candle_limit}, {limit}, {business_days}\n")

    asc_desc = "asc"
    print(f"asc_desc = {asc_desc}")

    df = pd.DataFrame()  # Initialize an empty DataFrame to handle cases where data might not be fetched
    try:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/{interval}/{timescale}/{start_date}/{end_date}?adjusted=true&sort={asc_desc}&limit={limit}&apiKey={api_key}"
        response = requests.get(url)
        response.raise_for_status()  # This will raise an HTTPError if the HTTP request returned an unsuccessful status code
        
        data = response.json()
        print(f"({interval}m) url: {url}")
    
        print(f"response: {response}\n") # i want to print conditions somehow

        # Check if 'results' key is in the data
        if 'results' in data:
            #print("Results is true!!!")
            df = pd.DataFrame(data['results'])
            df['t'] = pd.to_datetime(df['t'], unit='ms')
            df.rename(columns={'v': 'volume', 'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'timestamp'}, inplace=True)
            if interval == 15:
                corrected_df = await filter_data(df)
            elif interval==2:
                corrected_df = await filter_data(df, exclude_today=False)
            save_to_csv(corrected_df, f"{symbol}_{interval}_{timescale}_candles.csv")
            return corrected_df
        else:
            print("No 'results' key found in the API response.")
            return pd.DataFrame()  # Return an empty DataFrame if no results

    except requests.exceptions.HTTPError as http_err:
        print("HTTP error occurred:", http_err)
    except KeyError as key_err:
        print("Key error in data conversion:", key_err)
    except Exception as e:
        print("An unexpected error occurred:", e)

    return pd.DataFrame()

async def filter_data(df, exclude_today=True):
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
    # Keep data for Monday (0) to Friday (4)
    weekday_df = df[df['timestamp'].dt.dayofweek < 5]

    if exclude_today:
        # Exclude current day data
        today = pd.Timestamp(datetime.now().date())
        weekday_df = weekday_df[weekday_df['timestamp'].dt.date < today.date()]

    # Keep data within market hours
    market_open_time = pd.Timestamp('14:30:00').time()#09:30:00
    market_close_time = pd.Timestamp('21:00:00').time()#16:00:00
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

async def get_current_price(symbol: str) -> float:
    url = "wss://ws.tradier.com/v1/markets/events"  # Replace with your actual WebSocket URL
    try:
        session_id = get_session_id()  # Call the get_session_id function
        if session_id is None:
            print("Failed to get a new session ID for get_current_price(), data_acquisition.py.")
            return 0.0

        async with websockets.connect(url, ssl=True, compression=None) as websocket:
            # Send payload to subscribe to the symbol's trades
            payload = json.dumps({
                "symbols": [symbol],
                "sessionid": session_id,  # Include the session ID in the payload
                # Add other fields as required by your API
            })
            await websocket.send(payload)

            # Wait for the first trade message
            while True:
                message = await websocket.recv()
                data = json.loads(message)

                if 'type' in data and data['type'] == 'trade':
                    return float(data.get("price", 0))

    except InvalidStatusCode as e:
        print(f"WebSocket connection error: {e}")
    except Exception as e:
        print(f"Error in get_current_price: {e}")

    return 0.0  # Return a default value or handle this case as required

async def add_markers(event_type):
    
    log_file_path = Path(__file__).resolve().parent / 'logs/SPY_2M.log'
    x_coord = get_current_candle_index(log_file_path)
    y_coord = await get_current_price(SYMBOL)
    print(f"    [MARKER] {x_coord}, {y_coord}, {event_type}")

    x_coord += 1

    marker_styles = {
        'buy': {'marker': '^', 'color': 'blue'},
        'trim': {'marker': 'o', 'color': 'red'},
        'sell': {'marker': 'v', 'color': 'red'}
    }
    
    marker = {
        'event_type': event_type,
        'x': x_coord,
        'y': y_coord,
        'style': marker_styles[event_type]
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

#another test function
async def get_certain_candle_data(api_key, symbol, interval, timescale, start_date, end_date, market_type='ALL'):
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

            # Filter DataFrame based on market type
            if market_type == 'PREMARKET':
                df = df[df['timestamp'].dt.time < datetime.strptime("09:30", "%H:%M").time()]
            elif market_type == 'MARKET':
                df = df[(df['timestamp'].dt.time >= datetime.strptime("09:30", "%H:%M").time()) & 
                        (df['timestamp'].dt.time < datetime.strptime("16:00", "%H:%M").time())]
            elif market_type == 'AFTERMARKET':
                df = df[df['timestamp'].dt.time >= datetime.strptime("16:00", "%H:%M").time()]
            # For 'ALL', no filtering is needed

            df.rename(columns={'v': 'volume', 'o': 'open', 'c': 'close', 'h': 'high', 'l': 'low', 't': 'timestamp'}, inplace=True)
            csv_filename = f"{symbol}_{interval}_{timescale}_{market_type}.csv"
            df.to_csv(csv_filename, index=False)
            print(f"Data saved: {csv_filename}")
            return df
        else:
            print("No 'results' key found in the API response.")
    except requests.exceptions.HTTPError as http_err:
        print("HTTP error occurred:", http_err)
    except Exception as e:
        print("An unexpected error occurred:", e)

    return None

async def get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, am, pm, merged_file_name):
    PD_AM, CD_PM = None, None
    #SPY_2_minute_AFTERMARKET.csv
    start_date, end_date = get_dates(1, False)
    print(f"\n[AM] Start and End: {start_date}, {end_date}")
    PD_AM = await get_certain_candle_data(cred.POLYGON_API_KEY, SYMBOL, candle_interval, candle_timescale, start_date, end_date, am)
    #SPY_2_minute_PREMARKET.csv
    start_date, end_date = get_dates(1, True)
    print(f"\n[PM] Start and End days: {start_date}, {end_date}")
    CD_PM = await get_certain_candle_data(cred.POLYGON_API_KEY, SYMBOL, candle_interval, candle_timescale, start_date, end_date, pm)
    #more code...
    if PD_AM is not None and CD_PM is not None:
        # Merge dataframes
        merged_df = pd.concat([PD_AM, CD_PM], ignore_index=True)
        # Calculate EMAs and save to CSV
        for ema_config in EMA:
            window, color = ema_config
            ema_column_name = f"EMA_{window}"
            merged_df[ema_column_name] = merged_df['close'].ewm(span=window, adjust=False).mean()
        merged_df.to_csv(merged_file_name, index=False)
        print(f"\nData saved: {merged_file_name}")
        for window, _ in EMA:
            ema_column_name = f"EMA_{window}"
            print(f"EMA {window}: {merged_df[ema_column_name].iloc[-1]}")
    else:
        print("Aftermarket or premarket data not available. EMA calculation skipped.")

def read_log_to_df(log_file_path):
    """Read log data into a DataFrame."""
    return pd.read_json(log_file_path, lines=True)

async def calculate_save_EMAs(candle, X_value):
    """Process a single candle: Adds it to CSV, Recalculate EMAs, Saves EMA's to JSON file"""
    
    merged_file_name = f"{SYMBOL}_MERGED.csv"
   
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
    for window, _ in EMA: #window, color
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

#the functions below were a test to see if i could get the realtime ema data from polygon
async def get_ema_data(timespan, adjusted, window, series_type, order):
    # problem with this polygon api request:
    # i have to pay 200$ a month for realtime data, I currently 
    # have the free plan where i get previous day data
    today = datetime.now()
    start_timestamp = to_unix_timestamp(today.year, today.month, today.day, today.hour, today.minute, today.second) 
    end_timestamp = start_timestamp + 2 * 60 * 1000  # Add 2 minutes in milliseconds
    print(f"start: {convert_unix_timestamp_to_time(start_timestamp)}, end: {convert_unix_timestamp_to_time(end_timestamp)}")
    
    closest_value = None
    closest_timestamp = None
    smallest_diff = float('inf')

    url = f"https://api.polygon.io/v1/indicators/ema/{SYMBOL}?from={start_timestamp}&to={end_timestamp}&timespan={timespan}&adjusted={adjusted}&window={window}&series_type={series_type}&order={order}&apiKey={cred.POLYGON_API_KEY}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                ema_data = await response.json()
                #print(f"ema_data: {ema_data}\n")
                if 'results' in ema_data and 'values' in ema_data['results']:
                    for data in ema_data['results']['values']:
                        print(f"data time: {convert_unix_timestamp_to_time(data['timestamp'])}, data value: {data['value']}")
                        timestamp_diff = abs(data['timestamp'] - start_timestamp)

                        if timestamp_diff < smallest_diff:
                            smallest_diff = timestamp_diff
                            closest_value = data['value']
                            closest_timestamp = data['timestamp']

                    return closest_timestamp, closest_value
                else:
                    print("EMA data not found in the response")
                    return None, None
            else:
                print(f"Error fetching EMA data: {response.status}")
                return None, None

def to_unix_timestamp(year, month, day, hour, minute, second=0):
    dt = datetime(year, month, day, hour, minute, second)
    return int(time.mktime(dt.timetuple()) * 1000)  # Convert to milliseconds

def convert_unix_timestamp_to_time(unix_timestamp, timezone_offset=-5):
    time = datetime.utcfromtimestamp(unix_timestamp / 1000) + timedelta(hours=timezone_offset)
    return time.strftime('%m/%d %H:%M:%S')