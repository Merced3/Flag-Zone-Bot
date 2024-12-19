# tll_trading_strategy.py, meaning 'Temporal Lattice Leap Trading Strategy'
import os
from chart_visualization import update_2_min
import json
import asyncio
from datetime import datetime, timedelta, time
from buy_option import buy_option_cp
from economic_calender_scraper import check_order_time_to_event_time
from order_handler import get_profit_loss_orders_list, sell_rest_of_active_order
from error_handler import error_log_and_discord_message
from data_acquisition import get_current_candle_index, calculate_save_EMAs, get_candle_data_and_merge, above_below_ema, load_json_df, read_last_n_lines, load_message_ids, check_order_type_json, add_candle_type_to_json, determine_order_cancel_reason, initialize_ema_json, restart_state_json, record_priority_candle, clear_priority_candles, update_state, check_valid_points, is_angle_valid, resolve_flags, count_flags_in_json, log_order_details, candle_zone_handler, candle_ema_handler, candle_close_in_zone, start_new_flag_values, restart_flag_data, reset_json
from pathlib import Path
import pytz
import cred
import aiohttp

STRATEGY_NAME = "FLAG/ZONE STRAT"

STRATEGY_DESCRIPTION = """
Desctiption: 
    1) We wait until candle breaks out of a zone, that zone dictates if we use bear or bull flags.
    2) When we break out of those flags, we check if were above or below all the emas. if were not, we do not buy
    3) If evreything checks out, we buy and use the 13ema as trailing stoploss and we trim along the way up.
"""

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
OPTION_EXPIRATION_DTE = config["OPTION_EXPIRATION_DTE"]
EMA_MAX_DISTANCE = config["EMA_MAX_DISTANCE"]
MINS_BEFORE_MAJOR_NEWS_ORDER_CANCELATION = config["MINS_BEFORE_MAJOR_NEWS_ORDER_CANCELATION"]
TRADE_IN_BUFFERS = config["TRADE_IN_BUFFERS"]
START_POINT_MAX_NUM_FLAGS = config["FLAGPOLE_CRITERIA"]["START_POINT_MAX_NUM_FLAGS"]

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
    
new_york_tz = pytz.timezone('America/New_York')

MARKET_CLOSE = time(16, 0)
MARKET_OPEN = time(9, 30)

def get_market_open_time():
    today = datetime.now(new_york_tz).date()
    market_open_time = datetime.combine(today, time(9, 30))
    return new_york_tz.localize(market_open_time)


