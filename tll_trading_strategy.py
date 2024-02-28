# tll_trading_strategy.py, meaning 'Temporal Lattice Leap Trading Strategy'
import os
import json
import asyncio
from datetime import datetime, timedelta, time
from submit_order import find_what_to_buy, submit_option_order, submit_option_order_v2, get_order_status, get_expiration, calculate_quantity
from order_handler import get_profit_loss_orders_list, get_unique_order_id_and_is_active, manage_active_order, sell_rest_of_active_order, manage_active_fake_order
from print_discord_messages import print_discord
from error_handler import error_log_and_discord_message
from data_acquisition import get_account_balance, add_markers, get_current_candle_index, calculate_save_EMAs, get_current_price, get_candle_data_and_merge
from pathlib import Path
import pandas as pd
import math
import pytz
import cred
import aiohttp

STRATEGY_NAME = "TEMPORAL LATTICE LEAP"

STRATEGY_DESCRIPTION = """ """

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config

config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
NUM_OUT_MONEY = config["NUM_OUT_OF_MONEY"]
SYMBOL = config["SYMBOL"]
TIMEFRAMES = config["TIMEFRAMES"]
ACCOUNT_BALANCE = config["ACCOUNT_BALANCES"]
MIN_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MIN_NUM_CANDLES"]
MAX_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MAX_NUM_CANDLES"]

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f'{SYMBOL}_{TIMEFRAMES[0]}.log')  # Adjust the path accordingly

active_order = {
    'order_id': None,
    'order_retrieval': None,
    'entry_price': None,
    'quantity': None,
    'partial_exits': []
}

last_processed_candle = None 

MESSAGE_IDS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'message_ids.json')
message_ids_dict = {}

