# tll_trading_strategy.py, meaning 'Temporal Lattice Leap Trading Strategy'
import os
from chart_visualization import update_2_min
import asyncio
from datetime import datetime, timedelta, time
from order_handler import get_profit_loss_orders_list, sell_rest_of_active_order
from error_handler import error_log_and_discord_message
from data_acquisition import get_candle_data_and_merge
from utils.file_utils import get_current_candle_index
from utils.json_utils import load_json_df, initialize_ema_json, record_priority_candle, reset_json, read_config
from utils.log_utils import read_last_n_lines
from objects import candle_zone_handler, get_objects
from buy_option import reset_usedBP_messageIDs
from flag_manager import identify_flag, create_state
from rule_manager import handle_rules_and_order
from sentiment_engine import get_current_sentiment
from shared_state import indent, print_log, latest_sentiment_score
import pytz
import cred
import aiohttp
from utils.data_utils import calculate_save_EMAs
from paths import CANDLE_LOGS, PRIORITY_CANDLES_PATH, EMAS_PATH, AFTERMARKET_EMA_PATH, PREMARKET_EMA_PATH, MERGED_EMA_PATH

STRATEGY_NAME = "FLAG/ZONE STRAT"

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

async def execute_trading_strategy():
    print_log("Starting `execute_trading_strategy()`...")
    global last_processed_candle

    indent_lvl=1
    create_state(indent_lvl, "bear", None)
    create_state(indent_lvl, "bull", None)

    MARKET_OPEN_TIME = get_market_open_time()  # Get today's market open time
    market_open_plus_15 = MARKET_OPEN_TIME + timedelta(minutes=15)
    market_open_plus_15 = market_open_plus_15.time()

    zones, tpls = get_objects()

    # Wait for start and populate data
    while True:
        await asyncio.sleep(0.5)  # Check every half second
        f_candle = read_last_n_lines(CANDLE_LOGS.get("2M"), 1)
        if f_candle:
            print_log(f"[ETS] First candle processed: {f_candle[0]}")
            break

    last_processed_candle = None
    candle_interval = 2
    candle_timescale = "minute"

    # Ema Specific variables
    has_calculated_emas = False #TODO False
    candle_list = []  # Stores candles for the first 15 minutes

    initialize_ema_json(EMAS_PATH)

    async with aiohttp.ClientSession() as session:  # Initialize HTTP session
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        try:
            while True:
                # Check if current time is within one minute of market close
                current_time = datetime.now(new_york_tz).time()
                if current_time >= (datetime.combine(datetime.today(), MARKET_CLOSE) - timedelta(minutes=1)).time():
                    candle_list.clear()
                    await sell_rest_of_active_order("Market closing soon. Exiting all positions.")
                    todays_profit_loss = sum(get_profit_loss_orders_list()) #returns todays_orders_profit_loss_list
                    print_log(f"{indent(indent_lvl)}[ETS] todays_profit_loss: {todays_profit_loss}")
                    reset_usedBP_messageIDs()
                    last_processed_candle = None
                    break

                current_last_candle = read_last_n_lines(CANDLE_LOGS.get("2M"), 1)  # Read the latest candle
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
                    #candle_zone_type, is_in_zone = candle_zone_handler(candle, zones)
                    #able_to_buy = not is_in_zone # if so, don't buy inside zones
                    #print_log(f"{indent(indent_lvl)}[ETS-CZH] Zone setup: {candle_zone_type}")
                        
                    # Data allocation
                    await record_priority_candle(candle, "None") # Add candle into `priority_candles.json` to store certian vales into
                    last_candle = load_json_df(PRIORITY_CANDLES_PATH).iloc[-1].to_dict()
                        
                    # Flag handling
                    flags_completed = await identify_flag(last_candle, indent_lvl=indent_lvl+1, print_satements=False)
                    print_log(f"{indent(indent_lvl)}[ETS-IF] Num Flags Completed: {len(flags_completed)}")
                    # Len simpler in logs, if need be for more trackable situations just delete the 'len()'
                    update_2_min(indent_lvl=indent_lvl)

                    #current_candle_score = get_current_sentiment(candle, zones, tpls, indent_lvl+1, False)
                    #print_log(f"{indent(indent_lvl)}[ETS-GCS] Sentiment Score: {current_candle_score}")
                        
                    # Give's `manage_active_order()` 'current_candle_score' access.
                    #latest_sentiment_score["score"] = current_candle_score

                    #if able_to_buy and flags_completed:
                        #handling_detials=await handle_rules_and_order(1, candle, candle_zone_type, zones, flags_completed, session=session, headers=headers, print_statements=False)
                        #if handling_detials[0]:
                            #quantity, strike_ask_bid, strike_price = handling_detials[2], handling_detials[3], handling_detials[4]
                            #order_status_message = f"Buy Signal '{handling_detials[1].upper()}' Successful! → {quantity}x @ {strike_ask_bid} (Strike: {strike_price})"
                        #else:
                            #order_status_message = f"Order Blocked, {handling_detials[1]}"
                        #print_log(f"{indent(indent_lvl)}[ETS-HRAO] {order_status_message}")
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

    if current_time >= market_open_plus_15:
        if not has_calculated_emas and candle_list: # 8:46am
            print_log(f"{indent(indent_lvl)}[EMA CS] Finalizing EMAs after first 15 minutes...")
            
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, AM, PM, indent_lvl+1
            )

            reset_json(EMAS_PATH, [])

            candle_list.append(candle) # Add 8:46 to list
            candle_list_sorted = sorted(candle_list, key=lambda c: c["timestamp"]) # Sort candles chronologically
            
            for i, _candle in enumerate(candle_list_sorted):
                await calculate_save_EMAs(_candle, i)

            print_log(f"{indent(indent_lvl)}[EMA CS] Final EMA list calculated.")
            return True  # EMAs finalized
        
        elif not has_calculated_emas and not candle_list: # TODO: This is for testing, making sure the live version works well with this new setup. Once it works reliably, remove this block of code (if-statement and everything in it)
            print_log(f"{indent(indent_lvl)}[EMA CS] Program Started AFTER the first 15 minutes...")
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, AM, PM, indent_lvl+1
            )
            reset_json(EMAS_PATH, []) # Clear EMAs.json file for a clean slate
            return True  # EMAs finalized
        
        elif has_calculated_emas: # 8:48am and After...
            await calculate_save_EMAs(candle, get_current_candle_index())
            print_log(f"{indent(indent_lvl)}[EMA CS] EMA updated post-15-min.")
            return True  # EMAs finalized
        
    else: # Still within first 15 min, From 8:32 Till 8:44am.
        candle_list.append(candle)

        # Wipe and recreate merged files
        for file_path in [AFTERMARKET_EMA_PATH, PREMARKET_EMA_PATH, MERGED_EMA_PATH]:
            if os.path.exists(file_path):
                os.remove(file_path)

        await get_candle_data_and_merge(
            candle_interval, candle_timescale, AM, PM, indent_lvl+1
        )

        # Clear EMAs.json file for a clean slate
        reset_json(EMAS_PATH, [])

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
    num = get_current_candle_index()
    print_log(f"[{formatted_time}] {num} OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")