#data_aquisition.py
import requests
import pandas as pd
import pandas_market_calendars as mcal
import numpy as np
from chart_visualization import update_2_min
from error_handler import error_log_and_discord_message
import websockets
from websockets.exceptions import InvalidStatusCode
import asyncio
import cred
import aiohttp
import json
import pytz
import time
from datetime import datetime, timedelta
import os
import math
from pathlib import Path

RETRY_INTERVAL = 1  # Seconds between reconnection attempts
should_close = False  # Global variable to signal if the WebSocket should close

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config

config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
SYMBOL = config["SYMBOL"]
EMA = config["EMAS"]
ORDERS_ZONE_THRESHOLD = config["ORDERS_ZONE_THRESHOLD"]

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
                corrected_df = await filter_data(df, True, '13:30:00', '19:45:00')
            elif interval==2:
                corrected_df = await filter_data(df, False)
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
    print(f'day_time_start: {day_time_start}; day_time_end: {day_time_end}')
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

async def add_markers(event_type, x=None, y=None, percentage=None):
    
    log_file_path = Path(__file__).resolve().parent / 'logs/SPY_2M.log'
    if x is not None and y is not None:
        x_coord = x
        y_coord = y
    else:
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

    update_2_min()

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

def load_json_df(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return pd.DataFrame(data)

async def above_below_ema(state, threshold=None):
    """
    Determines if the current price is above or below the 13 EMA and by what margin.

    Parameters:
    state (str): 'above' or 'below' indicating desired state relative to EMA.
    threshold (float, optional): The maximum allowable distance from the 13 EMA for additional condition checks.

    Returns:
    (bool, bool): Tuple where the first item indicates if the price is correctly positioned relative to all EMAs,
                  and the second indicates if the price is within the specified threshold from the 13 EMA.
    """

    # Get current price
    price = await get_current_price(SYMBOL)

    # Load EMA values
    EMAs = load_json_df('EMAs.json')
    if EMAs.empty:
        print("        [EMA] ERROR: data is unavailable.")
        return False, None  # No EMA data available 
    
    last_EMA = EMAs.iloc[-1]
    last_EMA_dict = last_EMA.to_dict()
    print(f"        [EMA] Last EMA Values: {last_EMA_dict}, Price: {price}")
    
    # Ensure price is correctly positioned relative to all EMAs
    for ema, ema_value in last_EMA_dict.items():
        if ema != 'x':  # 'x' is not an EMA value but an index or timestamp
            if (state == 'above' and price <= ema_value) or (state == 'below' and price >= ema_value):
                return False, None  # Price does not meet EMA position requirements
    
    # Calculate distance from the 13 EMA if the price is in the correct position relative to all EMAs
    distance = abs(price - last_EMA_dict.get('13', 0))  # Default to 0 if '13' not present
    print(f"        [EMA] distance = {distance}")
    
    # Check if the distance from the 13 EMA is within the allowed threshold if specified
    within_threshold = (distance <= threshold) if threshold is not None else True

    return True, within_threshold  # Return True for correct EMA positioning and the threshold check result

def resolve_flags(json_file='line_data.json'):
    
    # Load the flags from JSON file
    line_data_path = Path(json_file)
    if line_data_path.exists():
        with open(line_data_path, 'r') as file:
            line_data = json.load(file)
    else:
        print(f"    [FLAG ERROR] File {json_file} not found.")
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
                print("    [FLAG] Active flags resolved.")
            # Skip adding the flag to updated_line_data if it's active and has invalid points
        else:
            updated_line_data.append(flag)

    # Save the updated data back to the JSON file
    with open(line_data_path, 'w') as file:
        json.dump(updated_line_data, file, indent=4)

def determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, multi_order_condition_met):
    reasons = []
    if not ema_condition_met:
        reasons.append("Price not aligned with EMAs")
    if not ema_price_distance_met:
        reasons.append("Price too distant from 13 EMA")
    if not vp_1 or not vp_2:
        point = "Point 1 None" if not vp_1 else "Point 2 None"
        reasons.append(f"Invalid points; {point}")
    if not multi_order_condition_met:
        reasons.append("Trade limit in zone reached")
    return "; ".join(reasons) if reasons else "No specific reason"

