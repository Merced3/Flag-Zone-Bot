# utils/data_utils.py, DataFrame loading/saving
import pandas as pd
import os
import json
import math
from shared_state import print_log, indent, safe_read_json
import pandas_market_calendars as mcal
from datetime import datetime, timedelta
from utils.json_utils import read_config, update_ema_json
from paths import pretty_path, EMAS_PATH, CANDLE_LOGS, LINE_DATA_PATH, MERGED_EMA_PATH

def load_from_csv(filename):
    try:
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except FileNotFoundError:
        print_log(f"File `{pretty_path(filename)}` not found.")
        return None
    except Exception as e:
        print_log(f"An error occurred while loading `{pretty_path(filename)}`: {e}")
        return None

def save_to_csv(df, filename):
    df.to_csv(filename, index=False)

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

def get_dates(num_of_days, use_todays_date=False, use_specific_start_date=None):
    nyse = mcal.get_calendar('NYSE')

    # If using today's date, else use yesterday's date or Friday's date if today is a weekend
    if use_todays_date:
        start = datetime.today()
    elif use_specific_start_date:
        start = datetime.strptime(use_specific_start_date, '%Y-%m-%d')
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

async def calculate_save_EMAs(candle, X_value):
    """
    Process a single candle: Adds it to CSV, Recalculate EMAs, Saves EMAs to JSON file.
    """
    required_columns = ['timestamp', 'open', 'high', 'low', 'close']

    # Load or init
    try:
        df = pd.read_csv(MERGED_EMA_PATH)
        df = df[required_columns] if not df.empty else pd.DataFrame(columns=required_columns)
    except FileNotFoundError:
        df = pd.DataFrame(columns=required_columns)

    # Fix candle
    candle_df = pd.DataFrame([candle])
    for col in required_columns:
        if col not in candle_df.columns:
            candle_df[col] = pd.Timestamp.now().isoformat() if col == 'timestamp' else 0.0

    candle_df = candle_df[required_columns]  # Ensure correct column order

    # Concat only if valid
    if not candle_df.empty:
        df = pd.concat([df, candle_df], ignore_index=True)
    df.to_csv(MERGED_EMA_PATH, mode='w', header=True, index=False)

    # EMAs
    current_ema_values = {}
    for window, _ in read_config('EMAS'):  # window, color
        ema_col = f"EMA_{window}"
        df[ema_col] = df['close'].ewm(span=window, adjust=False).mean()
        current_ema_values[str(window)] = df[ema_col].iloc[-1]

    current_ema_values['x'] = X_value
    update_ema_json(EMAS_PATH, current_ema_values)

def get_latest_ema_values(ema_type):
    # ema_type must be a string, Ex: "13" or "48", "200" ect...
    ema_type = str(ema_type)

    # Check if the file is empty before reading
    if os.stat(EMAS_PATH).st_size == 0:
        print_log(f"    [GLEV] `{pretty_path(EMAS_PATH)}` is empty.")
        return None, None

    try:
        # Read the EMA data from the JSON file
        with open(EMAS_PATH, "r") as file:
            emas = json.load(file)

        if not emas:  # Check if the file is empty or contains no data
            print_log(f"    [GLEV] `{pretty_path(EMAS_PATH)}` is empty or contains no data.")
            return None, None
        latest_ema = emas[-1][ema_type]
        #print(f"Latest emas: {latest_ema}")
        index_ema = emas[-1]['x']

        return latest_ema, index_ema
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        print_log(f"    [GLEV] EMA error: {e}")
        return None, None

def is_ema_broke(ema_type, timeframe, cp):
    # Get EMA Data
    latest_ema, index_ema = get_latest_ema_values(ema_type)
    if latest_ema is None or index_ema is None:
        return False
    
    # Get Candle Data
    filepath = CANDLE_LOGS.get(timeframe)
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
         
def check_valid_points(indent_lvl, line_name, line_type, print_statements=True):
    default_structure = {
        "active_flags": [],
        "completed_flags": []
    }

    line_data = safe_read_json(LINE_DATA_PATH, default=default_structure, indent_lvl=indent_lvl+1)
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