async def execute_trading_strategy(zones):
    print("Starting execute_trading_strategy()...")
    global last_processed_candle
    message_ids_dict = load_message_ids()
    print("message_ids_dict: ", message_ids_dict)

    candle_list = []  # Stores candles for the first 15 minutes
    MARKET_OPEN_TIME = get_market_open_time()  # Get today's market open time
    market_open_plus_15 = MARKET_OPEN_TIME + timedelta(minutes=15)
    market_open_plus_15 = market_open_plus_15.time()

    restart_state_json(True)

    # Wait for the simulation to start and populate data
    while True:
        await asyncio.sleep(0.5)  # Check every half second
        f_candle = read_last_n_lines(LOG_FILE_PATH, 1)
        if f_candle:
            print(f"    [ETS INFO] First candle processed: {f_candle[0]}")
            break

    #Testing While Running: 'resistance PDH' or 'support Buffer' or "support_1 Buffer"
    what_type_of_candle = candle_zone_handler(f_candle[0], None, zones, True)
    print(f"    [ETS INFO] what_type_of_candle = {what_type_of_candle}\n\n")

    last_processed_candle = None
    has_calculated_emas = False #TODO False
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
                    await sell_rest_of_active_order("Market closing soon. Exiting all positions.")
                    todays_profit_loss = sum(get_profit_loss_orders_list()) #returns todays_orders_profit_loss_list
                    end_of_day_account_balance = ACCOUNT_BALANCE[0] + todays_profit_loss
                    print(f"ACCOUNT_BALANCE[0]: {ACCOUNT_BALANCE[0]}, todays_profit_loss: {todays_profit_loss}\nend_of_day_account_balance: {end_of_day_account_balance}")
                    
                    with open(config_path, 'r') as f: # Read existing config
                        config = json.load(f)
                    config["ACCOUNT_BALANCES"][1] = end_of_day_account_balance # Update the ACCOUNT_BALANCES
                    with open(config_path, 'w') as f: # Write back the updated config
                        json.dump(config, f, indent=4)  # Using indent for better readability
                    restart_state_json(True)
                    break

                current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)  # Read the latest candle
                if current_last_candle and current_last_candle != last_processed_candle:
                    last_processed_candle = current_last_candle
                    #get that candle, look at its OHLC values
                    candle = last_processed_candle[0]
                    
                    # TODO: Calculate/Save EMAs
                    if current_time >= market_open_plus_15:
                        # At this point, we finalize the EMA calculations and stop resetting with each new candle.
                        if not has_calculated_emas and candle_list:
                            # Perform final fetch and merge to cover all premarket and aftermarket data
                            await get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, AM, PM, merged_file_name)
                            reset_json('EMAs.json', [])
                            # Calculate EMAs for the candle list accumulated until the 15-minute mark
                            for _candle in reversed(candle_list):
                                index_val_in_list = len(candle_list) - candle_list.index(_candle) - 1
                                await calculate_save_EMAs(_candle, index_val_in_list)

                            # Calculate EMA for the current candle after processing the list
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated final EMA list")
                            has_calculated_emas = True

                        elif has_calculated_emas:
                            # After market open + 15 mins, continue calculating EMA for new candles
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA candle")
                    else:
                        # Before market_open_plus_15, calculate EMA with a continuously updated candle list
                        candle_list.append(candle)
                        has_calculated_emas = False

                        # Delete and recreate the CD_PM and merged files
                        if os.path.exists(premarket_file):
                            os.remove(premarket_file)
                        if os.path.exists(merged_file_name):
                            os.remove(merged_file_name)

                        # Create PD_AM and CD_PM, then merge them, re-adding the candle list each time
                        await get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, AM, PM, merged_file_name)

                        # Clear EMAs.json file for a clean slate
                        with open('EMAs.json', 'w') as f:
                            json.dump([], f)

                        # Add candles from the candle list to the merged file and recalculate EMAs
                        for _candle in reversed(candle_list):
                            index_val_in_list = len(candle_list) - candle_list.index(_candle) - 1
                            await calculate_save_EMAs(_candle, index_val_in_list)

                        print(f"    [EMA] Calculated temporary EMA for first 15 min candle list with {len(candle_list)} candles.")

                    #Handle the zones
                    what_type_of_candle = candle_zone_handler(candle, what_type_of_candle, zones, False)
                    # Handle the candle bull or bear setup with EMA's
                    bull_or_bear_candle = candle_ema_handler(candle)
                    # Handle if close in zone
                    is_in_zone = candle_close_in_zone(candle, zones) # is or isn't in zones
                    able_to_buy = not is_in_zone # if so, don't buy inside zones

                    if bull_or_bear_candle is not None:
                        #record the candle data
                        await record_priority_candle(candle, what_type_of_candle, bull_or_bear_candle)
                        priority_candles = load_json_df('priority_candles.json')
                        num_flags = count_flags_in_json()
                        last_candle = priority_candles.iloc[-1]
                        last_candle_dict = last_candle.to_dict()
                        await identify_flag(last_candle_dict, num_flags, session, headers, what_type_of_candle, bull_or_bear_candle, able_to_buy)
                    else:
                        restart_flag_data(what_type_of_candle, bull_or_bear_candle)
                else:
                    await asyncio.sleep(1)  # Wait for new candle data
                    update_2_min() # i hate how this has to update every second just for the boxes to be garanteed to chow up...

        except Exception as e:
            await error_log_and_discord_message(e, "tll_trading_strategy", "execute_trading_strategy")

