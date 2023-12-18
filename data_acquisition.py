#data_aquisition.py
import requests
import pandas as pd
import numpy as np
from error_handler import error_log_and_discord_message
import websockets
from websockets.exceptions import InvalidStatusCode, ConnectionClosedError
import asyncio
import cred
import json
import pytz
from datetime import datetime

RETRY_INTERVAL = 1  # Seconds between reconnection attempts
should_close = False  # Global variable to signal if the WebSocket should close

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
                print("[Hr:Min:Sec]")

                async for message in websocket:
                    if should_close:
                        print("Closing WebSocket connection.")
                        await websocket.close()
                        return

                    await queue.put(message)

        except websockets.ConnectionClosed:
            print("WebSocket connection closed. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

        except Exception as e:
            await error_log_and_discord_message(e, "data_acquisition", "ws_connect", "An error occurred. Re-establishing connection...")
            await asyncio.sleep(RETRY_INTERVAL)  # Wait before retrying

def get_session_id():
    url = "https://api.tradier.com/v1/markets/events/session"
    
    headers = {
        "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
        "Accept": "application/json"
    }
    
    response = requests.post(url, data={}, headers=headers)
    if response.status_code == 200:
        return response.json()["stream"]["sessionid"]
    else:
        print(f"Error: Unable to get session ID: {response.text}")
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
        print(url)
        #print(f"{interval} {timescale} Raw JSON Response:", data)

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