def load_message_ids():
    if os.path.exists(MESSAGE_IDS_FILE_PATH):
        with open(MESSAGE_IDS_FILE_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    else:
        return {}

def read_last_n_lines(file_path, n): #code from a previous ema tradegy, thought it may help. pls edit if need be.
    # Ensure the logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    # Check if the file exists, if not, create an empty file
    if not os.path.isfile(file_path):
        with open(file_path, 'w') as file:
            pass

    with open(file_path, 'r') as file:
        lines = file.readlines()
        last_n_lines = lines[-n:]
        return [json.loads(line.strip()) for line in last_n_lines]
    
new_york_tz = pytz.timezone('America/New_York')

MARKET_CLOSE = time(16, 0)
MARKET_OPEN = time(9, 30)
used_buying_power = {}

def load_json_df(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return pd.DataFrame(data)

def get_papertrade_BP():
    #get every orders cost that is in USED_BUYING_POWER, calculate how much all of it added togther costs
    all_order_costs = sum(used_buying_power.values())
    current_balance = config["ACCOUNT_BALANCES"][0]
    current_bp_left = current_balance - all_order_costs
    return current_bp_left

def get_market_open_time():
    today = datetime.now(new_york_tz).date()
    market_open_time = datetime.combine(today, time(9, 30))
    return new_york_tz.localize(market_open_time)

def initialize_ema_json(json_path):
    """Ensure the EMA JSON file exists and is valid; initialize if not."""
    if not os.path.exists(json_path) or os.stat(json_path).st_size == 0:
        with open(json_path, 'w') as file:
            json.dump([], file)  # Initialize with an empty list
    try:
        with open(json_path, 'r') as file:
            return json.load(file) if isinstance(json.load(file), list) else []
    except json.JSONDecodeError:
        return []

async def execute_trading_strategy(zones):
    print("Starting execute_trading_strategy()...")
    global last_processed_candle

    message_ids_dict = load_message_ids()
    print("message_ids_dict: ", message_ids_dict)

    what_type_of_candle = None #TODO None
    havent_cleared = None #TODO None

    candle_list = []  # Stores candles for the first 15 minutes
    # Flag to check if initial candles have been processed
    has_calculated = False #TODO False

    MARKET_OPEN_TIME = get_market_open_time()  # Get today's market open time
    market_open_plus_15 = MARKET_OPEN_TIME + timedelta(minutes=15)
    market_open_plus_15 = market_open_plus_15.time()

    restart_state_json("state.json", True)

    candle_interval = 2
    candle_timescale = "minute"
    AM = "AFTERMARKET"
    PM = "PREMARKET"
    aftermarket_file = f"{SYMBOL}_{candle_interval}_{candle_timescale}_{AM}.csv"
    premarket_file = f"{SYMBOL}_{candle_interval}_{candle_timescale}_{PM}.csv"
    json_EMA_path = 'EMAs.json'
    merged_file_name = f"{SYMBOL}_MERGED.csv"

    initialize_ema_json(json_EMA_path)

    async with aiohttp.ClientSession() as session:  # Initialize HTTP session
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        try:
            while True:
                # Check if current time is within one minute of market close
                current_time = datetime.now(new_york_tz).time()
                if current_time >= (datetime.combine(datetime.today(), MARKET_CLOSE) - timedelta(minutes=1)).time():
                    # If within one minute of market close, exit all positions
                    await sell_rest_of_active_order(message_ids_dict, "Market closing soon. Exiting all positions.")
                    todays_profit_loss = sum(get_profit_loss_orders_list()) #returns todays_orders_profit_loss_list
                    end_of_day_account_balance = ACCOUNT_BALANCE[0] + todays_profit_loss
                    print(f"ACCOUNT_BALANCE[0]: {ACCOUNT_BALANCE[0]}, todays_profit_loss: {todays_profit_loss}\nend_of_day_account_balance: {end_of_day_account_balance}")
                    
                    with open(config_path, 'r') as f: # Read existing config
                        config = json.load(f)
                    config["ACCOUNT_BALANCES"][1] = end_of_day_account_balance # Update the ACCOUNT_BALANCES
                    with open(config_path, 'w') as f: # Write back the updated config
                        json.dump(config, f, indent=4)  # Using indent for better readability
                    break

                current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)  # Read the latest candle
                if current_last_candle and current_last_candle != last_processed_candle:
                    last_processed_candle = current_last_candle
                    #get that candle, look at its OHLC values
                    candle = last_processed_candle[0]
                    
                    # Calculate/Save EMAs
                    if current_time >= market_open_plus_15:
                        if not has_calculated and candle_list:
                            await get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, AM, PM, merged_file_name) 
                            #i need to change this for loop
                            for _candle in reversed(candle_list):
                                index_val_in_list = len(candle_list) - candle_list.index(_candle) - 1
                                await calculate_save_EMAs(_candle, index_val_in_list)
                            #calculate the current candle after the list has been processed
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA list")
                            has_calculated = True
                        elif has_calculated:
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA candle")
                    else:
                        candle_list.append(candle)
                        has_calculated = False

                    #Handle the zones
                    for box_name, (count, high_low_of_day, buffer) in zones.items(): 
                        # More code...
                        if "support" in box_name:
                            PDL = high_low_of_day #Previous Day Low
                            # if price goes back into zone, then stop recording candles and delete the data in priority_candles.json
                            if candle['open'] <= buffer and candle['close'] >= buffer: 
                                what_type_of_candle = f"{box_name} Buffer"
                                print(f"    [START 1] Recording SUPPORT Priority Candles; type = {what_type_of_candle}") #simulate recording data...
                                havent_cleared = True
                            elif candle['open'] >= buffer and candle['close'] <= buffer:
                                print(f"    [END 2] Recording Priority Candles; type = {what_type_of_candle}")
                                what_type_of_candle = None
                                
                            if candle['open'] >= PDL and candle['close'] <= PDL: 
                                what_type_of_candle = f"{box_name} PDL"
                                print(f"    [Start 3] Recording Priority Candles; type = {what_type_of_candle}")
                                havent_cleared = True
                            elif candle['open'] <= PDL and candle['close'] >= PDL:
                                print(f"    [END 4] Recording Priority Candles; type = {what_type_of_candle}")
                                what_type_of_candle = None
                              
                        elif ("resistance" in box_name) or ("PDHL" in box_name):
                            PDH = high_low_of_day #Previous Day High
                            if candle['open'] >= buffer and candle['close'] <= buffer:
                                what_type_of_candle = f"{box_name} Buffer"
                                print(f"    [START 5] Recording RESISTANCE Priority Candles; type = {what_type_of_candle}") #simulate recording data...
                                havent_cleared = True
                            elif candle['open'] <= buffer and candle['close'] >= buffer:
                                print(f"    [END 6] Recording Priority Candles; type = {what_type_of_candle}")
                                what_type_of_candle = None
                            
                            if candle['open'] <= PDH and candle['close'] >= PDH: 
                                what_type_of_candle = f"{box_name} PDH"
                                print(f"    [START 7] Recording RESISTANCE Priority Candles; type = {what_type_of_candle}")
                                havent_cleared = True
                            elif candle['open'] >= PDH and candle['close'] <= PDH:
                                print(f"    [END 8] Recording Priority Candles; type = {what_type_of_candle}")
                                what_type_of_candle = None
                    if what_type_of_candle is not None:
                        #record the candle data
                        await record_priority_candle(candle, what_type_of_candle)
                        priority_candles = load_json_df('priority_candles.json')
                        num_flags = count_flags_in_json()
                        last_candle = priority_candles.iloc[-1]
                        last_candle_dict = last_candle.to_dict()
                        await identify_flag(last_candle_dict, num_flags, session, headers)
                    else:
                        clear_priority_candles(havent_cleared, what_type_of_candle)
                        restart_state_json("state.json", havent_cleared)
                        resolve_flags()  
                else:
                    await asyncio.sleep(1)  # Wait for new candle data

        except Exception as e:
            await error_log_and_discord_message(e, "tll_trading_strategy", "execute_trading_strategy")

