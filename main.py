#main.py
from chart_visualization import plot_candles_and_boxes, initiate_shutdown, update_15_min, setup_global_boxes
from data_acquisition import get_candle_data, get_dates, reset_json, active_provider, initialize_order_log
from tll_trading_strategy import execute_trading_strategy
from buy_option import message_ids_dict, used_buying_power
from ema_strategy import execute_200ema_strategy
from economic_calender_scraper import get_economic_calendar_data, setup_economic_news_message
from print_discord_messages import bot, print_discord, get_message_content, send_file_discord
from error_handler import error_log_and_discord_message, print_log
import data_acquisition
import chart_visualization
import asyncio
from datetime import datetime, timedelta
import pandas as pd
import threading
import boxes
import cred
import json
import pytz
import re
import glob
import os
from pathlib import Path

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)

websocket_connection = None  # Initialize websocket_connection at the top level

ONE_HOUR = 3600
ONE_MINUTE = 60

config_path = Path(__file__).resolve().parent / 'config.json'#
def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config

config = read_config()
SYMBOL = config["SYMBOL"]
DAYS = config["PAST_DAYS"]
TIMEFRAMES = config["TIMEFRAMES"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
ACCOUNT_BALANCE = config["ACCOUNT_BALANCES"]
CANDLE_BUFFER = config["CANDLE_BUFFER"]
GET_PDHL = config["GET_PDHL"]
CANDLE_DURATION = {}

timeframe_mapping = {
    "1M": 1 * ONE_MINUTE,
    "2M": 2 * ONE_MINUTE,
    "3M": 3 * ONE_MINUTE,
    "5M": 5 * ONE_MINUTE,
    "15M": 15 * ONE_MINUTE,
    "30M": 30 * ONE_MINUTE,
    "1H": 1 * ONE_HOUR
}

for timeframe in TIMEFRAMES:
    if timeframe in timeframe_mapping:
        CANDLE_DURATION[timeframe] = timeframe_mapping[timeframe]
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

# Define New York timezone
new_york_tz = pytz.timezone('America/New_York')

LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def write_to_log(data, symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    with filepath.open("a") as file:
        json_data = json.dumps(data)
        file.write(json_data + "\n")

def clear_log(symbol=None, timeframe=None, terminal_log=None):
    filepath = None
    if symbol and timeframe:
        filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    if terminal_log:
        filepath = LOGS_DIR / terminal_log
    if filepath.exists():
        filepath.unlink() 

def read_log_file(log_file_path):
    try:
        with open(log_file_path, 'r') as file:
            return file.read()
    except FileNotFoundError:
        print_log(f"File {log_file_path} not found.")
        return ""

def write_log_data_as_string(data, symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    with filepath.open("a") as file:
        file.write(data + "\n")

current_candle = {
    "open": None,
    "high": None,
    "low": None,
    "close": None
}

current_candles = {tf: {"open": None, "high": None, "low": None, "close": None} for tf in TIMEFRAMES}
start_times = {tf: datetime.now() for tf in TIMEFRAMES}
candle_counts = {tf: 0 for tf in TIMEFRAMES}

def to_float(value):
    if isinstance(value, str):
        return float(value.replace("$", "").replace(",", ""))
    elif isinstance(value, (float, int)):
        return float(value)
    else:
        raise ValueError("Value must be a string or a number")

def extract_trade_results(message, message_id):
    # Clean up the message to remove unwanted characters
    clean_message = ''.join(e for e in message if (e.isalnum() or e.isspace() or e in ['$', '%',  '.', ':', '-', '✅', '❌']))
    #print(f"clean_message: {clean_message}")

    # Pattern to extract total investment (using the previous pattern)
    investment_pattern = r"Total Investment: \$(.+)"
    investment_match = re.search(investment_pattern, clean_message)
    total_investment = float(investment_match.group(1).replace(",", "")) if investment_match else 0.0
    #print(f"total_investment: {total_investment}")

    # TODO: DEBUG STARTS HERE
    """
    # Start with just AVG BID
    avg_bid_pattern = r"AVG BID:\s*\$([\d,]+\.\d{3})"
    avg_bid_match = re.search(avg_bid_pattern, clean_message)
    print(f"avg_bid_match: {avg_bid_match}")

    # Then add TOTAL
    total_pattern = r"TOTAL:\s*(-?\$\-?[\d,]+\.\d{2})"
    total_match = re.search(total_pattern, clean_message)
    print(f"total_match: {total_match}")

    # Then add INDICATOR
    indicator_pattern = r"(✅|❌)"
    indicator_match = re.search(indicator_pattern, clean_message)
    print(f"indicator_match: {indicator_match}")

    # Then add PERCENT
    percent_pattern = r"PERCENT:\s*(-?\d+\.\d{2})%"
    percent_match = re.search(percent_pattern, clean_message)
    print(f"percent_match: {percent_match}")
    """
    # TODO: DEBUG ENDS HERE
    
    # Pattern to extract the average bid, total profit/loss, profit indicator, and percentage gain/loss
    results_pattern = r"AVG BID:\s*\$([\d,]+\.\d{3})\s*TOTAL:\s*(-?\$\-?[\d,]+\.\d{2})\s*(✅|❌)\s*PERCENT:\s*(-?\d+\.\d{2})%"
    results_match = re.search(results_pattern, clean_message, re.DOTALL)
    #print(f"results_match: {results_match}")
    if results_match:
        avg_bid = float(results_match.group(1))
        
        # Handle 'total' value
        total_str = results_match.group(2).replace(",", "").replace("$", "")
        total = float(total_str) if total_str else 0.0
        
        profit_indicator = results_match.group(3)  # Capture ✅ or ❌
        percent = float(results_match.group(4))  # Capture the percentage
        
        return {
            "avg_bid": avg_bid,
            "total": total,
            "profit_indicator": profit_indicator,
            "percent": percent,
            "total_investment": total_investment
        }
    else:
        return f"Invalid Results Details for message ID {message_id}"

async def calculate_day_performance(message_ids_dict, start_balance_str, end_balance_str):
    trades_str_list = []
    BP_float_list = []
    for message_id in message_ids_dict.values():
        #print(f"\n\nmessage_id: {message_id}")
        message_content = await get_message_content(message_id)
        if message_content:
            #print(f"    Message content true, content:\n{message_content}")
            trade_info_dict = extract_trade_results(message_content, message_id)
            #print(f"    trade info = {trade_info_dict}")
            if isinstance(trade_info_dict, str) and "Invalid" in trade_info_dict:
                continue
            
            trade_info_str = f"${trade_info_dict['total']:.2f}, {trade_info_dict['percent']:.2f}%{trade_info_dict['profit_indicator']}"
            trades_str_list.append(trade_info_str)
            BP_float_list.append(trade_info_dict['total_investment'])

    total_bp_used_today = sum(BP_float_list)
    trades_str = '\n'.join(trades_str_list)
    start_balance = to_float(start_balance_str)
    end_balance = to_float(end_balance_str)
    profit_loss = end_balance - start_balance
    percent_gl = (profit_loss / start_balance) * 100

    output_msg = f"""
All Trades:
{trades_str}

Total BP Used Today:
${total_bp_used_today:,.2f}

Account balance:
Start: ${"{:,.2f}".format(start_balance_str)}
End: ${"{:,.2f}".format(end_balance_str)}

Profit/Loss: ${profit_loss:,.2f}
Percent Gain/Loss: {percent_gl:.2f}%
"""
    return output_msg

def generate_candlestick_times(start_time, end_time, interval):
    new_york_tz = pytz.timezone('America/New_York')
    start = new_york_tz.localize(datetime.combine(datetime.today(), start_time.time()))
    end = new_york_tz.localize(datetime.combine(datetime.today(), end_time.time()))
    times = []
    while start <= end:
        times.append(start)
        start += interval
    return times

def add_seconds_to_time(time_str, seconds):
    time_obj = datetime.strptime(time_str, '%H:%M:%S')
    new_time_obj = time_obj + timedelta(seconds=seconds)
    return new_time_obj.strftime('%H:%M:%S')

def load_from_csv(filename):
    try:
        df = pd.read_csv(filename)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except FileNotFoundError:
        print_log(f"File {filename} not found.")
        return None
    except Exception as e:
        print_log(f"An error occurred while loading {filename}: {e}")
        return None



async def process_data(queue):
    print_log("Starting process_data()...")
    global current_candles, candle_counts
    
    # Define initial timestamps for the first day
    current_day = datetime.now(new_york_tz).date()
    market_open_time = datetime.now(new_york_tz).replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_time = datetime.now(new_york_tz).replace(hour=16, minute=0, second=0, microsecond=0)
    
    timestamps = {tf: [t.strftime('%H:%M:%S') for t in generate_candlestick_times(market_open_time, market_close_time, timedelta(seconds=CANDLE_DURATION[tf]))] for tf in TIMEFRAMES}
    buffer_timestamps = {tf: [add_seconds_to_time(t, CANDLE_BUFFER) for t in timestamps[tf]] for tf in timestamps}
    
    try:
        while True:
            now = datetime.now(new_york_tz)
            f_now = now.strftime('%H:%M:%S')

            # Check if the day has changed
            if now.date() != current_day:
                print_log("[INFO] Detected day change. Recalculating timestamps...")
                current_day = now.date()
                market_open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
                market_close_time = now.replace(hour=16, minute=0, second=0, microsecond=0)

                # Recalculate timestamps for the new day
                timestamps = {tf: [t.strftime('%H:%M:%S') for t in generate_candlestick_times(market_open_time, market_close_time, timedelta(seconds=CANDLE_DURATION[tf]))] for tf in TIMEFRAMES}
                buffer_timestamps = {tf: [add_seconds_to_time(t, CANDLE_BUFFER) for t in timestamps[tf]] for tf in timestamps}

                # Reset the candles for the new day
                current_candles = {tf: {"open": None, "high": None, "low": None, "close": None} for tf in TIMEFRAMES}
                candle_counts = {tf: 0 for tf in TIMEFRAMES}
            
            if now >= market_close_time:
                print_log("Ending process_data()...")
                break

            message = await queue.get()
            data = json.loads(message)

            if 'type' in data and data['type'] == 'trade':
                price = float(data.get("price", 0))

                for timeframe in TIMEFRAMES:
                    current_candle = current_candles[timeframe]
                    if current_candle["open"] is None:
                        current_candle["open"] = price
                        current_candle["high"] = price
                        current_candle["low"] = price

                    current_candle["high"] = max(current_candle["high"], price)
                    current_candle["low"] = min(current_candle["low"], price)
                    current_candle["close"] = price

                    if (f_now in timestamps[timeframe]) or (f_now in buffer_timestamps[timeframe]):
                        current_candle["timestamp"] = datetime.now().isoformat()
                        write_to_log(current_candle, SYMBOL, timeframe)
                        
                        # Reset the current candle and start time
                        current_candles[timeframe] = {
                            "open": None,
                            "high": None,
                            "low": None,
                            "close": None
                        }
                        
                        f_current_time = datetime.now().strftime("%H:%M:%S")
                        candle_counts[timeframe] += 1
                        print_log(f"[{f_current_time}] Candle count for {timeframe}: {candle_counts[timeframe]}")
                        
                        # Remove the timestamp to avoid duplication
                        if f_now in timestamps[timeframe]:
                            timestamps[timeframe].remove(f_now)
                            buffer_timestamps[timeframe].remove(add_seconds_to_time(f_now, CANDLE_BUFFER)) #add CANDLE_BUFFER to f_now and remove it from the buffer_timestamps list.
                        elif f_now in buffer_timestamps[timeframe]:
                            buffer_timestamps[timeframe].remove(f_now)
                            timestamps[timeframe].remove(add_seconds_to_time(f_now, -CANDLE_BUFFER)) #subtract CANDLE_BUFFER from f_now and remove it from the timestamps list.

        queue.task_done()

    except Exception as e:
        await error_log_and_discord_message(e, "main", "process_data")

async def ensure_economic_calendar_data():
    json_file = 'week_ecom_calender.json'
    
    # Check if the JSON file exists
    if not os.path.exists(json_file):
        await get_economic_calendar_data("week", 3, "america")
        return

    # Read the JSON data
    with open(json_file, 'r') as file:
        data = json.load(file)

    # Extract week_timespan
    week_timespan = data.get('week_timespan', "")
    if not week_timespan:
        await get_economic_calendar_data("week", 3, "america")
        return

    # Parse the week_timespan
    try:
        start_date_str, end_date_str = week_timespan.split(" to ")
        start_date = datetime.strptime(start_date_str, '%m-%d-%y')
        end_date = datetime.strptime(end_date_str, '%m-%d-%y')
    except ValueError:
        await get_economic_calendar_data("week", 3, "america")
        return

    # Get today's date
    today_date = datetime.now()

    # Check if today's date is within the week_timespan
    if not (start_date <= today_date <= end_date):
        await get_economic_calendar_data("week", 3, "america")

async def initial_setup():
    global websocket_connection
    global start_of_day_account_balance
    global end_of_day_account_balance

    await bot.wait_until_ready()
    print_log(f"We have logged in as {bot.user}")
    await print_discord(f"Starting Bot, Real Money Activated" if IS_REAL_MONEY else f"Starting Bot, Paper Trading Activated")

#async def main(): Keeping this just incase
    #await initial_setup()
    #await main_loop()

async def main():
    new_york = pytz.timezone('America/New_York')
    last_run_date = None  # To track the last date the functions ran
    last_weekend_message_date = None  # To track the last weekend message date

    while True:
        try:
            # Get the current time in New York timezone
            current_time = datetime.now(new_york)
            current_date = current_time.date()  # Extract the date (e.g., 2024-06-12)

            # Debug: Print current time and date
            #print(f"[DEBUG] Current time: {current_time.strftime('%Y-%m-%d %H:%M:%S')} (New York Time)")
            #print(f"[DEBUG] Last run date: {last_run_date}, Today's date: {current_date}")

            # Check if today is Monday to Friday
            if current_time.weekday() in range(0, 5):  # 0=Monday, 4=Friday
                # Set target time to 9:20 AM New York time
                target_time = new_york.localize(
                    datetime.combine(current_time.date(), datetime.strptime("09:20:00", "%H:%M:%S").time())
                )

                # Check if it's time to run and hasn't already run today
                if current_time >= target_time and last_run_date != current_date:
                    print_log(f"[INFO] Running initial_setup and main_loop at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    await initial_setup()  # Run the initial setup
                    await main_loop()      # Run the main loop
                    last_run_date = current_date  # Update the last run date

                    print_log("[INFO] initial_setup and main_loop completed successfully.")
                    print_log("Waiting until tomorrow's 8:20 AM...")

                # Debug: If already ran today
                #elif last_run_date == current_date:
                    #print(f"[DEBUG] Already ran today at {current_date}. Waiting for tomorrow.")

            else:
                # It's a weekend
                if last_weekend_message_date != current_date:
                    print_log(f"[INFO] Today is {current_time.strftime('%A')}. Market is closed. Waiting for Monday...")
                    last_weekend_message_date = current_date  # Update the last weekend message date

            # Sleep for 10 seconds before checking again
            await asyncio.sleep(10)

        except Exception as e:
            print_log(f"[ERROR] Exception in main loop: {e}")
            await asyncio.sleep(10)  # Avoid tight loops in case of errors


async def main_loop():
    global websocket_connection
    global start_of_day_account_balance
    global end_of_day_account_balance

    queue = asyncio.Queue()
    already_ran = False
    # Process the data to get zones and lines
    Boxes = None
    tp_lines = None
    keep_loop = True
    while keep_loop:
        try:
            new_york = pytz.timezone('America/New_York')
            current_time = datetime.now(new_york)
            market_open_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("09:30:00", "%H:%M:%S").time()))
            market_close_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("16:00:00", "%H:%M:%S").time()))
            
            # Ensure the order log is initialized before using it
            initialize_order_log('order_log.csv')
            
            # 2 mins before market opens
            if ((current_time < market_open_time) or (current_time < market_close_time)) and not already_ran:
                await ensure_economic_calendar_data()

                start_date, end_date = get_dates(DAYS)
                print_log(f"15m) Start and End days: \n{start_date}, {end_date}\n")

                candle_15m_data = load_from_csv(f"{SYMBOL}_15_minute_candles.csv")
                if candle_15m_data is None:
                    candle_15m_data = await get_candle_data(cred.POLYGON_API_KEY, SYMBOL, 15, "minute", start_date, end_date)

                candle_15m_data['date'] = candle_15m_data['timestamp'].dt.date
                days = candle_15m_data['date'].unique()
                days = days[::-1]  # Reverse the order of days to start with the most recent date
                num_days = min(DAYS, len(days))
                
                if candle_15m_data is not None and 'timestamp' in candle_15m_data.columns:
                    prev_days_data = pd.DataFrame()  # Initialize prev_days_data to an empty DataFrame
                    
                    # Plot the data
                    chart_thread = threading.Thread(target=plot_candles_and_boxes, args=(candle_15m_data, SYMBOL))
                    chart_thread.start()
                    await asyncio.sleep(1) # wait for the thread

                    for day_num in range(num_days):
                        current_date = days[day_num]
                        day_data = candle_15m_data[candle_15m_data['date'] == current_date]
                        print_log(f"[Day {day_num + 1} of {num_days}] {current_date}")
                        #print(f"    [LENGTH DAY DATA] {len(day_data)}")
                        df_15m = pd.concat([day_data, prev_days_data])
                        Boxes, tp_lines = boxes.get_v2(Boxes, tp_lines, df_15m, current_date, len(day_data), GET_PDHL)
                        Boxes = boxes.correct_zones_inside_other_zones(Boxes)
                        Boxes, tp_lines = boxes.correct_bleeding_zones(Boxes, tp_lines)
                        Boxes, tp_lines = boxes.correct_zones_that_are_too_close(Boxes, tp_lines)
                        prev_days_data = df_15m
                        #await asyncio.sleep(.25)
                    print_log(" ") # space at the end of console log for visual clarity
                    setup_global_boxes(Boxes, tp_lines)
                    update_15_min()
                    
                    already_ran = True

                    # Save boxes into log file for later use
                    boxes_info = f"15m) Start and End days: {start_date}, {end_date}\n{Boxes}\n\nTake Profit Lines: {tp_lines}\n"
                    write_log_data_as_string(boxes_info, SYMBOL, f"{TIMEFRAMES[0]}_Boxes")

                elif candle_15m_data is None or candle_15m_data.empty or 'timestamp' not in candle_15m_data.columns:
                    print_log(f"    [ERROR] Error loading or invalid data in {SYMBOL}_15_minute_candles.csv")
                else:
                    print_log("    [ERROR] No candle data was retrieved or 'timestamp' column is missing.")
            
            if market_open_time <= current_time <= market_close_time:
                if websocket_connection is None:  # Start WebSocket connection
                    data_acquisition.should_close = False
                    chart_visualization.should_close = False
                    
                    # Start the WebSocket connection for the active provider
                    asyncio.create_task(data_acquisition.ws_connect_v2(queue, active_provider, SYMBOL), name="WebsocketConnection")  # Start in the background
                    websocket_connection = True

                    # Initialize account balance and log
                    if IS_REAL_MONEY:
                        start_of_day_account_balance = await data_acquisition.get_account_balance(IS_REAL_MONEY)
                    else:
                        start_of_day_account_balance = ACCOUNT_BALANCE[0] #0 IS START OF DAY BALANCE
                    end_of_day_account_balance = 0
                    f_s_account_balance = "{:,.2f}".format(start_of_day_account_balance)
                    await print_discord(f"Market is Open! Account BP: ${f_s_account_balance}")

                    # Send 2-min chart picture to Discord
                    pic_15m_filepath = Path(__file__).resolve().parent / f"{SYMBOL}_15-min_chart.png"
                    await send_file_discord(pic_15m_filepath)

                    await print_discord(setup_economic_news_message())
                await asyncio.gather(
                    process_data(queue),
                    execute_trading_strategy(Boxes) # Strategy starts
                )
            else:
                if websocket_connection is not None:
                    data_acquisition.should_close = True  # Signal to close WebSocket
                    await reseting_values()
                    chart_visualization.should_close = True
                    already_ran = False
                    keep_loop = False
                if current_time <= market_open_time:
                    # Calculate the seconds until the market opens
                    delta_until_open = (market_open_time - current_time).total_seconds()
                    print_log(f"The market is about to open. Waiting {int(delta_until_open)} seconds...")
                    await asyncio.sleep(delta_until_open)
                elif market_close_time <= current_time:
                    print_log("The market is closed...")
                    break
        except Exception as e:
            await error_log_and_discord_message(e, "main", "main")

