#main.py
from chart_visualization import plot_candles_and_boxes, initiate_shutdown
from data_acquisition import get_candle_data, get_dates, reset_json
from tll_trading_strategy import execute_trading_strategy
from buy_option import message_ids_dict, used_buying_power
from ema_strategy import execute_200ema_strategy
from print_discord_messages import bot, print_discord, get_message_content, send_file_discord
from error_handler import error_log_and_discord_message
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

# Define market open and close times (assuming 9:30 AM to 4:00 PM New York Time)
MARKET_OPEN_TIME = datetime.now(new_york_tz).replace(hour=9, minute=30, second=0, microsecond=0)
MARKET_CLOSE_TIME = datetime.now(new_york_tz).replace(hour=16, minute=0, second=0, microsecond=0)

LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def write_to_log(data, symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    with filepath.open("a") as file:
        json_data = json.dumps(data)
        file.write(json_data + "\n")

def clear_log(symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    if filepath.exists():
        filepath.unlink() 

def read_log_file(log_file_path):
    try:
        with open(log_file_path, 'r') as file:
            return file.read()
    except FileNotFoundError:
        print(f"File {log_file_path} not found.")
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
    clean_message = ''.join(e for e in message if (e.isalnum() or e.isspace() or e in ['$', '.', ':', '-']))
    investment_pattern = r"Total Investment: \$(.+)"
    investment_match = re.search(investment_pattern, clean_message)
    total_investment = float(investment_match.group(1).replace(",", "")) if investment_match else 0.0

    results_pattern = r"AVG BID:.*?(-?\d{1,3}(?:,\d{3})*\.\d{2}).*?TOTAL:.*?(-?\d{1,3}(?:,\d{3})*\.\d{2})(✅|❌).*?PERCENT:.*?(-?\d+\.\d+)%"
    results_match = re.search(results_pattern, message, re.DOTALL)
    if results_match:
        avg_bid = float(results_match.group(1))
        total = float(results_match.group(2))
        profit_indicator = results_match.group(3)
        percent = float(results_match.group(4))
        
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
        message_content = await get_message_content(message_id)
        if message_content:
            trade_info_dict = extract_trade_results(message_content, message_id)
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
        print(f"File {filename} not found.")
        return None
    except Exception as e:
        print(f"An error occurred while loading {filename}: {e}")
        return None



async def process_data(queue):
    print("Starting process_data()...")
    global current_candles, candle_counts
    timestamps = {tf: [t.strftime('%H:%M:%S') for t in generate_candlestick_times(MARKET_OPEN_TIME, MARKET_CLOSE_TIME, timedelta(seconds=CANDLE_DURATION[tf]))] for tf in TIMEFRAMES}
    buffer_timestamps = {tf: [add_seconds_to_time(t, CANDLE_BUFFER) for t in timestamps[tf]] for tf in timestamps}
    
    try:
        while True:
            now = datetime.now(new_york_tz)
            f_now = now.strftime('%H:%M:%S')
            if now >= MARKET_CLOSE_TIME:
                print("Ending process_data()...")
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
                        print(f"[{f_current_time}] Candle count for {timeframe}: {candle_counts[timeframe]}")
                        
                        #remove the timestamp from the list so we don't write to the log again.
                        if f_now in timestamps[timeframe]:
                            timestamps[timeframe].remove(f_now)
                            buffer_timestamps[timeframe].remove(add_seconds_to_time(f_now, CANDLE_BUFFER)) #add CANDLE_BUFFER to f_now and remove it from the buffer_timestamps list.
                        else: #f_now in buffer_timestamps[timeframe]
                            buffer_timestamps[timeframe].remove(f_now)
                            timestamps[timeframe].remove(add_seconds_to_time(f_now, -CANDLE_BUFFER)) #subtract CANDLE_BUFFER from f_now and remove it from the timestamps list.

        queue.task_done()

    except Exception as e:
        await error_log_and_discord_message(e, "main", "process_data")

async def main():
    print("Starting main()...")
    global websocket_connection
    global start_of_day_account_balance
    global end_of_day_account_balance

    await bot.wait_until_ready()
    
    print(f"We have logged in as {bot.user}")

    await print_discord(f"Starting Bot, Real Money Activated" if IS_REAL_MONEY else f"Starting Bot, Paper Trading Activated")

    queue = asyncio.Queue()
    already_ran = False

    try:
        while True:
            new_york = pytz.timezone('America/New_York')
            current_time = datetime.now(new_york)
            market_open_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("09:30:00", "%H:%M:%S").time()))
            market_close_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("16:00:00", "%H:%M:%S").time()))

            # 2 mins before market opens, havent implemented this but will soon. its not the highest on the priority list.
            # I want this to run before the wesocket connection starts so that we have the boxes first
            if ((current_time < market_open_time) or (current_time < market_close_time)) and not already_ran:
                start_date, end_date = get_dates(DAYS)
                print(f"15m) Start and End days: \n{start_date}, {end_date}\n")

                candle_15m_data = load_from_csv(f"{SYMBOL}_15_minute_candles.csv")
                if candle_15m_data is None:
                    candle_15m_data = await get_candle_data(cred.POLYGON_API_KEY, SYMBOL, 15, "minute", start_date, end_date)

                start_date_2m, end_date_2m = get_dates(2)
                print(f"2m) Start and End days: \n{start_date_2m}, {end_date_2m}\n")
                
                candle_2m_data = load_from_csv(f"{SYMBOL}_2_minute_candles.csv")
                if candle_2m_data is None:
                    candle_2m_data = await get_candle_data(cred.POLYGON_API_KEY, SYMBOL, 2, "minute", start_date_2m, end_date_2m)

                if candle_15m_data is not None and 'timestamp' in candle_15m_data.columns:
                    Boxes = boxes.get(candle_15m_data, DAYS)
                    chart_thread = threading.Thread(target=plot_candles_and_boxes, args=(candle_15m_data, candle_2m_data, Boxes, SYMBOL))
                    chart_thread.start()
                    already_ran = True
                    #save boxes into log file for later use
                    boxes_info = f"15m) Start and End days: {start_date}, {end_date}\n{Boxes}\n"
                    write_log_data_as_string(boxes_info, SYMBOL, f"{TIMEFRAMES[0]}_Boxes")

                elif candle_15m_data is None or candle_15m_data.empty or 'timestamp' not in candle_15m_data.columns:
                    print(f"    [ERROR] Error loading or invalid data in {SYMBOL}_15_minute_candles.csv")
                else:
                    print("    [ERROR] No candle data was retrieved or 'timestamp' column is missing.")
            
            if market_open_time <= current_time <= market_close_time:
                if websocket_connection is None:  # Only create a new connection if there isn't one
                    data_acquisition.should_close = False
                    chart_visualization.should_close = False
                    asyncio.create_task(data_acquisition.ws_connect(queue, SYMBOL))  # Start in the background
                    websocket_connection = True

                    # Print that market has opened and account balance
                    if IS_REAL_MONEY:
                        start_of_day_account_balance = await data_acquisition.get_account_balance(IS_REAL_MONEY)
                    else:
                        start_of_day_account_balance = ACCOUNT_BALANCE[0] #0 IS START OF DAY BALANCE
                    end_of_day_account_balance = 0
                    f_s_account_balance = "{:,.2f}".format(start_of_day_account_balance)
                    await print_discord(f"Market is Open! Account BP: ${f_s_account_balance}")

                    #send 2-min chart picture to discord chat
                    pic_15m_filepath = Path(__file__).resolve().parent / f"{SYMBOL}_15-min_chart.png"
                    await send_file_discord(pic_15m_filepath)

                await asyncio.gather(
                    process_data(queue),
                    execute_trading_strategy(Boxes),
                    #execute_200ema_strategy()
                )
            else:
                
                print("The market is closed...")
                if websocket_connection is not None:
                    data_acquisition.should_close = True  # Signal to close WebSocket
                    await reseting_values()
                    chart_visualization.should_close = True
                    already_ran = False

                if current_time < market_open_time:
                    delta_until_open = market_open_time - current_time
                else:
                    next_day = current_time + timedelta(days=1)
                    next_market_open_time = new_york.localize(datetime.combine(next_day.date(), datetime.strptime("09:30:00", "%H:%M:%S").time()))
                    delta_until_open = next_market_open_time - current_time

                print(f"Sleeping for {delta_until_open.seconds:,} seconds until the market opens.")
                await asyncio.sleep(delta_until_open.seconds)
                

    except Exception as e:
        await error_log_and_discord_message(e, "main", "main")

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

    #Calculate/Send todays results, use the 'message_ids_dict' from ema_strategy.py
    output_message = await calculate_day_performance(message_ids_dict, start_of_day_account_balance, end_of_day_account_balance)
    await print_discord(output_message)
    #reset all values
    used_buying_power.clear()
    print("[RESET] Cleared 'used_buying_power' list.")

    #clear 'message_ids.json' file
    reset_json('message_ids.json', {})
    #Clear the markers.json file
    reset_json('markers.json', {})
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
        print(f"[RESET] Updated file: config.json")
        json.dump(config, f, indent=4)  # Save the updated config
    start_of_day_account_balance = end_of_day_account_balance
    end_of_day_account_balance = 0

    #delete all the data from the csv files
    #find all CSV files in directory
    csv_files = Path(__file__).resolve().parent.glob('*.csv')
    for file in csv_files:
        print(f"[RESET] Deleting File: {file.name}")
        file.unlink()  # Delete the file

    
    #save new data in dicord, send log file, with boxes in the file,
    whole_log = read_log_file(LOGS_DIR / f"{SYMBOL}_{TIMEFRAMES[0]}.log")
    write_log_data_as_string(whole_log, SYMBOL, f"{TIMEFRAMES[0]}_Boxes")
    new_log_file_path = LOGS_DIR / f"{SYMBOL}_{TIMEFRAMES[0]}_Boxes.log"
    await send_file_discord(new_log_file_path) #Send file
    await send_file_discord('EMAs.json')

    #clear the Logs, logs/[ticker_symbol]_2M.log file. Don't delete it just clear it.
    #this deleted the file, but we want to keep the file and just clear it.
    clear_log(SYMBOL, "2M")
    clear_log(SYMBOL, "2M_Boxes")

    # Find all the files that have 'order_log' in them and delete them
    order_log_files = glob.glob('./*order_log*')

    for file in order_log_files:
        try:
            os.remove(file)
            print(f"[RESET] Order log file {file} deleted.")
        except Exception as e:
            print(f"An error occurred while deleting {file}: {e}")

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
        print("Manually interrupted, cleaning up...")
        loop.run_until_complete(shutdown(loop))
    finally:
        loop.close()