async def identify_flag(candle, num_flags, session, headers):
    print(f"    [Candle {candle['candle_index']}] OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")
    state_file_path = "state.json" 
    
    # Read the current state from the JSON file
    with open(state_file_path, 'r') as file:
        state = json.load(file)
    
    current_high = state.get('current_high', None)
    highest_point = state.get('highest_point', None)
    lower_highs = state.get('lower_highs', [])
    
    current_low = state.get('current_low', None)
    lowest_point = state.get('lowest_point', None)
    higher_lows = state.get('higher_lows', [])

    slope = state.get('slope', None)
    intercept = state.get('intercept', None)


    # Check if the 'type' key exists in the candle dictionary
    if 'type' in candle and ('support Buffer' in candle['type']) or ('resistance PDH' in candle['type']) or ('PDHL PDH' in candle['type']):
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_high is None or candle['high'] > current_high:
            # NEW CODE: Somehow check if there already is a flag and if current candle is higher then slopes highest high, if it is it should buy
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, breakout_type='bullish'
                )   
            current_high = candle['high']
            highest_point = (candle['candle_index'], current_high)
            print(f"        [Highest Point] New: {highest_point}")
            lower_highs = []
        else: 
            if candle['high'] == current_high and candle['candle_index'] > highest_point[0]:
                highest_point = (candle['candle_index'], current_high)
                print(f"        [Highest Point] Updated: {highest_point}")
                lower_highs = []
            else:
                lower_highs.append((candle['candle_index'], candle['high']))
        # This block calculates the slope and intercept for a potential flag, updating line data if valid points are found.
        if len(lower_highs) >= MIN_NUM_CANDLES and (slope is None or intercept is None):
            print(f"        [SLOPE] Calculating Slope Line...")
            slope, intercept = calculate_slope_intercept(lower_highs, highest_point)
            if slope is not None:  # Add a check here
                if is_angle_valid(slope, config) :
                    print("        [VALID SLOPE] Angle within valid range.")
                    
                    print(f"        [FLAG] UPDATE LINE DATA 1: {line_name}")
                    update_line_data(line_name, "Bull", "active", highest_point)
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, breakout_type='bullish'
                        )
                else:
                    print("        [INVALID SLOPE] First point is later than second point.")
                    slope, intercept = None, None
            else:
                print("        [SLOPE] calculation failed or not applicable.")
        elif slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, breakout_type='bullish'
            )
        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, breakout_type='bullish'
            )
    
    elif ('support PDL' in candle['type']) or ('resistance Buffer' in candle['type']) or ('PDHL Buffer' in candle['type']):
        #now Lets work on Bear Candles, instead of Higher highs we will be looking at lower lows
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_low is None or candle['low'] < current_low:
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, breakout_type='bearish'
                )
            current_low = candle['low']
            lowest_point = (candle['candle_index'], current_low)
            print(f"        [Lowest Point] New: {lowest_point}")
            higher_lows = []
        else: 
            if candle['low'] == current_low and candle['candle_index'] > lowest_point[0]:
                lowest_point = (candle['candle_index'], current_low)
                print(f"        [Lowest Point] Updated: {current_low}")
                higher_lows = []
            else:
                higher_lows.append((candle['candle_index'], candle['low']))

        # This block calculates the slope and intercept for a potential flag, updating line data if valid points are found.
        if len(higher_lows) >= MIN_NUM_CANDLES and (slope is None or intercept is None):
            print(f"        [SLOPE] Calculating Slope Line...")
            slope, intercept = calculate_slope_intercept(higher_lows, lowest_point)
            if slope is not None:  # Add a check here
                if is_angle_valid(slope, config, bearish=True):
                    print("        [VALID SLOPE] Angle within valid range.")
                    
                    print(f"        [FLAG] UPDATE LINE DATA 2: {line_name}")
                    update_line_data(line_name, "Bear", "active", lowest_point)
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, breakout_type='bearish'
                        )
                else:
                    print("        [INVALID SLOPE] First point is later than second point.")
                    slope, intercept = None, None
            else:
                print("        [SLOPE] calculation failed or not applicable.")

        elif slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, breakout_type='bearish'
            )

        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, breakout_type='bearish'
            )
    else:
        print(f"        [No Support Candle] type = {candle}")    
    
    # Write the updated state back to the JSON file
    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)

    update_state(state_file_path, current_high, highest_point, lower_highs, current_low, lowest_point, higher_lows, slope, intercept, candle)

