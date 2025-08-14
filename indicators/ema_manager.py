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
            "seen_ts": set(),           # <<< NEW: dedupe guard
            "has_calculated": False # TODO: `False` before market opens, `True` after first 15 mins of market opens
        }

def _append_unique_premarket(state, candle):
    """
    Only buffer a candle once (by its timestamp string).
    Prevents inflated counts when WS resends or code replays a candle.
    """
    ts = candle.get("timestamp")
    # normalize to plain second level for safety
    ts_key = str(ts)[:19] if ts is not None else None
    if ts_key and ts_key not in state["seen_ts"]:
        state["seen_ts"].add(ts_key)
        state["candle_list"].append(candle)

def _clear_buffer(state):
    state["candle_list"].clear()
    state["seen_ts"].clear()

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
        # --- POST 09:45 ET: ensure we are initialized ONCE, then switch to incremental ---
        if not state["has_calculated"]:
            # Cover both "normal" and "started-late" cases with the same bootstrap path.
            print_log(f"{indent_pad}[EMA CS] Finalizing EMAs after first 15 minutes for {timeframe}...")
            await get_candle_data_and_merge(
                candle_interval, candle_timescale, "AFTERMARKET", "PREMARKET", indent_lvl+1, timeframe
            )
            reset_json(ema_path, [])

            # Rebuild EMA series deterministically from the buffered candles (if any)
            if state["candle_list"]:
                sorted_candles = sorted(state["candle_list"], key=lambda c: c["timestamp"])
                for i, c in enumerate(sorted_candles):
                    await calculate_save_EMAs(c, i, timeframe)

            state["has_calculated"] = True
            _clear_buffer(state)  # <<< NEW: drop the pre-open cache so counts can't linger
            print_log(f"{indent_pad}[EMA CS] Final EMA list calculated for {timeframe}.")
        # From here on, strictly incremental
        await calculate_save_EMAs(candle, get_current_candle_index(timeframe), timeframe)
        print_log(f"{indent_pad}[EMA CS] Updated live EMA for {timeframe}.")
    else:
        # --- PRE 09:45 ET: keep a clean, deduped buffer & live temp EMAs for the UI ---
        _append_unique_premarket(state, candle)  # <<< NEW: dedupe
        # Clean any old merge artifacts to prevent mixing runs
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

        # log exact size of the *deduped* buffer so it matches your mental model
        print_log(f"{indent_pad}[EMA CS] Temp EMA calculated for {timeframe} ({len(state['candle_list'])} candles).")
