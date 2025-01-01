import os
import json
import asyncio
from error_handler import error_log_and_discord_message, print_log
from data_acquisition import read_ema_json, get_current_candle_index, above_below_ema, read_last_n_lines, load_message_ids, read_config
from buy_option import buy_option_cp
import cred
import aiohttp

STRATEGY_NAME = "200 EMA CROSS STRAT"

STRATEGY_DESCRIPTION = """When the candle crosses the 200 ema it buys a call or put and we use the 13 ema as our stoploss. If it crosses the ema by going down, it buys a put and if it goes up, it buys a call."""

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

config = read_config()
#IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
#SYMBOL = config["SYMBOL"]
#TIMEFRAMES = config["TIMEFRAMES"]

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f'{read_config("SYMBOL")}_{read_config("TIMEFRAMES")[0]}.log')

last_processed_candle = None
last_processed_ema = None
async def execute_200ema_strategy():
    print_log("Starting execute_200ema_strategy()...")
    global last_processed_candle
    global last_processed_ema

    message_ids_dict = load_message_ids()
    print_log("message_ids_dict: ", message_ids_dict)


    async with aiohttp.ClientSession() as session:  # Initialize HTTP session
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        try:
            while True:
                current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)  # Read the latest candle
                #current_last_ema looks like this: {'13': 497.7309298942181, '48': 497.17249282745496, '200': 497.041904265085, 'x': 88}
                current_last_ema = await read_ema_json(-1) #get last position
                ema_type = "200"
                
                if (current_last_candle and current_last_candle != last_processed_candle) and (current_last_ema and current_last_ema != last_processed_ema):
                    last_processed_candle = current_last_candle
                    last_processed_ema = current_last_ema
                    #get that candle, look at its OHLC values, it looks like this: {'open': 497.69, 'high': 497.91, 'low': 497.65, 'close': 497.885, 'timestamp': '2024-04-22T11:28:00.142634'}
                    candle = last_processed_candle[0]
                    candle_pos = get_current_candle_index()
                    ema_x = last_processed_ema["x"]
                    desired_ema = last_processed_ema[ema_type]
                    print_log(f"    [EMA STRATEGY] candle (X, OHLC): ( {candle_pos}, ({candle['open']}, {candle['high']}, {candle['low']}, {candle['close']})); {ema_type}ema: {ema_x}, {desired_ema}")
                    
                    if candle['open'] < desired_ema < candle['close']:
                        #candle closed over ema
                        print_log("Buy Call")
                        if await above_below_ema('above'): # i think this will help with alternating between orders.
                            await buy_option_cp(read_config("REAL_MONEY_ACTIVATED"), read_config("SYMBOL"), 'call', session, headers, STRATEGY_NAME)

                    elif candle['close'] < desired_ema < candle['open']:
                        #candle closed below ema
                        print_log("Buy Put")
                        if await above_below_ema('below'): # i think this will help with alternating between orders.
                            await buy_option_cp(read_config("REAL_MONEY_ACTIVATED"), read_config("SYMBOL"), 'put', session, headers, STRATEGY_NAME)

                else:
                    await asyncio.sleep(0.5)  # Wait for new candle data


        except Exception as e:
            await error_log_and_discord_message(e, "ema_strategy", "execute_200ema_strategy")