async def identify_flag(candle, num_flags, session, headers, what_type_of_candle, bull_or_bear_candle, able_to_buy = True):
    print(f"    [IDF Candle {candle['candle_index']}] OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")
    state_file_path = "state.json" 
    
    # Read the current state from the JSON file
    with open(state_file_path, 'r') as file:
        state = json.load(file)
    
    flag_counter = state.get('flag_counter', 0)
    start_point = state.get('start_point', None) # [X, Y, Y²]
    candle_points = state.get('candle_points', []) # [[X, Y, Y²], [X, Y, Y²], ...]
    # each point looks like this: [X, Y, Y²]
    #[X (candle index), Y (close or open), Y² (high or low)]
    #Y² means a second Y value, that we will use later on. 

    slope = state.get('slope', None)
    intercept = state.get('intercept', None)
    breakout_detected = None

    # Check if the 'zone_type' key exists in the candle dictionary
    if 'zone_type' in candle:
        line_name = f"flag_{num_flags}"
        candle_type = "bull" if bull_or_bear_candle == "bullish" else "bear"
        current_oc_high = candle['close'] if candle['close']>=candle['open'] else candle['open']
        current_oc_low = candle['close'] if candle['close']<=candle['open'] else candle['open']
            
        # flags for new starting points, bear and bull
        make_bull_starting_point = candle_type == "bull" and ((start_point is None or current_oc_high > start_point[1]) or (current_oc_high == start_point[1] and candle['candle_index'] > start_point[0]))
        make_bear_starting_point = candle_type == "bear" and ((start_point is None or current_oc_low < start_point[1]) or (current_oc_low == start_point[1]  and candle['candle_index'] > start_point[0]))
        print(f"    [IDF Markers] Bull: {make_bull_starting_point}, Bear: {make_bear_starting_point}")
        
        # settings new highs
        if make_bull_starting_point or make_bear_starting_point:
            # Checking if current candle is higher then whole flag, if it is, check if should buy
            if slope is not None and intercept is not None:
                print("    [IDF PBD 1] process_breakout_detection()")
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy, breakout_type=candle_type
                )
                
            start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle, bull_or_bear_candle)
                
        else:
            # 'oc' means Open or Close
            if bull_or_bear_candle == "bullish": # Bull candle list
                candle_oc = candle['open'] if candle['open']>=candle['close'] else candle['close']
                candle_points.append((candle['candle_index'], candle_oc, candle['high']))
            else:                                # Bear candle list
                candle_oc = candle['close'] if candle['close']<=candle['open'] else candle['open']
                candle_points.append((candle['candle_index'], candle_oc, candle['low']))
            # Organize the points into ascending order, where the X value is the indicator for the order
            candle_points = sorted(candle_points, key=lambda x: x[0])




        total_candles = 1 + len(candle_points) # the 1 represents 'start_point' since its the first canlde
        print(f"    [IDF] Total candles: {total_candles}")
        if total_candles >= MIN_NUM_CANDLES and (slope is None or intercept is None):
            
            print(f"    [IDF SLOPE] Calculating Slope Line 1...")
            slope, intercept, first_point, second_point = calculate_slope_intercept(candle_points, start_point, candle_type)
            
            angle_valid, angle = is_angle_valid(slope, config, bearish=(bull_or_bear_candle == "bearish"))
            print(f"    [IDF VALID SLOPE] Angle/Degree: {angle}")
            if angle_valid:
                print(f"    [IDF FLAG] UPDATE: {line_name}, active")
                line_type = "Bull" if bull_or_bear_candle == "bullish" else "Bear"
                update_line_data(line_name, line_type, "active", first_point, second_point)
            else:
                print(f"    [IDF INVALID SLOPE] Angle/Degree outside of range")
        elif slope is not None and intercept is not None:
            print("    [IDF PBD 2] process_breakout_detection()")
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy, breakout_type=candle_type
            )
            if not breakout_detected:
                slope, intercept, first_point, second_point = calculate_slope_intercept(candle_points, start_point, candle_type)
                angle_valid, angle = is_angle_valid(slope, config, bearish=(bull_or_bear_candle == "bearish"))
                if angle_valid:
                    print(f"    [IDF VALID SLOPE] Angle/Degree: {angle}")
                    line_type = "Bull" if bull_or_bear_candle == "bullish" else "Bear"
                    update_line_data(line_name, line_type, "active", first_point, second_point)
                else:
                    print(f"    [IDF INVALID SLOPE] Angle/Degree outside of range: {angle}")
                    start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle, bull_or_bear_candle)
            elif breakout_detected: 
                if flag_counter < START_POINT_MAX_NUM_FLAGS:
                    flag_counter = flag_counter +1
                    print(f"    [IDF] Forming flag {flag_counter} for current start_point.")
                else:
                    print(f"    [IDF] Maximum flags reached for start_point, resetting start_point and candle_points.")
                    start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle, bull_or_bear_candle)
    else:
        print(f"    [IDF No Support Candle] type = {what_type_of_candle}")    
    
    if not able_to_buy and breakout_detected:
        #broke out while inside zone.
        print(f"    [IDF] Breakout Detected and inside of zone.")
    
    # Write the updated state back to the JSON file
    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)
    print(f"    [IDF CANDLE DIR] {what_type_of_candle}, Flag Count: {flag_counter}")
    update_2_min()
    update_state(state_file_path, flag_counter, start_point, candle_points, slope, intercept)

