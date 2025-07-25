# main.py
from chart_visualization import get_root, initiate_shutdown, plot_candles_and_boxes, refresh_15_min_candle_stick_data
from data_acquisition import ws_auto_connect, get_account_balance, active_provider, is_market_open
from utils.json_utils import read_config, get_correct_message_ids, update_config_value
from utils.log_utils import write_to_log, clear_temp_logs_and_order_files
from utils.order_utils import initialize_csv_order_log
from utils.time_utils import generate_candlestick_times, add_seconds_to_time
from shared_state import price_lock, print_log
import shared_state
import threading
from flag_manager import clear_all_states
from tll_trading_strategy import execute_trading_strategy
from economic_calender_scraper import ensure_economic_calendar_data, setup_economic_news_message
from print_discord_messages import bot, print_discord, send_file_discord, calculate_day_performance
from error_handler import error_log_and_discord_message
from order_handler import get_profit_loss_orders_list, reset_profit_loss_orders_list
import data_acquisition
import asyncio
from datetime import datetime, timedelta
from objects import process_end_of_day_15m_candles
import cred
import json
import pytz
from paths import SPY_15M_CHART_PATH, SPY_2M_CHART_PATH, TERMINAL_LOG, EMAS_PATH, MARKERS_PATH, CANDLE_LOGS

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)

websocket_connection = None  # Initialize websocket_connection at the top level

ONE_HOUR = 3600
ONE_MINUTE = 60

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

for timeframe in read_config('TIMEFRAMES'):
    if timeframe in timeframe_mapping:
        CANDLE_DURATION[timeframe] = timeframe_mapping[timeframe]
    else:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

# Define New York timezone
new_york_tz = pytz.timezone('America/New_York')

current_candle = {
    "open": None,
    "high": None,
    "low": None,
    "close": None
}

current_candles = {tf: {"open": None, "high": None, "low": None, "close": None} for tf in read_config('TIMEFRAMES')}
start_times = {tf: datetime.now() for tf in read_config('TIMEFRAMES')}
candle_counts = {tf: 0 for tf in read_config('TIMEFRAMES')}

async def process_data(queue):
    print_log("Starting `process_data()`...")
    global current_candles, candle_counts, start_times
    
    # Define initial timestamps for the first day
    current_day = datetime.now(new_york_tz).date()
    market_open_time = datetime.now(new_york_tz).replace(hour=9, minute=30, second=0, microsecond=0)
    market_close_time = datetime.now(new_york_tz).replace(hour=16, minute=0, second=0, microsecond=0)
    
    timestamps = {tf: [t.strftime('%H:%M:%S') for t in generate_candlestick_times(market_open_time, market_close_time, timedelta(seconds=CANDLE_DURATION[tf]))] for tf in read_config('TIMEFRAMES')}
    buffer_timestamps = {tf: [add_seconds_to_time(t, read_config('CANDLE_BUFFER')) for t in timestamps[tf]] for tf in timestamps}
    
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
                timestamps = {tf: [t.strftime('%H:%M:%S') for t in generate_candlestick_times(market_open_time, market_close_time, timedelta(seconds=CANDLE_DURATION[tf]))] for tf in read_config('TIMEFRAMES')}
                buffer_timestamps = {tf: [add_seconds_to_time(t, read_config('CANDLE_BUFFER')) for t in timestamps[tf]] for tf in timestamps}

                # Reset the candles for the new day
                current_candles = {tf: {"open": None, "high": None, "low": None, "close": None} for tf in read_config('TIMEFRAMES')}
                candle_counts = {tf: 0 for tf in read_config('TIMEFRAMES')}
                start_times = {tf: now for tf in read_config('TIMEFRAMES')}
            
            if now >= market_close_time:
                print_log("Ending `process_data()`...")
                
                for timeframe in read_config('TIMEFRAMES'):
                    current_candle = current_candles[timeframe]
                    if current_candle["open"] is not None:
                        current_candle["timestamp"] = start_times[timeframe].isoformat()
                        write_to_log(current_candle, read_config('SYMBOL'), timeframe)
                        print_log(f"[FINAL WRITE] Flushed final {timeframe} candle at market close")
                    
                current_candles = {tf: {"open": None, "high": None, "low": None, "close": None} for tf in read_config('TIMEFRAMES')}
                candle_counts = {tf: 0 for tf in read_config('TIMEFRAMES')} # Reset candle counts for the next day
                async with price_lock:
                    shared_state.latest_price = None  # Reset the latest price
                break

            message = await queue.get()
            data = json.loads(message)

            if 'type' in data and data['type'] == 'trade':
                price = float(data.get("price", 0))

                # Update the shared `latest_price` variable
                async with price_lock:
                    shared_state.latest_price = price  # Update shared_state.latest_price

                for timeframe in read_config('TIMEFRAMES'):
                    current_candle = current_candles[timeframe]
                    if current_candle["open"] is None:
                        current_candle["open"] = price
                        current_candle["high"] = price
                        current_candle["low"] = price
                        start_times[timeframe] = now

                    current_candle["high"] = max(current_candle["high"], price)
                    current_candle["low"] = min(current_candle["low"], price)
                    current_candle["close"] = price

                    if (f_now in timestamps[timeframe]) or (f_now in buffer_timestamps[timeframe]):
                        current_candle["timestamp"] = start_times[timeframe].isoformat()
                        write_to_log(current_candle, read_config('SYMBOL'), timeframe)
                        
                        # Reset the current candle and start time
                        current_candles[timeframe] = {
                            "open": None,
                            "high": None,
                            "low": None,
                            "close": None
                        }
                        
                        f_current_time = datetime.now().strftime("%H:%M:%S")
                        candle_counts[timeframe] += 1
                        print_log(f"[{f_current_time}] Candle count for {timeframe}: {candle_counts[timeframe]+1}")
                        
                        # Remove the timestamp to avoid duplication
                        if f_now in timestamps[timeframe]:
                            timestamps[timeframe].remove(f_now)
                            buffer_timestamps[timeframe].remove(add_seconds_to_time(f_now, read_config('CANDLE_BUFFER'))) #add CANDLE_BUFFER to f_now and remove it from the buffer_timestamps list.
                        elif f_now in buffer_timestamps[timeframe]:
                            buffer_timestamps[timeframe].remove(f_now)
                            timestamps[timeframe].remove(add_seconds_to_time(f_now, -read_config('CANDLE_BUFFER'))) #subtract CANDLE_BUFFER from f_now and remove it from the timestamps list.

        queue.task_done()

    except Exception as e:
        await error_log_and_discord_message(e, "main", "process_data")