async def check_for_bearish_breakout(line_name, hl, higher_lows, lowest_point, slope, intercept, candle, config, session, headers):
    
    if slope and intercept is not None:
        trendline_y = slope * hl[0] + intercept

        if hl[1] < trendline_y:
            print(f"        [BREAKOUT] Potential Breakout Detected at {hl}")

            # Check if the candle associated with this higher low completely closes below the trendline
            if candle['close'] < trendline_y:
                success = await handle_breakout_and_order(
                    candle, trendline_y, line_name, hl[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear"
                )
                if success:
                    return None, None, True
            else:
                # Test new slope and intercept
                new_slope = (hl[1] - lowest_point[1]) / (hl[0] - lowest_point[0])
                new_intercept = lowest_point[1] - new_slope * lowest_point[0]
                if new_slope is not None and is_angle_valid(new_slope, config, bearish=True):
                    valid_breakout = True
                    for test_point in higher_lows:
                        if test_point[1] < new_slope * test_point[0] + new_intercept:
                            valid_breakout = False
                            break

                    if valid_breakout:
                        print(f"        [FLAG] UPDATE LINE DATA 4: {line_name}")
                        update_line_data(line_name, "Bear", "active", lowest_point, hl)
                        return new_slope, new_intercept, True
                    else:
                        print("        [INVALID BREAKOUT] Invalid breakout on new slope.")
                        return None, None, False
                else:
                    return None, None, False

        
        if candle['close'] < trendline_y:
            success = await handle_breakout_and_order(
                candle, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear", calculate_new_trendline=True, slope=slope, intercept=intercept
            )
            if success:
                return None, None, True
    return slope, intercept, False

async def check_for_bullish_breakout(line_name, lh, lower_highs, highest_point, slope, intercept, candle, config, session, headers):
    
    if slope and intercept is not None:
        #y = mx + b
        trendline_y = slope * lh[0] + intercept
        
        if lh[1] > trendline_y:
            print(f"        [BREAKOUT] Potential Breakout Detected at {lh}")
            # Check if the candle associated with this lower high closes over the slope intercept (trendline_y)
            if candle['close'] > trendline_y:
                success = await handle_breakout_and_order(
                    candle, trendline_y, line_name, lh[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull"
                )
                if success:
                    return None, None, True
            else:
                # Test new slope and intercept
                new_slope = (lh[1] - highest_point[1]) / (lh[0] - highest_point[0])
                new_intercept = highest_point[1] - new_slope * highest_point[0]

                if new_slope is not None and is_angle_valid(new_slope, config):
                    valid_breakout = True
                    for test_point in lower_highs:
                        # Check if any point is above the new trendline
                        if test_point[1] > new_slope * test_point[0] + new_intercept:
                            valid_breakout = False
                            #break

                    if valid_breakout:
                        print(f"        [FLAG] UPDATE LINE DATA 6: {line_name}")
                        update_line_data(line_name, "Bull", "active", highest_point, lh)
                        return new_slope, new_intercept, True
                    else:
                        print("        [INVALID BREAKOUT] Invalid breakout on new slope.")
                        return None, None, False
                else:
                    return None, None, False
        #this is incase the candle is the one that breaks above the whole trendline, making a new highest high
        if candle['close'] > trendline_y:
            success = await handle_breakout_and_order(
                candle, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull", calculate_new_trendline=True, slope=slope, intercept=intercept
            )
            if success:
                return None, None, True
    return slope, intercept, False

async def process_breakout_detection(line_name, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers, breakout_type='bullish'):
    """
    Processes breakout detection for given points.

    Args:
        line_name (str): The name of the line or flag being processed.
        points (list): A list of points (lower highs or higher lows) to check for breakouts.
        highest_or_lowest_point (tuple): The highest or lowest point related to the flag.
        slope (float): The slope of the trendline.
        intercept (float): The intercept of the trendline.
        candle (dict): The current candle being processed.
        config (dict): Configuration settings.
        session: The HTTP session.
        headers: HTTP headers for requests.
        breakout_type (str): 'bullish' or 'bearish' to determine the type of breakout to check.

    Returns:
        tuple: Updated slope, intercept, and a boolean indicating if a breakout was detected.
    """
    breakout_detected = False
    for point in points:
        if breakout_type == 'bullish':
            slope, intercept, detected = await check_for_bullish_breakout(
                line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers
            )
        else:  # 'bearish'
            slope, intercept, detected = await check_for_bearish_breakout(
                line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers
            )
        if detected:
            breakout_detected = True
            print(f"        [Breakout Detected] {line_name} detected a {breakout_type} breakout at {point}")
            break  # Optional: break if you only care about the first detected breakout
    return slope, intercept, breakout_detected

async def above_below_ema(state):
    # This will return true or false, state has to be either 'above' or 'below'
    # It will get an instant price of what the stock is trading at
    # Then it will see if the price is above or below the EMAs.
    # The state tells us what we're looking for

    # Get current price
    price = await get_current_price(SYMBOL)

    # Access EMAs.json, get the last EMA values
    EMAs = load_json_df('EMAs.json')
    last_EMA = EMAs.iloc[-1]
    last_EMA_dict = last_EMA.to_dict()
    print(f"        [EMA] Last EMA Values: {last_EMA_dict}, Price: {price}")
    # Check if price is above or below the EMAs
    for ema in last_EMA_dict:
        if ema != 'x':  # Assuming 'x' is not an EMA value but an index or timestamp
            if state == 'above' and price <= last_EMA_dict[ema]:
                return False
            if state == 'below' and price >= last_EMA_dict[ema]:
                return False

    return True

def check_valid_points(line_name):
    line_data_path = Path('line_data.json')
    if line_data_path.exists():
        with open(line_data_path, 'r') as file:
            line_data = json.load(file)
            for flag in line_data:
                if flag['name'] == line_name:
                    # Check and print point_1's x, y if available
                    point_1 = flag.get('point_1')
                    if point_1:
                        print(f"        [LINE CHECK] Point 1: x={point_1.get('x')}, y={point_1.get('y')}")
                    else:
                        print("        [LINE CHECK] Point 1: None")

                    # Check and print point_2's x, y if available
                    point_2 = flag.get('point_2')
                    if point_2:
                        print(f"        [LINE CHECK] Point 2: x={point_2.get('x')}, y={point_2.get('y')}")
                    else:
                        print("        [LINE CHECK] Point 2: None")

                    # Ensure both point_1 and point_2 exist and have non-null x and y
                    point_1_valid = point_1 and point_1.get('x') is not None and point_1.get('y') is not None
                    point_2_valid = point_2 and point_2.get('x') is not None and point_2.get('y') is not None
                    
                    return point_1_valid, point_2_valid
    return False

async def handle_breakout_and_order(candle, trendline_y, line_name, point, session, headers, is_real_money, symbol, line_type, calculate_new_trendline=False, slope=None, intercept=None):
    """
    Handle the breakout logic and conditional order execution, with an optional calculation of a new trendline.

    Args:
    - candle: The current candle data.
    - trendline_y: The y-value of the trendline at the x-position of the current candle.
    - line_name: The name of the line associated with the current analysis.
    - point: The point associated with the current breakout analysis. Can be lh or candle['candle_index'] based on the context.
    - session: The aiohttp client session for making HTTP requests.
    - headers: HTTP request headers.
    - is_real_money: Boolean indicating if real money trading is activated.
    - symbol: The trading symbol.
    - line_type: 'Bull' for bullish breakouts or 'Bear' for bearish breakouts.
    - calculate_new_trendline: Boolean indicating if a new trendline calculation is needed based on the current candle.
    - slope: The slope of the trendline (required if calculate_new_trendline is True).
    - intercept: The intercept of the trendline (required if calculate_new_trendline is True).
    """

    # Calculate new trendline if required, needed for both line types
    if calculate_new_trendline and slope is not None and intercept is not None:
        trendline_y = slope * point + intercept  # Recalculate trendline_y with new slope and intercept
    
    print(f"        [FLAG] UPDATE LINE DATA: {line_name}")
    update_line_data(line_name=line_name, line_type=line_type, status="active", point_2=(point, trendline_y))
    
    if line_type == 'Bull':
        condition_met = await above_below_ema('above')
    else:  # 'Bear'
        condition_met = await above_below_ema('below')

    vp_1, vp_2 = check_valid_points(line_name) #vp means valid point

    print(f"        [CONDITIONS] {condition_met}, {vp_1}, {vp_2}")
    if condition_met and vp_1 and vp_2:
        action = 'call' if line_type == 'Bull' else 'put'
        print(f"    [ORDER CONFIRMED] Buy Signal ({action.upper()})")
        await buy_option_cp(is_real_money, symbol, action, session, headers)
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return True
    else:
        reason = "Not above EMAs" if not condition_met else "Invalid points"
        action = 'CALL' if line_type == 'Bull' else 'PUT'
        print(f"    [ORDER CANCELED] Buy Signal ({action}); {reason}.")
        #if any of the vp_1 or vp_2 are false, don't go through. but if vp_1 and vp_2 are both true and not condition_met is true then go through
        if not condition_met and vp_1 and vp_2:
            update_line_data(line_name=line_name, line_type=line_type, status="complete") #test this out next day to see if this fixes the wait-until above/below emas to buy error.
        return False
    
def calculate_slope_intercept(lower_highs, highest_point):
    # Calculate slope (m) and intercept (c)
    # Get the latest in the list [1,0,-1] each one is a X,Y coordinate
    latest_lower_high = lower_highs[-1]
    # Ensure the first point's X value is less than the second point's X value
    if highest_point[0] < latest_lower_high[0]:
        #slope formula: m = (y2 - y1) / (x2 - x1)
        slope = (latest_lower_high[1] - highest_point[1]) / (latest_lower_high[0] - highest_point[0])
        #rearrangement of the slope-intercept form: c = y − mx 
        intercept = highest_point[1] - slope * highest_point[0]
        print(f"        [VALID SLOPE] Slope: {slope}, Intercept: {intercept}")
        return slope, intercept
    else:
        print("        [INVALID POINTS] First point is later than second point.")
        return None, None

def update_state(state_file_path, current_high, highest_point, lower_highs, current_low, lowest_point, higher_lows, slope, intercept, candle):
    with open(state_file_path, 'r') as file:
        state = json.load(file)

    state['current_high'] = current_high
    state['highest_point'] = highest_point

    # Create a new list for lower_highs based on the condition
    new_lower_highs = [tuple(lh) for lh in lower_highs if lh[0] > highest_point[0]]
    # Update lower_highs if there are new values, otherwise empty the list
    if new_lower_highs:
        unique_new_lower_highs = set(new_lower_highs)
        state['lower_highs'] = list(unique_new_lower_highs)
    else:
        state['lower_highs'] = []

    state['current_low'] = current_low
    state['lowest_point'] = lowest_point

    # Create a new list for higher_lows based on the condition
    new_higher_lows = [tuple(hl) for hl in higher_lows if hl[0] > lowest_point[0]]
    # Update higher_lows if there are new values, otherwise empty the list
    if new_higher_lows:
        unique_new_higher_lows = set(new_higher_lows)
        state['higher_lows'] = list(unique_new_higher_lows)
    else:
        state['higher_lows'] = []

    state['slope'] = slope
    state['intercept'] = intercept

    # Add the current candle to previous_candles, avoiding duplicates
    if candle['candle_index'] not in [c['candle_index'] for c in state['previous_candles']]:
        state['previous_candles'].append(candle)

    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)

def restart_state_json(state_file_path, havent_cleared):
    """
    Initializes or resets the state.json file to default values.

    Parameters:
    state_file_path (str): The file path for the state.json file.
    """
    initial_state = {
        'current_high': None,
        'highest_point': None,
        'lower_highs': [],
        'current_low': None,
        'lowest_point': None,
        'higher_lows': [],
        'slope': None,
        'intercept': None,
        'previous_candles': []
    }
    if havent_cleared:
        with open(state_file_path, 'w') as file:
            json.dump(initial_state, file, indent=4)
        print("    [RESET] State JSON file has been reset to initial state.")

def is_angle_valid(slope, config, bearish=False):
    """
    Calculates the angle of the slope and checks if it is within the valid range specified in the config.
    
    Parameters:
    slope (float): The slope of the line.
    config (dict): Configuration dictionary containing angle criteria.

    Returns:
    bool: True if the angle is within the valid range, False otherwise.
    """
    angle = math.atan(slope) * (180 / math.pi)
    
    if bearish:
        min_angle = config["FLAGPOLE_CRITERIA"]["BEAR_MIN_ANGLE"]
        max_angle = config["FLAGPOLE_CRITERIA"]["BEAR_MAX_ANGLE"]
    else:
        min_angle = config["FLAGPOLE_CRITERIA"]["BULL_MIN_ANGLE"]
        max_angle = config["FLAGPOLE_CRITERIA"]["BULL_MAX_ANGLE"]

    print(f"        [Slope Angle] {angle} degrees for {'Bear' if bearish else 'Bull'} flag")
    return min_angle <= angle <= max_angle

def resolve_flags(json_file='line_data.json'):
    
    # Load the flags from JSON file
    line_data_path = Path(json_file)
    if line_data_path.exists():
        with open(line_data_path, 'r') as file:
            line_data = json.load(file)
    else:
        print(f"    [FLAG ERROR] File {json_file} not found.")
        return

    # Iterate through the flags and resolve opposite flags
    updated_line_data = []
    for flag in line_data:
        #edit this part to take into account null values
        if flag['type'] and flag['status'] == 'active':
            # Mark as complete or remove the flag based on your strategy
            is_point_1_valid = flag['point_1']['x'] is not None and flag['point_1']['y'] is not None
            is_point_2_valid = flag['point_2']['x'] is not None and flag['point_2']['y'] is not None
                
            if is_point_1_valid and is_point_2_valid:
                flag['status'] = 'complete' #mark complete so its no longer edited
                updated_line_data.append(flag)
                print("    [FLAG] Active flags resolved.")
            # Skip adding the flag to updated_line_data if it's active and has invalid points
        else:
            updated_line_data.append(flag)

    # Save the updated data back to the JSON file
    with open(line_data_path, 'w') as file:
        json.dump(updated_line_data, file, indent=4)

#right now i have real_money_activated == false
async def buy_option_cp(real_money_activated, ticker_symbol, cp, session, headers):
    # Extract previous option type from the unique_order_id
    unique_order_id, current_order_active = get_unique_order_id_and_is_active()
    prev_option_type = unique_order_id.split('-')[1] if unique_order_id else None

    # Check if there's an active order of the same type
    if current_order_active and prev_option_type == cp:
        print(f"Canceling buy Order, same order type '{cp}' is already active.")
        return
    elif current_order_active and prev_option_type != cp:
        # Sell the current active order if it's of a different type
        await sell_rest_of_active_order(message_ids_dict, "Switching option type.")

    try:
        bid = None
        side = "buy_to_open"
        order_type = "market"  # order_type = "limit" if bid else "market"
        expiration_date = get_expiration("not specified")
        strike_price, strike_ask_bid = await find_what_to_buy(ticker_symbol, cp, NUM_OUT_MONEY, expiration_date, session, headers)
        #print(f"Strike, Price: {strike_price}, {strike_ask_bid}")
        
        quantity = calculate_quantity(strike_ask_bid, 0.1, 30)    
        #order math, making sure we have enough buying power to fulfill order
        if real_money_activated:
            buying_power = await get_account_balance(real_money_activated, bp=True)
        else:
            buying_power = get_papertrade_BP()
        commission_fee = 0.35
        buffer = 0.25
        strike_bid_cost = strike_ask_bid * 100 # 0.32 is actually 32$ when dealing with option contracts
        order_cost = (strike_bid_cost + commission_fee) * quantity
        order_cost_buffer = ((strike_bid_cost+buffer) + commission_fee) * quantity
        f_order_cost = "{:,.2f}".format(order_cost) # 'f_' means formatted
        f_order_cost_buffer = "{:,.2f}".format(order_cost_buffer) # formatted
        #print(f"order_cost_buffer: {order_cost_buffer}\nbuying_power: {buying_power}")

        # If contract cost more than what buying power we
        # have left, cancel the buy and send discord message.
        if order_cost_buffer >= buying_power:
            message = f"""
**NOT ENOUGH BUYING POWER LEFT**
-----
Canceling Order for Strategy: 
**{STRATEGY_NAME}**
-----
**Buying Power:** ${buying_power}
**Order Cost Buffer:** ${f_order_cost_buffer}
Order Cost Buffer exceded BP
-----
**Strike Price:** {strike_price}
**Option Type:** {cp}
**Quantity:** {quantity} contracts
**Price:** ${strike_ask_bid}
**Total Cost:** ${f_order_cost}
"""
            await print_discord(message)
            return

        if strike_price is None:
            # If no appropriate strike price found, cancel the buy operation
            await print_discord(f"**Appropriate strike was not found**\nstrike_price = None, Canceling buy.\n(Since not enough info)")
            return

        if real_money_activated: 
            #stuff...
            order_result = await submit_option_order(real_money_activated, ticker_symbol, strike_price, cp, bid, expiration_date, quantity, side, order_type)
            if order_result:
                await add_markers("buy")
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                unique_order_ID, order_bid_entry_price, order_quantity = await get_order_status(STRATEGY_NAME, real_money_activated, order_result['order_id'], "buy", ticker_symbol, cp, strike_price, expiration_date, timestamp, message_ids_dict)

                # Whenever you decide to start managing an active order
                # send orders to active order script, to constantly read
                active_order = {# Your active order details
                    'order_id': unique_order_ID,
                    'order_retrieval': order_result['order_id'],
                    'entry_price': order_bid_entry_price,
                    'quantity': order_quantity,
                    'partial_exits': []
                }

                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_order(active_order, message_ids_dict))
                if task.done():
                    print("Task completed.")
        else:
            active_order = await submit_option_order_v2(STRATEGY_NAME, ticker_symbol, strike_price, cp, expiration_date, session, headers, message_ids_dict, buying_power)
            if active_order is not None:
                await add_markers("buy")
                order_cost = (active_order["entry_price"] * 100) * active_order["quantity"]
                used_buying_power[active_order['order_id']] = order_cost
                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_fake_order(active_order, message_ids_dict))
                if task.done():
                    print("Task completed.")
            else:
                print("Canceled Trade")

    except Exception as e:
        await error_log_and_discord_message(e, "tll_trading_strategy", "buy_option_cp")