def restart_state_json(reset_all, state_file_path="state.json", reset_side=None):
    """
    Initializes or resets the state.json file to default values or specific sections.

    Parameters:
    reset_all (bool): if True, reset entire state.
    state_file_path (str): The file path for the state.json file.
    reset_side (str): which side to reset, "bear" or "bull".
    """
    initial_state = {
        'current_high': None,
        'highest_point': None,
        'lower_highs': [],
        'current_low': None,
        'lowest_point': None,
        'higher_lows': [],
        'slope': None,
        'intercept': None,
        'previous_candles': []
    }
    if reset_all:
        with open(state_file_path, 'w') as file:
            json.dump(initial_state, file, indent=4)
        print("    [RESET] State JSON file has been reset to initial state.")
    elif not reset_all and reset_side is not None:
        # Load existing state from file
        try:
            with open(state_file_path, 'r') as file:
                state = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError):
            print("    [ERROR] State file not found or is corrupt. Resetting to initial state.")
            state = initial_state

        # Apply selective resets based on the specified side
        if reset_side == "bull":
            state['current_high'] = None
            state['highest_point'] = None
            state['lower_highs'] = []
        elif reset_side == "bear":
            state['current_low'] = None
            state['lowest_point'] = None
            state['higher_lows'] = []
        
        # Save the updated state back to the file
        with open(state_file_path, 'w') as file:
            json.dump(state, file, indent=4)
        print(f"    [RESET] State JSON file has been reset for {reset_side} side.")

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

def clear_priority_candles(havent_cleared, type_candle, json_file='priority_candles.json'):
    if havent_cleared:
        with open(json_file, 'w') as file:
            json.dump([], file, indent=4)
        print(f"    [RESET] {json_file}; what_type_of_candle = {type_candle}")
        havent_cleared = False

async def record_priority_candle(candle, type_candles, json_file='priority_candles.json'):
    # Load existing data or initialize an empty list
    try:
        with open(json_file, 'r') as file:
            candles_data = json.load(file)
        # Check if 'type' of the last candle exists and does not equal 'type_candles'
        if candles_data and candles_data[-1]['type'] != type_candles:
            # If the types don't match, clear the priority candles
            clear_priority_candles(True, type_candles, json_file)
            restart_state_json(True)
            candles_data = []  # Reset candles_data to be an empty list after clearing
    except (FileNotFoundError, json.JSONDecodeError):
        candles_data = []

    current_candle_index = get_current_candle_index()

    # Append the new candle data along with its type
    candle_with_type = candle.copy()
    candle_with_type['type'] = type_candles
    candle_with_type['candle_index'] = current_candle_index
    candles_data.append(candle_with_type)

    # Save updated data back to the file
    with open(json_file, 'w') as file:
        json.dump(candles_data, file, indent=4)

async def read_ema_json(position):
    try:
        with open("EMAs.json", "r") as file:
            emas = json.load(file)
            latest_ema = emas[position]
            return latest_ema
    except FileNotFoundError:
        print("EMAs.json file not found.")
        return None
    except KeyError:
        print(f"EMA type [{position}] not found in the latest entry.")
        return None
    except Exception as e:
        await error_log_and_discord_message(e, "ema_strategy", "read_last_ema_json")
        return None
    
def is_ema_broke(ema_type, symbol, timeframe, cp):
    # Load the latest EMA values
    try:
        with open("EMAs.json", "r") as file:
            emas = json.load(file)
            latest_ema = emas[-1][ema_type]  # Assuming 'ema_type' is a string like "13", "48", or "200"
            index_ema = emas[-1]['x']
    except FileNotFoundError:
        print("EMAs.json file not found.")
        return False
    except KeyError:
        print(f"EMA type {ema_type} not found in the latest entry.")
        return False
    
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(filepath, "r") as file:
            lines = file.readlines()
            index_candle = len(lines) - 1
            latest_candle = json.loads(lines[-1])
    except FileNotFoundError:
        print(f"{symbol}_{timeframe}.log file not found.")
        return False
    except json.JSONDecodeError:
        print(f"Error decoding the last candle from {symbol}_{timeframe}.log")
        return False
    
    if index_candle == index_ema:
        open_price = latest_candle["open"]
        close_price = latest_candle["close"]
    else:
        open_price = None
        close_price = None  

    # Check conditions based on option type
    if open_price and close_price:
        if cp == 'call' and latest_ema > close_price: #close_price > latest_ema and open_price < latest_ema:
            print(f"        [EMA BROKE] {ema_type}ema Hit, Sell rest of call. [CLOSE]: {close_price}; [Last EMA]: {latest_ema}; [OPEN]: {open_price}")
            return True
        elif cp == 'put' and latest_ema < close_price:
            print(f"        [EMA BROKE] {ema_type}ema Hit, Sell rest of put. [OPEN]: {open_price}; [EMA {ema_type}]: {latest_ema}; [CLOSE] {close_price}")
            return True
    return False

def read_last_n_lines(file_path, n): #code from a previous ema tradegy, thought it may help. pls edit if need be.
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
        print("Error reading the file or file not found. Assuming no orders have been placed.")
        candle_types = []

    # Count how many times the given candle_type appears in the list
    num_of_matches = candle_types.count(candle_type)
    #print(num_of_matches)
    # Compare the count with the threshold
    if num_of_matches >= ORDERS_ZONE_THRESHOLD:
        return False  # More or equal matches than the threshold, do not allow more orders

    return True  # Fewer matches than the threshold, allow more orders

