# tll_trading_strategy.py, meaning 'Temporal Lattice Leap Trading Strategy'
import os
from chart_visualization import update_2_min
import json
import asyncio
from datetime import datetime, timedelta, time
from order_handler_v2 import get_profit_loss_orders_list, sell_rest_of_active_order
from error_handler import error_log_and_discord_message
from data_acquisition import get_current_candle_index, calculate_save_EMAs, get_candle_data_and_merge, load_json_df, read_last_n_lines, load_message_ids, initialize_ema_json, restart_state_json, record_priority_candle, reset_json, read_config
from boxes import candle_zone_handler
from buy_option import reset_usedBP_messageIDs
from flag_manager import identify_flag, create_state
from rule_manager import handle_rules_and_order
from sentiment_engine import get_current_sentiment
from shared_state import indent, print_log, latest_sentiment_score
from pathlib import Path
import pytz
import cred
import aiohttp

STRATEGY_NAME = "FLAG/ZONE STRAT"

config_path = Path(__file__).resolve().parent / 'config.json'

config = read_config()
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f"{read_config('SYMBOL')}_{read_config('TIMEFRAMES')[0]}.log")  # Adjust the path accordingly

active_order = {
    'order_id': None,
    'order_retrieval': None,
    'entry_price': None,
    'quantity': None,
    'partial_exits': []
}

last_processed_candle = None 
    
new_york_tz = pytz.timezone('America/New_York')

MARKET_CLOSE = time(16, 0)
MARKET_OPEN = time(9, 30)

def get_market_open_time():
    today = datetime.now(new_york_tz).date()
    market_open_time = datetime.combine(today, time(9, 30))
    return new_york_tz.localize(market_open_time)

async def execute_trading_strategy(zones, tpls):
    print_log("Starting `execute_trading_strategy()`...")
    global last_processed_candle

    indent_lvl=1
    create_state(indent_lvl, "bear", None)
    create_state(indent_lvl, "bull", None)

    MARKET_OPEN_TIME = get_market_open_time()  # Get today's market open time
    market_open_plus_15 = MARKET_OPEN_TIME + timedelta(minutes=15)
    market_open_plus_15 = market_open_plus_15.time()

    # Wait for start and populate data
    while True:
        await asyncio.sleep(0.5)  # Check every half second
        f_candle = read_last_n_lines(LOG_FILE_PATH, 1)
        if f_candle:
            print_log(f"[ETS] First candle processed: {f_candle[0]}")
            break

    last_processed_candle = None
    candle_interval = 2
    candle_timescale = "minute"

    # Ema Specific variables
    has_calculated_emas = False #TODO False
    candle_list = []  # Stores candles for the first 15 minutes

    initialize_ema_json('EMAs.json')

    async with aiohttp.ClientSession() as session:  # Initialize HTTP session
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        try:
            while True:
                # Check if current time is within one minute of market close
                current_time = datetime.now(new_york_tz).time()
                if current_time >= (datetime.combine(datetime.today(), MARKET_CLOSE) - timedelta(minutes=1)).time():
                    # If within one minute of market close, exit all positions
                    candle_list.clear()
                    await sell_rest_of_active_order("Market closing soon. Exiting all positions.")
                    todays_profit_loss = sum(get_profit_loss_orders_list()) #returns todays_orders_profit_loss_list
                    end_of_day_account_balance = read_config('ACCOUNT_BALANCES')[0] + todays_profit_loss
                    print_log(f"{indent(indent_lvl)}[ETS] ACCOUNT_BALANCES[0]: {read_config('ACCOUNT_BALANCES')[0]}\n{indent(indent_lvl)}[ETS] todays_profit_loss: {todays_profit_loss}\n{indent(indent_lvl)}[ETS] end_of_day_account_balance: {end_of_day_account_balance}")
                    _config = None
                    with open(config_path, 'r') as f: # Read existing config
                        _config = json.load(f)
                    _config["ACCOUNT_BALANCES"][1] = end_of_day_account_balance # Update the ACCOUNT_BALANCES
                    with open(config_path, 'w') as f: # Write back the updated config
                        json.dump(_config, f, indent=4)  # Using indent for better readability
                    reset_usedBP_messageIDs()
                    last_processed_candle = None
                    break

                current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)  # Read the latest candle
                if current_last_candle and current_last_candle != last_processed_candle:
                    last_processed_candle = current_last_candle
                    # Get candle, its OHLC values
                    candle = last_processed_candle[0]
                    
                    # Handle Making EMA's
                    has_calculated_emas = await EMAs_calc_save(
                        candle, current_time, market_open_plus_15, has_calculated_emas,
                        candle_list, candle_interval, candle_timescale, indent_lvl+1
                    )

                    # Figure out where the candle is relative to zones, this tells us if were outside or inside a zone.
                    candle_zone_type, is_in_zone = candle_zone_handler(candle, zones)
                    able_to_buy = not is_in_zone # if so, don't buy inside zones
                    print_log(f"{indent(indent_lvl)}[ETS-CZH] Zone setup: {candle_zone_type}")
                        
                    # Data allocation
                    await record_priority_candle(candle, candle_zone_type) # Add candle into `priority_candles.json` to store certian vales into
                    last_candle = load_json_df('priority_candles.json').iloc[-1].to_dict()
                        
                    # Flag handling
                    flags_completed = await identify_flag(last_candle, indent_lvl=indent_lvl+1, print_satements=False)
                    print_log(f"{indent(indent_lvl)}[ETS-IF] Num Flags Completed: {len(flags_completed)}")
                    # Len simpler in logs, if need be for more trackable situations just delete the 'len()'
                    update_2_min(indent_lvl=indent_lvl)

                    current_candle_score = get_current_sentiment(candle, zones, tpls, indent_lvl+1, False)
                    print_log(f"{indent(indent_lvl)}[ETS-GCS] Sentiment Score: {current_candle_score}")
                        
                    # TODO: Give's `manage_active_order()` 'current_candle_score' access.
                    latest_sentiment_score["score"] = current_candle_score

                    if able_to_buy and flags_completed:
                        handling_detials=await handle_rules_and_order(1, candle, candle_zone_type, zones, flags_completed, session=session, headers=headers, print_statements=False)
                        if handling_detials[0]:
                            quantity, strike_ask_bid, strike_price = handling_detials[2], handling_detials[3], handling_detials[4]
                            order_status_message = f"Buy Signal '{handling_detials[1].upper()}' Successful! → {quantity}x @ {strike_ask_bid} (Strike: {strike_price})"
                        else:
                            order_status_message = f"Order Blocked, {handling_detials[1]}"
                        print_log(f"{indent(indent_lvl)}[ETS-HRAO] {order_status_message}")
                        # {quantity}x @ {strike_ask_bid} (Strike: {strike_price})
                    update_2_min()
                else:
                    await asyncio.sleep(1)  # Wait for new candle data

        except Exception as e:
            await error_log_and_discord_message(e, "tll_trading_strategy", "execute_trading_strategy")