def clear_priority_candles(havent_cleared, type_candle, json_file='priority_candles.json'):
    if havent_cleared:
        with open(json_file, 'w') as file:
            json.dump([], file, indent=4)
        print(f"    [RESET] {json_file}; what_type_of_candle = {type_candle}")
        havent_cleared = False

async def record_priority_candle(candle, type_candles, json_file='priority_candles.json'):
    # Load existing data or initialize an empty list
    try:
        with open(json_file, 'r') as file:
            candles_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        candles_data = []

    current_candle_index = get_current_candle_index()

    # Append the new candle data along with its type
    candle_with_type = candle.copy()
    candle_with_type['type'] = type_candles
    candle_with_type['candle_index'] = current_candle_index
    candles_data.append(candle_with_type)

    # Save updated data back to the file
    with open(json_file, 'w') as file:
        json.dump(candles_data, file, indent=4)

def count_flags_in_json(json_file='line_data.json'):
    try:
        with open(json_file, 'r') as file:
            lines = json.load(file)
            # Count only those flags with a status of 'complete'
            complete_flags = [line for line in lines if line.get('status') == 'complete']
            return len(complete_flags)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0  # Return 0 if file doesn't exist or is empty
    
def update_line_data(line_name, line_type, status=None, point_1=None, point_2=None, json_file='line_data.json'):
    try:
        with open(json_file, 'r') as file:
            lines = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        lines = []

    # Find the line with the same name, if it exists
    existing_line = next((line for line in lines if line['name'] == line_name), None)
    
    if existing_line:
        # Update existing line with new values if provided, else keep old values
        existing_line['type'] = line_type  # Assuming you always want to update the type
        if status is not None:
            existing_line['status'] = status
        if point_1 is not None:
            existing_line['point_1'] = {"x": point_1[0], "y": point_1[1]}
        if point_2 is not None:
            existing_line['point_2'] = {"x": point_2[0], "y": point_2[1]}
    else:
        # Create a new line data entry with provided values or defaults
        new_line_data = {
            "name": line_name,
            "type": line_type,
            "status": status if status is not None else "active",
            "point_1": {"x": point_1[0], "y": point_1[1]} if point_1 else {"x": None, "y": None},
            "point_2": {"x": point_2[0], "y": point_2[1]} if point_2 else {"x": None, "y": None}
        }
        lines.append(new_line_data)

    with open(json_file, 'w') as file:
        json.dump(lines, file, indent=4)