async def initial_setup():
    await bot.wait_until_ready()
    print_log(f"We have logged in as {bot.user}")
    await print_discord(f"Starting Bot, Real Money Activated" if read_config('REAL_MONEY_ACTIVATED') else f"Starting Bot, Paper Trading Activated")

async def main():
    new_york = pytz.timezone('America/New_York')
    last_run_date = None  # To track the last date the functions ran
    last_weekend_message_date = None  # To track the last weekend message date

    while True:
        try:
            # Get the current time in New York timezone
            current_time = datetime.now(new_york)
            current_date = current_time.date()  # Extract the date (e.g., 2024-06-12)

            # Check if today is Monday to Friday
            if current_time.weekday() in range(0, 5):  # 0=Monday, 4=Friday
                # Set target time to 9:20 AM New York time
                target_time = new_york.localize(
                    datetime.combine(current_time.date(), datetime.strptime("09:20:00", "%H:%M:%S").time())
                )

                # Check if it's time to run and hasn't already run today
                if current_time >= target_time and last_run_date != current_date:
                    print_log(f"[INFO] Running initial_setup and main_loop at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    # Run the initial setup
                    await initial_setup()
                    
                    # Run the main loop if markets are open
                    if await is_market_open():
                        await main_loop() 
                    else:
                        print_log(f"Markets are closed today: {current_time.strftime('%m/%d/%Y - %A')}") # "Markets are closed today: 1/1/2025 - Wednesday"
                        await print_discord("**MARKETS ARE CLOSED TODAY**")
                        
                    last_run_date = current_date  # Update the last run date

                    print_log("[INFO] initial_setup and main_loop completed successfully.")
                    print_log("Waiting until tomorrow's 8:20 AM...")

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

    queue = asyncio.Queue()
    already_ran = False
    keep_loop = True

    while keep_loop:
        try:
            new_york = pytz.timezone('America/New_York')
            current_time = datetime.now(new_york)
            market_open_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("09:30:00", "%H:%M:%S").time()))
            market_close_time = new_york.localize(datetime.combine(current_time.date(), datetime.strptime("16:00:00", "%H:%M:%S").time()))
            
            # Ensure the order log is initialized before using it
            initialize_csv_order_log()
            
            # Before market opens
            if ((current_time < market_open_time) or (current_time < market_close_time)) and not already_ran:
                await ensure_economic_calendar_data()
                already_ran = True  # Set this to True to avoid running this block again until the next day

                # Plot the data
                if get_root() is None: # For when program is first starting
                    print_log("WARNING: Chart root disappeared! This should not happen.")
                else: # For 24/7+ Run Times
                    refresh_15_min_candle_stick_data()
            
            # Market is Open
            if market_open_time <= current_time <= market_close_time:
                if websocket_connection is None:  # Start WebSocket connection
                    data_acquisition.should_close = False # Signal its okay to open Websocket
        
                    # Start the WebSocket connection for the active provider
                    asyncio.create_task(ws_auto_connect(queue, active_provider, read_config('SYMBOL')), name="WebsocketConnection")  # Start in the background
                    websocket_connection = True

                    # Get Account Balance and Send to Discord
                    start_of_day_account_balance = await get_account_balance(read_config('REAL_MONEY_ACTIVATED')) if read_config('REAL_MONEY_ACTIVATED') else read_config('START_OF_DAY_BALANCE')
                    f_s_account_balance = "{:,.2f}".format(start_of_day_account_balance)
                    await print_discord(f"Market is Open! Account BP: ${f_s_account_balance}")

                    # Send 2-min chart picture to Discord
                    await send_file_discord(SPY_15M_CHART_PATH)

                    await print_discord(setup_economic_news_message())
                task1 = asyncio.create_task(process_data(queue), name="ProcessDataTask")
                task2 = asyncio.create_task(execute_trading_strategy(), name="TradingStrategyTask")
                await asyncio.gather(task1, task2)
            else: # Market is closed
                if websocket_connection is not None:
                    data_acquisition.should_close = True  # Signal to close WebSocket
                    await process_end_of_day()
                    refresh_15_min_candle_stick_data()
                    already_ran = False
                    keep_loop = False
                if current_time <= market_open_time:
                    await wait_until_market_open(market_open_time, new_york)
                elif market_close_time <= current_time:
                    print_log("The market is closed...")
                    break
        except Exception as e:
            await error_log_and_discord_message(e, "main", "main")

