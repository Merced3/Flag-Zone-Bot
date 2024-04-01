from main import get_dates, main, load_from_csv
from data_acquisition import get_candle_data, ws_connect, get_current_price, get_current_candle_index
from chart_visualization import plot_candles_and_boxes
import chart_visualization
from tll_trading_strategy import buy_option_cp, message_ids_dict, load_message_ids
from print_discord_messages import bot, print_discord, get_message_content, send_file_discord
import cred
import asyncio
import aiohttp
import boxes
import threading
import pandas as pd
import json
from pathlib import Path
import glob
import os

config_path = Path(__file__).resolve().parent / 'config.json'
def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config

config = read_config()
SYMBOL = config["SYMBOL"]
DAYS = config["PAST_DAYS"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]

#start_date, end_date = get_dates(DAYS)
#print(f"Start and End days: \n{start_date}, {end_date}\n")

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)

async def simulation():
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")
    #await testing_Buys()
    #await testing_plotting_new_data()
    #await testing_identify_flags()

    #clear the markers.json file
    markers_file_path = Path(__file__).resolve().parent / 'markers.json'
    if os.path.exists(markers_file_path):
        os.remove(markers_file_path)
    
    await testing_add_markers('buy')
    await testing_add_markers('trim')
    await testing_add_markers('sell')

async def testing_add_markers(event_type):
    
    log_file_path = Path(__file__).resolve().parent / 'logs/Example_SPY_2M.log'
    x_coord = get_current_candle_index(log_file_path)
    y_coord = await get_current_price(SYMBOL)
    print(f"Marker: {x_coord}, {y_coord}, {event_type}")

    marker_styles = {
        'buy': {'marker': '^', 'color': 'green'},
        'trim': {'marker': 'o', 'color': 'blue'},
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

    # Ensure the file exists and contains an empty list if it's new
    if not markers_file_path.exists():
        with open(markers_file_path, 'w') as f:
            json.dump([], f)

    # Read existing markers from the file, or initialize an empty list if there's a JSON decode error
    try:
        with open(markers_file_path, 'r') as f:
            markers = json.load(f)
    except json.decoder.JSONDecodeError:
        markers = []

    # Append the new marker and write back to the file
    markers.append(marker)
    with open(markers_file_path, 'w') as f:
        json.dump(markers, f, indent=4)

async def testing_plotting_new_data():
    already_ran = False

    #TEST GETTING CANDLE DATA AND PLOTTING
    start_date, end_date = get_dates(DAYS)
    print(f"15m) Start and End days: \n{start_date}, {end_date}\n")

    #would be cool to constantly get 1 day 15 min chart data and keep on adding it to the CSV file, once i find a way to do that
    candle_15m_data = load_from_csv(f"{SYMBOL}_15_minute_candles.csv")
    if candle_15m_data is None:
        candle_15m_data = await get_candle_data(cred.POLYGON_API_KEY, SYMBOL, 15, "minute", start_date, end_date)
  
    #TODO: do not delete the 2 min data, its not important for this test but needed for the plotting of chart
    candle_2m_data = load_from_csv(f"{SYMBOL}_2_minute_candles.csv")

    if candle_15m_data is not None and 'timestamp' in candle_15m_data.columns and not already_ran:
        Boxes = boxes.get(candle_15m_data, DAYS)
        chart_thread = threading.Thread(target=plot_candles_and_boxes, args=(candle_15m_data, candle_2m_data, Boxes, SYMBOL))
        chart_thread.start()
        already_ran = True

async def testing_identify_flags():
    Testing_Box = {'resistance_1': (244, 475.38, 474.92)}
    #I want to see how we can identify bear and bull flags, and how to identify the breakout of the flag
    #first we need to get candle data, we will find that in 'logs/Example_SPY_2M.log'
    candle_data = Path(__file__).resolve().parent / 'logs/Example_SPY_2M.log'
    #check if file exists
    if os.path.exists(candle_data):
        await simulate_candle_data(candle_data, interval=5)  # Change to 120 for 2 minutes
    else:
        print(f"File {candle_data} does not exist")
        return

async def simulate_candle_data(candle_data_path, interval=5):
    with open(candle_data_path, 'r') as file:
        candles_json = file.readlines()
    
    # Convert JSON strings to a list of dictionaries
    candles = [json.loads(candle) for candle in candles_json]
    
    # Convert to DataFrame for easier manipulation
    df_candles = pd.DataFrame(candles)
    
    # Convert timestamps to datetime objects
    df_candles['timestamp'] = pd.to_datetime(df_candles['timestamp'])
    
    # Set the index to the timestamp for time series analysis
    df_candles.set_index('timestamp', inplace=True)

    # Iterate through candles as if they are coming in live
    for index, row in df_candles.iterrows():
        print(f"Current candle: {row.to_dict()}")
        await asyncio.sleep(interval)  # Wait for a short period before the next candle

        # Here you would call your flag identification logic
        identify_flags(df_candles.loc[:index])

def identify_flags(df):
    # Analyze the DataFrame to identify flag patterns
    # This is just a placeholder for your actual logic
    # For example, you could look for small-bodied candles within a range
    # after a strong movement, followed by a breakout candle
    pass

async def testing_Buys():       
    headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
    
    await print_discord(f"Starting Bot, Real Money Activated" if IS_REAL_MONEY else f"Starting Bot, Real-Paper-Trading Activated")
    print()

    message_ids_dict = load_message_ids()
    
    # Initialize session with aiohttp

    async with aiohttp.ClientSession() as session:
        for _ in range(11):
            await buy_option_cp(IS_REAL_MONEY, SYMBOL, "call", session, headers)
            await asyncio.sleep(5)
            await buy_option_cp(IS_REAL_MONEY, SYMBOL, "put", session, headers)
            await asyncio.sleep(5)



if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    
    # Start the bot and the main coroutine
    loop.create_task(bot_start())
    loop.create_task(simulation())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("Manually interrupted, cleaning up...")
    finally:
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
        loop.close()