async def EMAs_calc_save(candle, current_time, market_open_plus_15, has_calculated_emas,
    candle_list, candle_interval, candle_timescale, indent_lvl):
    """
    Calculates and saves EMAs based on current time and whether we're past the first 15 minutes.
    """
    AM = "AFTERMARKET"
    PM = "PREMARKET"
    aftermarket_file = f"{read_config('SYMBOL')}_{candle_interval}_{candle_timescale}_{AM}.csv"
    premarket_file = f"{read_config('SYMBOL')}_{candle_interval}_{candle_timescale}_{PM}.csv"
    merged_file_name = f"{read_config('SYMBOL')}_MERGED.csv"

    if current_time >= market_open_plus_15:
        if not has_calculated_emas and candle_list: # 8:46am
            print_log(f"{indent(indent_lvl)}[EMA CS] Finalizing EMAs after first 15 minutes...")
            
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, AM, PM, merged_file_name, indent_lvl+1
            )

            reset_json('EMAs.json', [])

            candle_list.append(candle) # Add 8:46 to list
            candle_list_sorted = sorted(candle_list, key=lambda c: c["timestamp"]) # Sort candles chronologically
            
            for i, _candle in enumerate(candle_list_sorted):
                await calculate_save_EMAs(_candle, i)

            print_log(f"{indent(indent_lvl)}[EMA CS] Final EMA list calculated.")
            return True  # EMAs finalized
        
        elif has_calculated_emas: # 8:48am and After...
            await calculate_save_EMAs(candle, get_current_candle_index())
            print_log(f"{indent(indent_lvl)}[EMA CS] EMA updated post-15-min.")
            return True
        
    else: # Still within first 15 min, From 8:32 Till 8:44am.
        candle_list.append(candle)

        # Wipe and recreate merged files
        for file_path in [aftermarket_file, premarket_file, merged_file_name]:
            if os.path.exists(file_path):
                os.remove(file_path)

        await get_candle_data_and_merge(
            candle_interval, candle_timescale, AM, PM, merged_file_name, indent_lvl
        )

        # Clear EMAs.json file for a clean slate
        reset_json('EMAs.json', [])

        # Sort candles chronologically
        candle_list_sorted = sorted(candle_list, key=lambda c: c["timestamp"])

        for i, _candle in enumerate(candle_list_sorted):
            await calculate_save_EMAs(_candle, i)

        print_log(f"{indent(indent_lvl)}[EMA CS] Calculated temporary EMA for first 15 min candle list with {len(candle_list)} candles.")
        return False  # Still accumulating
    
def print_log_candle(candle):
    #{candle['candle_index']}
    timestamp_str = candle["timestamp"]
    timestamp_dt = datetime.fromisoformat(timestamp_str)
    formatted_time = timestamp_dt.strftime("%H:%M:%S")
    num = get_current_candle_index(LOG_FILE_PATH)
    print_log(f"[{formatted_time}] {num} OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")