def add_candle_type_to_json(candle_type, file_path = "order_candle_type.json"):
    # Read the current contents of the file, or initialize an empty list if file does not exist
    try:
        with open(file_path, 'r') as file:
            candle_types = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print("File not found or is empty. Starting a new list.")
        candle_types = []

    # Append the new candle_type to the list
    candle_types.append(candle_type)

    # Write the updated list back to the file
    with open(file_path, 'w') as file:
        json.dump(candle_types, file, indent=4)  # Using indent for better readability of the JSON file

def is_angle_valid(slope, config, bearish=False):
    """
    Calculates the angle of the slope and checks if it is within the valid range specified in the config.
    
    Parameters:
    slope (float): The slope of the line.
    config (dict): Configuration dictionary containing angle criteria.

    Returns:
    bool: True if the angle is within the valid range, False otherwise.
    """
    angle = math.atan(slope) * (180 / math.pi)
    
    if bearish:
        min_angle = config["FLAGPOLE_CRITERIA"]["BEAR_MIN_ANGLE"]
        max_angle = config["FLAGPOLE_CRITERIA"]["BEAR_MAX_ANGLE"]
    else:
        min_angle = config["FLAGPOLE_CRITERIA"]["BULL_MIN_ANGLE"]
        max_angle = config["FLAGPOLE_CRITERIA"]["BULL_MAX_ANGLE"]

    print(f"                [IAV Slope Angle] {angle} degrees for {'Bear' if bearish else 'Bull'} flag")
    return min_angle <= angle <= max_angle

def check_valid_points(line_name):
    line_data_path = Path('line_data.json')
    if line_data_path.exists():
        with open(line_data_path, 'r') as file:
            line_data = json.load(file)
            for flag in line_data:
                if flag['name'] == line_name:
                    # Check and print point_1's x, y if available
                    point_1 = flag.get('point_1')
                    #if point_1:
                    #    print(f"        [LINE CHECK] Point 1: x={point_1.get('x')}, y={point_1.get('y')}")
                    #else:
                    #    print("        [LINE CHECK] Point 1: None")

                    # Check and print point_2's x, y if available
                    point_2 = flag.get('point_2')
                    #if point_2:
                    #    print(f"        [LINE CHECK] Point 2: x={point_2.get('x')}, y={point_2.get('y')}")
                    #else:
                    #    print("        [LINE CHECK] Point 2: None")

                    # Ensure both point_1 and point_2 exist and have non-null x and y
                    point_1_valid = point_1 and point_1.get('x') is not None and point_1.get('y') is not None
                    point_2_valid = point_2 and point_2.get('x') is not None and point_2.get('y') is not None
                    
                    return point_1_valid, point_2_valid
    return False

def update_state(state_file_path, current_high, highest_point, lower_highs, current_low, lowest_point, higher_lows, slope, intercept, candle):
    with open(state_file_path, 'r') as file:
        state = json.load(file)

    state['current_high'] = current_high
    state['highest_point'] = highest_point

    # Create a new list for lower_highs based on the condition
    new_lower_highs = [tuple(lh) for lh in lower_highs if lh[0] > highest_point[0]]
    # Update lower_highs if there are new values, otherwise empty the list
    if new_lower_highs:
        unique_new_lower_highs = set(new_lower_highs)
        state['lower_highs'] = list(unique_new_lower_highs)
    else:
        state['lower_highs'] = []
        state['previous_candles'] = []

    state['current_low'] = current_low
    state['lowest_point'] = lowest_point

    # Create a new list for higher_lows based on the condition
    new_higher_lows = [tuple(hl) for hl in higher_lows if hl[0] > lowest_point[0]]
    # Update higher_lows if there are new values, otherwise empty the list
    if new_higher_lows:
        unique_new_higher_lows = set(new_higher_lows)
        state['higher_lows'] = list(unique_new_higher_lows)
    else:
        state['higher_lows'] = []
        state['previous_candles'] = []

    state['slope'] = slope
    state['intercept'] = intercept

    # Add the current candle to previous_candles, avoiding duplicates
    if candle['candle_index'] not in [c['candle_index'] for c in state['previous_candles']]:
        state['previous_candles'].append(candle)

    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)

def count_flags_in_json(json_file='line_data.json'):
    try:
        with open(json_file, 'r') as file:
            lines = json.load(file)
            # Count only those flags with a status of 'complete'
            complete_flags = [line for line in lines if line.get('status') == 'complete']
            return len(complete_flags)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0  # Return 0 if file doesn't exist or is empty
    
def reset_json(file_path, contents):
    with open(file_path, 'w') as f:
        json.dump(contents, f, indent=4)
        print(f"[RESET] Cleared file: {file_path}")

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

    print(f"[CLEARED]'{filename}.log' has been emptied.")

