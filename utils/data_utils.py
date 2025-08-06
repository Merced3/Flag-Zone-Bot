# utils/data_utils.py, DataFrame loading/saving
import pandas as pd
import math
from shared_state import print_log, indent, safe_read_json
import pandas_market_calendars as mcal
from datetime import datetime, timedelta
from paths import pretty_path, LINE_DATA_PATH

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
