# indicators/ema_manager.py
from shared_state import indent, print_log
from data_acquisition import get_candle_data_and_merge
from utils.json_utils import reset_json, initialize_json
from paths import get_ema_path, AFTERMARKET_EMA_PATH, PREMARKET_EMA_PATH, MERGED_EMA_PATH
from utils.file_utils import get_current_candle_index
from utils.ema_utils import calculate_save_EMAs, load_ema_json # the function `load_ema_json()` is called in the `initialize_timeframe_state()` function but its commented out.
from datetime import datetime, timedelta, time
import pytz
import os

new_york_tz = pytz.timezone('America/New_York')
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Dynamic state tracking for each timeframe
ema_state = {}

def initialize_timeframe_state(timeframe):
    if timeframe not in ema_state:
        #ema_path = get_ema_path(timeframe)
        #already_has_ema = bool(load_ema_json(ema_path))  # True if prior EMAs exist

        # We could use 'already_has_ema', but this has not been tested. I fear that it won't work
        # because it might consider `[]` as contents existing plus if it adds one contents into
        # the ema json file then the first candle that is inbetween the first 15 minutes would
        # turn this to true making it not work as intented.

        ema_state[timeframe] = {
            "candle_list": [],
            "has_calculated": False # TODO: `False` before market opens, `True` after first 15 mins of market opens
        }

def get_market_open_plus_15():
    now = datetime.now(new_york_tz)
    today = now.date()
    market_open_time = datetime.combine(today, MARKET_OPEN)
    return (market_open_time + timedelta(minutes=15)).time()

async def update_ema(candle: dict, timeframe: str):
    """
    Main interface to update EMA for a given candle and timeframe.
    """
    initialize_timeframe_state(timeframe)
    state = ema_state[timeframe]

    current_time = datetime.now(new_york_tz).time()
    market_open_plus_15 = get_market_open_plus_15()

    # Configurable (or calculated) interval
    interval_minutes = int(timeframe.replace("M", "").replace("m", ""))
    candle_interval = interval_minutes
    candle_timescale = "minute"
    indent_lvl = 1
    ema_path = get_ema_path(timeframe)
    initialize_json(ema_path, [])

    indent_pad = indent(indent_lvl)

    if current_time >= market_open_plus_15:
        if not state["has_calculated"] and state["candle_list"]:
            print_log(f"{indent_pad}[EMA CS] Finalizing EMAs after first 15 minutes for {timeframe}...")
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, "AFTERMARKET", "PREMARKET", indent_lvl+1, timeframe
            )
            reset_json(ema_path, [])
            state["candle_list"].append(candle)
            sorted_candles = sorted(state["candle_list"], key=lambda c: c["timestamp"])
            for i, c in enumerate(sorted_candles):
                await calculate_save_EMAs(c, i, timeframe)
            state["has_calculated"] = True
            print_log(f"{indent_pad}[EMA CS] Final EMA list calculated for {timeframe}.")

        elif not state["has_calculated"] and not state["candle_list"]:
            print_log(f"{indent_pad}[EMA CS] Bot started late; force initializing {timeframe} EMAs...")
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, "AFTERMARKET", "PREMARKET", indent_lvl+1, timeframe
            )
            reset_json(ema_path, [])
            state["has_calculated"] = True
        
        elif state["has_calculated"]:
            await calculate_save_EMAs(candle, get_current_candle_index(timeframe), timeframe)
            print_log(f"{indent_pad}[EMA CS] Updated live EMA for {timeframe}.")

    else:
        state["candle_list"].append(candle)
        for path in [AFTERMARKET_EMA_PATH, PREMARKET_EMA_PATH, MERGED_EMA_PATH]:
            if os.path.exists(path):
                os.remove(path)
        await get_candle_data_and_merge(
            candle_interval, candle_timescale, "AFTERMARKET", "PREMARKET", indent_lvl+1, timeframe
        )
        reset_json(ema_path, [])
        sorted_candles = sorted(state["candle_list"], key=lambda c: c["timestamp"])
        for i, c in enumerate(sorted_candles):
            await calculate_save_EMAs(c, i, timeframe)
        print_log(f"{indent_pad}[EMA CS] Temp EMA calculated for {timeframe} ({len(state['candle_list'])} candles).")