async def process_breakout_detection(line_name, slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy, breakout_type='bull'):
    # Calculate trendline y-value using the translated line
    trendline_y = slope * candle['candle_index'] + intercept
    detected = False

    if breakout_type == 'bull':
        candle_oc = candle['open'] if candle['open'] >= candle['close'] else candle['close']
        if candle_oc > trendline_y:
            print(f"    [PBD Breakout Detected] {line_name} detected bullish breakout at {candle_oc}")
            # Handle the breakout
            slope, intercept, detected = await check_for_bullish_breakout(
                line_name, (candle['candle_index'], candle_oc, candle['high']), slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy
            )
    else:  # 'bearish'
        candle_oc = candle['close'] if candle['close'] <= candle['open'] else candle['open']
        if candle_oc < trendline_y:
            print(f"    [PBD Breakout Detected] {line_name} detected bearish breakout at {candle_oc}")
            # Handle the breakout
            slope, intercept, detected = await check_for_bearish_breakout(
                line_name, (candle['candle_index'], candle_oc, candle['low']), slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy
            )
    
    return slope, intercept, detected

async def check_for_bearish_breakout(line_name, point, slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy):
    
    if slope and intercept is not None:
        trendline_y = slope * point[0] + intercept

        if point[1] < trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {point}")

            # Check if the candle associated with this higher low completely closes below the trendline
            if candle['close'] < trendline_y and candle['close'] <= candle['open']:
                success = await handle_breakout_and_order(
                    what_type_of_candle, trendline_y, line_name, point[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear", able_to_buy=able_to_buy
                )
                if success:
                    return slope, intercept, True
                else:
                    print(f"            [CFBB TRUE BREAKOUT 1] Condition Failure")
                    update_line_data(line_name=line_name, line_type="Bear", status="complete")
                    return slope, intercept, True
            else:
                # Test new slope and intercept
                print(f"            [CFBB BREAKOUT] Failed, Went up at {point}")
                return slope, intercept, False
        
        if candle['close'] < trendline_y and candle['close'] <= candle['open']:
            print(f"            [CFBB BREAKOUT 2] Closed under from {trendline_y} at {candle['close']}")
            success = await handle_breakout_and_order(
                what_type_of_candle, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear", calculate_new_trendline=True, slope=slope, intercept=intercept, able_to_buy=able_to_buy
            )
            if success:
                return None, None, True
            else:
                print(f"            [CFBB TRUE BREAKOUT 2] Condition Failure")
                update_line_data(line_name=line_name, line_type="Bear", status="complete")
                return None, None, True
    return slope, intercept, False

async def check_for_bullish_breakout(line_name, point, slope, intercept, candle, session, headers, what_type_of_candle, able_to_buy):
    if slope and intercept is not None:
        #y = mx + b
        trendline_y = slope * point[0] + intercept
        
        if point[1] > trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {point}")
            # Check if the candle associated with this lower high closes over the slope intercept (trendline_y)
            if candle['close'] > trendline_y and candle['open'] <= candle['close']:
                print(f"            [CFBB BREAKOUT 1] Closed over from {trendline_y} at {candle['close']}; {candle['open']}")
                success = await handle_breakout_and_order(
                    what_type_of_candle, trendline_y, line_name, point[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull", able_to_buy=able_to_buy
                )
                if success:
                    return slope, intercept, True
                else:
                    print(f"            [CFBB TRUE BREAKOUT 3] Condition Failure")
                    update_line_data(line_name=line_name, line_type="Bull", status="complete")
                    return slope, intercept, True
            else:
                # Test new slope and intercept
                print(f"            [CFBB BREAKOUT] Failed, Went down at {point}")
                return slope, intercept, False
        
        #this is incase the candle is the one that breaks above the whole trendline, making a new highest high
        if candle['close'] > trendline_y and candle['open'] <= candle['close']:
            print(f"            [CFBB BREAKOUT 2] Closed over from {trendline_y} at {candle['close']}")
            success = await handle_breakout_and_order(
                what_type_of_candle, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull", calculate_new_trendline=True, slope=slope, intercept=intercept, able_to_buy=able_to_buy
            )
            if success:
                return slope, intercept, True
            else:
                print(f"            [CFBB BREAKOUT 4] Condition Failure")
                update_line_data(line_name=line_name, line_type="Bull", status="complete")
                return slope, intercept, True
    return slope, intercept, False

async def handle_breakout_and_order(what_type_of_candle, trendline_y, line_name, candle_x, session, headers, is_real_money, symbol, line_type, calculate_new_trendline=False, slope=None, intercept=None, able_to_buy=True):

    # Calculate new trendline if required, needed for both line types
    if calculate_new_trendline and slope is not None and intercept is not None:
        trendline_y = slope * candle_x + intercept  # Recalculate trendline_y with new slope and intercept
        print(f"                [HBAO TRENDLINE] UPDATE: {trendline_y}")
    
    print(f"                [HBAO FLAG] UPDATE 1: {line_name}, active")
    update_line_data(line_name=line_name, line_type=line_type, status="active", point_2=(candle_x, trendline_y))

    # Before we check anythin, lets see if were in the zones/boxes, AKA 'able_to_buy'
    if not able_to_buy:
        print(f"                [HBAO ORDER CANCELED] Order is in Zone. UPDATE 2: {line_name}, complete")
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return False
    
    #Check emas
    if line_type == 'Bull':
        ema_condition_met, ema_price_distance_met, ema_distance = await above_below_ema('above', EMA_MAX_DISTANCE)
    else:  # 'Bear'
        ema_condition_met, ema_price_distance_met, ema_distance = await above_below_ema('below', EMA_MAX_DISTANCE)

    #check if points are valid
    vp_1, vp_2, line_degree_angle, correct_flag = check_valid_points(line_name, line_type) #vp means valid point

    # Check if trade limits have been reached in this zone
    multi_order_condition_met, num_of_matches = check_order_type_json(what_type_of_candle)

    # Check if trade time is aligned with economic events
    time_result = check_order_time_to_event_time(MINS_BEFORE_MAJOR_NEWS_ORDER_CANCELATION)

    print(f"                [HBAO CONDITIONS] {ema_condition_met}, {vp_1}, {vp_2}, {multi_order_condition_met}, {ema_price_distance_met}, {time_result}")
    if ema_condition_met and vp_1 and vp_2 and multi_order_condition_met and ema_price_distance_met and time_result and correct_flag: # if all conditions met, then authorize order, buy
        action = 'call' if line_type == 'Bull' else 'put'
        print(f"                [HBAO ORDER CONFIRMED] Buy Signal ({action.upper()})")
        success, strike_price, quantity, entry_bid_price, order_cost = await buy_option_cp(is_real_money, symbol, action, session, headers, STRATEGY_NAME)
        if success: #incase order was canceled because of another active
            add_candle_type_to_json(what_type_of_candle)
            time_entered_into_trade = datetime.now().strftime("%m/%d/%Y-%I:%M %p") # Convert to ISO format string
            # Log order details
            log_order_details('order_log.csv', what_type_of_candle, time_entered_into_trade, ema_distance, num_of_matches, line_degree_angle, symbol, strike_price, action, quantity, entry_bid_price, order_cost)
        else:
            print(f"                [HBAO ORDER FAIL] Buy Signal ({action.upper()}), what_type_of_candle = {what_type_of_candle}")
        print(f"                [HBAO FLAG] UPDATE 2: {line_name}, complete")
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return True
    else:
        reason = determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, correct_flag, multi_order_condition_met, time_result)
        
        action = 'CALL' if line_type == 'Bull' else 'PUT'
        print(f"                [HBAO ORDER CANCELED] Buy Signal ({action}); {reason}.")
        #if any of the vp_1 or vp_2 are false, don't go through. but if vp_1 and vp_2 are both true and not ema_condition_met is true then go through
        if not ema_condition_met and vp_1 and vp_2: #and not multi_order_condition_met:
            print(f"                [HBAO FLAG] UPDATE 3: {line_name}, complete")
            update_line_data(line_name=line_name, line_type=line_type, status="complete") #test this out next day to see if this fixes the wait-until above/below emas to buy error.
        return False
    
def calculate_slope_intercept(points, start_point, flag_type="bull"):
    # Ensure the start_point is included in the points list
    if start_point not in points:
        points = [start_point] + points

    # making sure points are in order
    points = sorted(points, key=lambda x: x[0])

    # Calculate slope (m) using the linear regression formula
    n = len(points)
    sum_x = sum(point[0] for point in points)
    sum_y = sum(point[1] for point in points)
    sum_xy = sum(point[0] * point[1] for point in points)
    sum_x_squared = sum(point[0] ** 2 for point in points)
    
    # m = [n(Σxy) - (Σx)(Σy)] / [n(Σx²) - (Σx)²]
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x_squared - sum_x ** 2)
    
    # Calculate intercept: b = ȳ - m * x̄
    mean_x = sum_x / n
    mean_y = sum_y / n
    intercept = mean_y - slope * mean_x
    
    # Perform the translation to avoid the slope line cutting through the body of the candles
    if flag_type == "bull":
        intercept = max(point[1] - slope * point[0] for point in points)
    else:  # bear flag
        intercept = min(point[1] - slope * point[0] for point in points)

    first_new_Y = slope * start_point[0] + intercept    
    first_point = (start_point[0], first_new_Y)
    
    second_new_Y = slope * points[-1][0] + intercept 
    second_point = (points[-1][0], second_new_Y)

    return slope, intercept, first_point, second_point
    
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

    update_2_min()