def get_correct_message_ids(_message_ids_dict):
    # Load `message_ids.json` from the file
    json_file_path = 'message_ids.json'
    if os.path.exists(json_file_path):
        with open(json_file_path, 'r') as file:
            json_message_ids_dict = json.load(file)
            #print (f"{json_message_ids_dict}")
    else:
        json_message_ids_dict = {}

    # Check if `message_ids_dict` is empty or if `json_message_ids_dict` has more information
    if not _message_ids_dict or len(json_message_ids_dict) >= len(_message_ids_dict):
        _message_ids_dict = json_message_ids_dict
    
    return _message_ids_dict

async def reseting_values():
    global websocket_connection
    global start_of_day_account_balance
    global end_of_day_account_balance
    global message_ids_dict
    global used_buying_power

    websocket_connection = None
    if IS_REAL_MONEY:
        end_of_day_account_balance = await data_acquisition.get_account_balance(IS_REAL_MONEY)
    else:
        with open(config_path, 'r') as f:
            config = json.load(f)
        end_of_day_account_balance = config["ACCOUNT_BALANCES"][1]
    f_e_account_balance = "{:,.2f}".format(end_of_day_account_balance)
    await print_discord(f"Market is closed. Today's closing balance: ${f_e_account_balance}")
    #send 2-min chart picture to discord chat
    pic_2m_filepath = Path(__file__).resolve().parent / f"{SYMBOL}_2-min_chart.png"
    await send_file_discord(pic_2m_filepath)

    message_ids_dict = get_correct_message_ids(message_ids_dict)

    #Calculate/Send todays results, use the 'message_ids_dict' from ema_strategy.py
    # TODO: the ouput_message was incorrect, fix it
    output_message = await calculate_day_performance(message_ids_dict, start_of_day_account_balance, end_of_day_account_balance)
    await print_discord(output_message)
    #reset all values
    used_buying_power.clear()
    print_log("[RESET] Cleared 'used_buying_power' list.")

    #save new data in dicord, send log files
    whole_log = read_log_file(LOGS_DIR / f"{SYMBOL}_{TIMEFRAMES[0]}.log")
    write_log_data_as_string(whole_log, SYMBOL, f"{TIMEFRAMES[0]}_Boxes")
    new_log_file_path = LOGS_DIR / f"{SYMBOL}_{TIMEFRAMES[0]}_Boxes.log"
    await send_file_discord(new_log_file_path) #Send file
    await send_file_discord('EMAs.json')
    await send_file_discord('markers.json')
    terminal_log_file_path = LOGS_DIR / "terminal_output.log"
    await send_file_discord(terminal_log_file_path)

    #clear 'message_ids.json' file
    reset_json('message_ids.json', {})
    #Clear the markers.json file
    reset_json('markers.json', [])
    #clear line_data_TEST.json
    reset_json('line_data.json', [])
    #clear order_candle_type.json
    reset_json('order_candle_type.json', [])
    #clear priority_candles.json
    reset_json('priority_candles.json', [])
    #clear EMAs.json
    reset_json('EMAs.json', [])
              
    #edit, maybe we can fix this by doing 
    #since all the logging has been done and everything is recorded
    with open(config_path, 'r') as f:
        config = json.load(f)
    #after all the calculations were done, make the start of day value the end of day value for a clean start for tommorrow
    config["ACCOUNT_BALANCES"][0] = end_of_day_account_balance 
    config["ACCOUNT_BALANCES"][1] = 0
    with open(config_path, 'w') as f:
        print_log(f"[RESET] Updated file: config.json")
        json.dump(config, f, indent=4)  # Save the updated config
    start_of_day_account_balance = end_of_day_account_balance
    end_of_day_account_balance = 0

    #delete all the data from the csv files
    #find all CSV files in directory
    csv_files = Path(__file__).resolve().parent.glob('*.csv')
    for file in csv_files:
        if file.name != 'order_log.csv':
            print_log(f"[RESET] Deleting File: {file.name}")
            file.unlink()  # Delete the file

    #clear the Logs, logs/[ticker_symbol]_2M.log file. Don't delete it just clear it.
    clear_log(SYMBOL, "2M")
    clear_log(SYMBOL, "2M_Boxes")
    clear_log(None, None, "terminal_output.log")

    # Find all the files that have 'order_log' in them and delete them
    order_log_files = glob.glob('./*order_log*')

    for file in order_log_files:
        try:
            if os.path.basename(file) != 'order_log.csv':
                os.remove(file)
                print_log(f"[RESET] Order log file {file} deleted.")
        except Exception as e:
            print_log(f"An error occurred while deleting {file}: {e}")

async def shutdown(loop, root=None):
    """Shutdown tasks and the Discord bot."""
    # Gracefully shutdown the Discord bot
    await bot.close()  # Make sure this is the correct way to close your bot instance
    # Cancel all remaining tasks
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task(loop)]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    initiate_shutdown()

    loop.stop()

if __name__ == "__main__":

    loop = asyncio.get_event_loop()
    loop.create_task(bot_start())
    loop.create_task(main())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print_log("Manually interrupted, cleaning up...")
        loop.run_until_complete(shutdown(loop))
    finally:
        loop.close()