async def wait_until_market_open(target_time, tz):
    print_log(f"Waiting for market open at {target_time.strftime('%H:%M:%S')}...")
    while True:
        now = datetime.now(tz)
        delta = abs((now - target_time).total_seconds())
        if delta <= 1:
            print_log("✅ Market open hit within 1 second margin. Starting...")
            break
        await asyncio.sleep(0.5)

async def process_end_of_day():
    global websocket_connection
    websocket_connection = None

    # 1. Get balances and calculate P/L
    rma = read_config('REAL_MONEY_ACTIVATED')
    start_of_day_account_balance = await get_account_balance(rma) if rma else read_config('START_OF_DAY_BALANCE')
    todays_profit_loss = sum(get_profit_loss_orders_list())
    end_of_day_account_balance = start_of_day_account_balance + todays_profit_loss
    
    # 2. Announce/report to Discord
    f_e_account_balance = "{:,.2f}".format(end_of_day_account_balance)
    await print_discord(f"Market is closed. Today's closing balance: ${f_e_account_balance}")
    message_ids_dict = get_correct_message_ids()
    output_message = await calculate_day_performance(message_ids_dict, start_of_day_account_balance, end_of_day_account_balance)
    await print_discord(output_message)

    # 3. Send relevant files/logs to Discord
    await send_file_discord(SPY_2M_CHART_PATH)
    await send_file_discord(CANDLE_LOGS.get("2M")) #Send file
    await send_file_discord(MARKERS_PATH)
    await send_file_discord(EMAS_PATH)
    await send_file_discord(TERMINAL_LOG)
    process_end_of_day_15m_candles()

    # 4. Administrative/config updates (do this last so nothing breaks mid-report)
    update_config_value('START_OF_DAY_BALANCE', end_of_day_account_balance)

    # 5. Reset all data for next session
    clear_all_states()
    clear_temp_logs_and_order_files()
    reset_profit_loss_orders_list()

async def shutdown(loop):
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

    # Start chart once at boot — main thread only
    chart_thread = threading.Thread(target=plot_candles_and_boxes, args=(0,), name="chart_root")
    chart_thread.start()

    # Start bot and main loop
    loop.create_task(bot_start(), name="DiscordBotStart")
    loop.create_task(main(), name="MainLoop")

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print_log("Manually interrupted, cleaning up...")
        loop.run_until_complete(shutdown(loop))
    finally:
        loop.close()
        