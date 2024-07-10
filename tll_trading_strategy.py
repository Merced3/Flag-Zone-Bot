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
from data_acquisition import get_current_candle_index, calculate_save_EMAs, get_candle_data_and_merge, above_below_ema, load_json_df, read_last_n_lines, load_message_ids, check_order_type_json, add_candle_type_to_json, determine_order_cancel_reason, initialize_ema_json, restart_state_json, record_priority_candle, clear_priority_candles, update_state, check_valid_points, is_angle_valid, resolve_flags, count_flags_in_json
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
    already_cleared = False #TODO FALSE
    num_of_candles_in_zone = 0 #TODO 0
    prev_what_type_of_candle = what_type_of_candle
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
                    
                    # Calculate/Save EMAs
                    if current_time >= market_open_plus_15:
                        if not has_calculated_emas and candle_list:
                            await get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, AM, PM, merged_file_name) 
                            #i need to change this for loop
                            for _candle in reversed(candle_list):
                                index_val_in_list = len(candle_list) - candle_list.index(_candle) - 1
                                await calculate_save_EMAs(_candle, index_val_in_list)
                            #calculate the current candle after the list has been processed
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA list")
                            has_calculated_emas = True
                        elif not has_calculated_emas:
                            await get_candle_data_and_merge(aftermarket_file, premarket_file, candle_interval, candle_timescale, AM, PM, merged_file_name)
                            #if not candle_list:
                                # get candles if any in spy log
                                # if none in spy log then try and get as much 2 min candle stick data from polygon and add it to spy log
                                # then calculate the list of candles in list
                                # then once list is done calculating then calulate current candle
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA list")
                            has_calculated_emas = True
                        elif has_calculated_emas:
                            await calculate_save_EMAs(candle, get_current_candle_index())
                            print("    [EMA] Calculated EMA candle")
                    else:
                        candle_list.append(candle)
                        has_calculated_emas = False

                    #Handle the zones
                    what_type_of_candle = candle_zone_handler(candle, what_type_of_candle, zones, False)

                    if what_type_of_candle is not None:
                        #record the candle data
                        prev_what_type_of_candle = what_type_of_candle
                        await record_priority_candle(candle, what_type_of_candle)
                        priority_candles = load_json_df('priority_candles.json')
                        num_flags = count_flags_in_json()
                        last_candle = priority_candles.iloc[-1]
                        last_candle_dict = last_candle.to_dict()
                        await identify_flag(last_candle_dict, num_flags, session, headers, what_type_of_candle)
                        already_cleared = False
                        num_of_candles_in_zone = 0
                    else:
                        #clear_priority_candles(havent_cleared, what_type_of_candle)
                        if not already_cleared and prev_what_type_of_candle is not None:
                            await record_priority_candle(candle, prev_what_type_of_candle)
                            priority_candles = load_json_df('priority_candles.json')
                            num_flags = count_flags_in_json()
                            last_candle = priority_candles.iloc[-1]
                            last_candle_dict = last_candle.to_dict()
                            should_reset = await identify_flag(last_candle_dict, num_flags, session, headers, prev_what_type_of_candle, False)
                            if should_reset:
                                print(f"    [ETS RESET] flag state variables, waiting for new candle to come out of zone")
                                prev_what_type_of_candle = None
                                num_of_candles_in_zone = 0
                                already_cleared = True
                            else:
                                num_of_candles_in_zone += 1
                                print(f"    [ETS Candles In Zone] {num_of_candles_in_zone}")
                        if not already_cleared and num_of_candles_in_zone > MIN_NUM_CANDLES: # How many candles it should ignore before restarting the whole state/priority json files
                            restart_flag_data(what_type_of_candle)
                            prev_what_type_of_candle = None
                            num_of_candles_in_zone = 0
                            already_cleared = True
                else:
                    await asyncio.sleep(1)  # Wait for new candle data

        except Exception as e:
            await error_log_and_discord_message(e, "tll_trading_strategy", "execute_trading_strategy")

def candle_zone_handler(candle, type_of_candle, boxes, first_candle = False):
    if boxes:
        for box_name, (x_pos, high_low_of_day, buffer) in boxes.items(): 
            # Determine zone type
            zone_type = "support" if "support" in box_name else "resistance" if "resistance" in box_name else "PDHL"
            PDH_or_PDL = high_low_of_day  # PDH for resistance, PDL for support
            box_top = PDH_or_PDL if zone_type in ["resistance", "PDHL"] else buffer  # PDH or Buffer as top for resistance/PDHL
            box_bottom = buffer if zone_type in ["resistance", "PDHL"] else PDH_or_PDL  # Buffer as bottom for resistance/PDHL
            check_is_in_another_zone = True
            action = None # Initialize action to None or any default value
            # Check if the candle shoots through the zone
            if candle['open'] < box_bottom:
                if candle['close'] > box_top:
                    # Candle shoots up through the zone
                    action = "[START 1]" # CALLS
                    candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
                    check_is_in_another_zone = True
                elif box_bottom < candle['close'] < box_top:
                    # Went up, closed Inside of box
                    action = '[END 2]'
            elif candle['open'] > box_top:
                if candle['close'] < box_bottom:
                    # Candle shoots down through the zone
                    action = "[START 3]" # PUTS
                    candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                    check_is_in_another_zone = True
                elif box_top > candle['close'] > box_bottom:
                    #went down, closed Inside of box
                    action = "[END 4]"
            elif candle['close'] > box_top and candle['open'] <= box_top:
                # Candle closes above the zone, potentially starting an upward trend
                action = "[START 5]" # CALLS
                candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
            elif candle['close'] < box_bottom and candle['open'] >= box_bottom:
                # Candle closes below the zone, potentially starting a downward trend
                action = "[START 6]" # PUTS
                candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                            
            
            # I only want this to run on the first candle
            if 'PDHL' in box_name and first_candle: 
                # Above zone
                if candle['open'] > box_top and candle['close'] > box_top:
                    # whole candle is above zone
                    candle_type = "PDH"
                    action = "[START 8]"
                elif candle['open'] < box_top and candle['close'] > box_top:
                    # candle is coming out above zone
                    candle_type = "PDH"
                    action = "[START 9]"
                
                # Below zone
                if candle['open'] < box_bottom and candle['close'] < box_bottom:
                    # whole candle is below zone
                    candle_type = "PDL"
                    action = "[START 10]"
                if candle['open'] > box_bottom and candle['close'] < box_bottom:
                    # candle is coming out below zone
                    candle_type = "PDL"
                    action = "[START 11]"
                check_is_in_another_zone = True

            if check_is_in_another_zone:
                # Additional checks to refine action based on closing inside any other zone
                for other_box_name, (_, other_high_low_of_day, other_buffer) in boxes.items():
                    if other_box_name != box_name:  # Ensure we're not checking the same zone
                        other_box_top = other_high_low_of_day if "resistance" in other_box_name or "PDHL" in other_box_name else other_buffer
                        other_box_bottom = other_buffer if "resistance" in other_box_name or "PDHL" in other_box_name else other_high_low_of_day
                                        
                        # Check if the candle closed inside this other zone
                        if other_box_bottom <= candle['close'] <= other_box_top:
                            # Modify action to [END #] since we closed inside of another zone
                            action = "[END 7]"
                            #print(f"    [MODIFIED ACTION] Candle closed inside another zone ({other_box_name}), changing action to {action}.")
                            break  # Exit the loop since we've found a zone that modifies the action
            
            if action:
                what_type_of_candle = f"{box_name} {candle_type}" if "START" in action else None
                #havent_cleared = True if what_type_of_candle is not None else False
                print(f"    [INFO] {action} what_type_of_candle = {what_type_of_candle}")
                return what_type_of_candle 
    else:
        print("    [CZH] No Boxes were found...")        
    if type_of_candle is not None:
        return type_of_candle

def restart_flag_data(what_type_of_candle):
    clear_priority_candles(True, what_type_of_candle)
    restart_state_json(True)
    resolve_flags()        

async def reset_flag_internal_values(candle, what_type_of_candle):
    clear_priority_candles(True, what_type_of_candle) #resetting priority candle values because previous candles before the highest one serves no purpose
    await record_priority_candle(candle, what_type_of_candle)
    return [], None, None

async def identify_flag(candle, num_flags, session, headers, what_type_of_candle, able_to_buy = True):
    print(f"    [IDF Candle {candle['candle_index']}] OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")
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
    breakout_detected = None
    candle_direction = None
    # Check if the 'type' key exists in the candle dictionary
    if 'type' in candle and ('support' in candle['type'] and 'Buffer' in candle['type']) or ('resistance' in candle['type'] and 'PDH' in candle['type']) or ('PDHL' in candle['type'] and 'PDH' in candle['type']):
        # Bull Candles, We look at Higher Highs
        candle_direction = "bullish"
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_high is None or candle['high'] > current_high:
            # NEW CODE: Somehow check if there already is a flag and if current candle is higher then slopes highest high, if it is it should buy
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bullish'
                )   
            current_high = candle['high']
            highest_point = (candle['candle_index'], current_high)
            print(f"    [IDF Highest Point] New: {highest_point}")
            lower_highs, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
        else: 
            if candle['high'] == current_high and candle['candle_index'] > highest_point[0]:
                #Ok, heres what happened we have a slope and intercept available but we had a equal higher high which should have made a buy order.
                if slope is not None and intercept is not None:
                    slope, intercept, breakout_detected = await process_breakout_detection(
                        line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bullish'
                    ) 
                current_high = candle['high']
                highest_point = (candle['candle_index'], current_high)
                print(f"    [IDF Highest Point] Updated: {highest_point}")
                lower_highs, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
            else:
                # 'oc' means Open or Close, whichever is higher
                candle_oc = candle['open'] if candle['open'] >= candle['close'] else candle['close']
                lower_highs.append((candle['candle_index'], candle_oc, candle['high']))
        # This block calculates the slope and intercept for a potential flag, updating line data if valid points are found.
        if len(lower_highs) >= MIN_NUM_CANDLES and (slope is None or intercept is None):
            print(f"    [IDF SLOPE] Calculating Slope Line...")
            slope, intercept, second_point = calculate_slope_intercept(lower_highs, highest_point, "bull")
            if slope is not None:  # Add a check here
                if is_angle_valid(slope, config) :
                    print("    [IDF VALID SLOPE] Angle within valid range.")
                    
                    print(f"    [IDF FLAG] UPDATE 1: {line_name}, active")
                    update_line_data(line_name, "Bull", "active", highest_point, second_point)
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bullish'
                        )
                else:
                    print("    [IDF INVALID SLOPE] First point is later than second point.")
                    current_high = candle['high']
                    highest_point = (candle['candle_index'], current_high)
                    print(f"        [(Lower) Highest Point] Updated: {highest_point}")
                    lower_highs, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
            else:
                print("    [IDF SLOPE] calculation failed or not applicable.")

        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, lower_highs, highest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bullish'
            )
    
    elif ('support' in candle['type'] and 'PDL' in candle['type']) or ('resistance' in candle['type'] and 'Buffer' in candle['type']) or ('PDHL' in candle['type'] and 'PDL' in candle['type']):
        # Bear Candles, we look at lower lows
        candle_direction = "bearish"
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_low is None or candle['low'] < current_low:
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bearish'
                )
            current_low = candle['low']
            lowest_point = (candle['candle_index'], current_low)
            print(f"    [IDF Lowest Point] New: {lowest_point}")
            higher_lows, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
        else: 
            if candle['low'] == current_low and candle['candle_index'] > lowest_point[0]:
                if slope is not None and intercept is not None:
                    slope, intercept, breakout_detected = await process_breakout_detection(
                        line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bearish'
                    )
                current_low = candle['low']
                lowest_point = (candle['candle_index'], current_low)
                print(f"    [IDF Lowest Point] Updated: {current_low}")
                higher_lows, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
            else:
                # 'oc' means Open or Close, whichever is lower
                candle_oc = candle['open'] if candle['open'] <= candle['close'] else candle['close']
                higher_lows.append((candle['candle_index'], candle_oc, candle['low']))

        # This block calculates the slope and intercept for a potential flag, updating line data if valid points are found.
        if len(higher_lows) >= MIN_NUM_CANDLES and (slope is None or intercept is None):
            print(f"    [IDF SLOPE] Calculating Slope Line...")
            slope, intercept, second_point = calculate_slope_intercept(higher_lows, lowest_point, "bear")
            if slope is not None:  # Add a check here
                if is_angle_valid(slope, config, bearish=True):
                    print("    [IDF VALID SLOPE] Angle within valid range.")
                    
                    print(f"    [IDF FLAG] UPDATE 2: {line_name}, active")
                    update_line_data(line_name, "Bear", "active", lowest_point, second_point) 
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bearish'
                        )
                else:
                    print("    [IDF  [INVALID SLOPE] First point is later than second point.")
                    current_low = candle['low']
                    lowest_point = (candle['candle_index'], current_low)
                    print(f"    [IDF (Higher) Lowest Point] Updated: {current_low}")
                    higher_lows, slope, intercept = await reset_flag_internal_values(candle, what_type_of_candle)
            else:
                print("    [IDF SLOPE] calculation failed or not applicable.")

        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bearish'
            )
    else:
        print(f"    [IDF No Support Candle] type = {candle}")    
    
    if not able_to_buy and breakout_detected:
        return True

    # Write the updated state back to the JSON file
    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)
    print(f"    [IDF CANDLE DIR] {candle_direction}")
    update_2_min()
    update_state(state_file_path, current_high, highest_point, lower_highs, current_low, lowest_point, higher_lows, slope, intercept, candle)

async def check_for_bearish_breakout(line_name, hl, higher_lows, lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy):
    
    if slope and intercept is not None:
        trendline_y = slope * hl[0] + intercept

        if hl[1] < trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {hl}")

            # Check if the candle associated with this higher low completely closes below the trendline
            if candle['close'] < trendline_y and candle['close'] <= candle['open']:
                if able_to_buy:
                    success = await handle_breakout_and_order(
                        what_type_of_candle, lowest_point, trendline_y, line_name, hl[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear"
                    )
                    if success:
                        return None, None, True
                    else:
                        print(f"            [CFBB TRUE BREAKOUT 1] Condition Failure; restart data")
                        restart_flag_data(what_type_of_candle)
                        return None, None, True
                else:
                    restart_flag_data(what_type_of_candle)
                    return None, None, True 
            else:
                # Test new slope and intercept
                print(f"            [CFBB BREAKOUT] Failed, Went up at {hl}")
                new_slope = (hl[1] - lowest_point[1]) / (hl[0] - lowest_point[0])
                new_intercept = lowest_point[1] - new_slope * lowest_point[0]
                if new_slope is not None and is_angle_valid(new_slope, config, bearish=True):
                    valid_breakout = True
                    for test_point in higher_lows:
                        if test_point[1] < new_slope * test_point[0] + new_intercept:
                            valid_breakout = False
                            break

                    if valid_breakout:
                        print(f"            [CFBB FLAG] UPDATE 4: {line_name}, active")
                        update_line_data(line_name, "Bear", "active", lowest_point, hl)
                        return new_slope, new_intercept, False
                    else:
                        print("            [CFBB INVALID BREAKOUT] Invalid breakout on new slope.")
                        return None, None, False
                else:
                    #TODO THIS SECTION NEEDS WORK
                    #idk what to do if slope angle is invalid
                    print("            [CFBB INVALID SLOPE] Slope is not within Range.")
                    return None, None, False

        
        if candle['close'] < trendline_y and candle['close'] <= candle['open']:
            print(f"            [CFBB BREAKOUT 2] Closed under from {trendline_y} at {candle['close']}")
            if able_to_buy:
                success = await handle_breakout_and_order(
                    what_type_of_candle, lowest_point, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bear", calculate_new_trendline=True, slope=slope, intercept=intercept
                )
                if success:
                    return None, None, True
                else:
                    print(f"            [CFBB TRUE BREAKOUT 2] Condition Failure; restart data")
                    restart_flag_data(what_type_of_candle)
                    return None, None, True
            else:
                restart_flag_data(what_type_of_candle)
                return None, None, True
    return slope, intercept, False

async def check_for_bullish_breakout(line_name, lh, lower_highs, highest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy):
    
    if slope and intercept is not None:
        #y = mx + b
        trendline_y = slope * lh[0] + intercept
        
        if lh[1] > trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {lh}")
            # Check if the candle associated with this lower high closes over the slope intercept (trendline_y)
            if candle['close'] > trendline_y and candle['open'] <= candle['close']:
                print(f"            [CFBB BREAKOUT 1] Closed over from {trendline_y} at {candle['close']}; {candle['open']}")
                if able_to_buy:
                    success = await handle_breakout_and_order(
                        what_type_of_candle, highest_point, trendline_y, line_name, lh[0], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull"
                    )
                    if success:
                        return None, None, True
                    else:
                        print(f"            [CFBB TRUE BREAKOUT 3] Condition Failure; restart data")
                        restart_flag_data(what_type_of_candle)
                        return None, None, True
                else:
                    restart_flag_data(what_type_of_candle)
                    return None, None, True
            else:
                # Test new slope and intercept
                print(f"            [CFBB BREAKOUT] Failed, Went down at {lh}")
                new_slope = (lh[1] - highest_point[1]) / (lh[0] - highest_point[0])
                new_intercept = highest_point[1] - new_slope * highest_point[0]

                if new_slope is not None and is_angle_valid(new_slope, config):
                    valid_breakout = True
                    for test_point in lower_highs:
                        # Check if any point is above the new trendline
                        if test_point[1] > new_slope * test_point[0] + new_intercept:
                            valid_breakout = False

                    if valid_breakout:
                        print(f"            [CFBB FLAG] UPDATE 6: {line_name}, active")
                        update_line_data(line_name, "Bull", "active", highest_point, lh)
                        return new_slope, new_intercept, False
                    else:
                        print("            [CFBB INVALID BREAKOUT] Invalid breakout on new slope.")
                        return None, None, False
                else:
                    #TODO THIS SECTION NEEDS WORK
                    #idk what to do if slope angle is invalid
                    print("            [CFBB INVALID SLOPE] Slope is not within Range.")
                    return None, None, False
        
        #this is incase the candle is the one that breaks above the whole trendline, making a new highest high
        if candle['close'] > trendline_y and candle['open'] <= candle['close']:
            print(f"            [CFBB BREAKOUT 2] Closed over from {trendline_y} at {candle['close']}")
            if able_to_buy:
                success = await handle_breakout_and_order(
                    what_type_of_candle, highest_point, trendline_y, line_name, candle['candle_index'], session, headers, IS_REAL_MONEY, SYMBOL, line_type="Bull", calculate_new_trendline=True, slope=slope, intercept=intercept
                )
                if success:
                    return None, None, True
                else:
                    print(f"            [CFBB TRUE BREAKOUT 4] Condition Failure; restart data")
                    restart_flag_data(what_type_of_candle)
                    return None, None, True
            else:
                restart_flag_data(what_type_of_candle)
                return None, None, True
    return slope, intercept, False

async def process_breakout_detection(line_name, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy, breakout_type='bullish'):
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
        what_type_of_candle: passes it through to breakout functions, this is to know what zone a possible order is being made out of, to track if were in threshold
        breakout_type (str): 'bullish' or 'bearish' to determine the type of breakout to check.

    Returns:
        tuple: Updated slope, intercept, and a boolean indicating if a breakout was detected.
    """
    breakout_detected = False
    if breakout_type == 'bullish':
        candle_oc = candle['open'] if candle['open'] >= candle['close'] else candle['close']
        point = (candle['candle_index'], candle_oc, candle['high'])  
        print(f"        [PBD POINT] {point}")
        slope, intercept, detected = await check_for_bullish_breakout(
            line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy
        )
    else:  # 'bearish'
        candle_oc = candle['close'] if candle['close'] <= candle['open'] else candle['open']
        point = (candle['candle_index'], candle_oc, candle['low'])
        print(f"        [PBD POINT] {point}")
        slope, intercept, detected = await check_for_bearish_breakout(
            line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, session, headers, what_type_of_candle, able_to_buy
        )
    if detected:
        breakout_detected = True
        print(f"        [PBD Breakout Detected] {line_name} detected a {breakout_type} breakout at {point}")
        return slope, intercept, breakout_detected # TODO See if this changes anything we dont want to change
    return slope, intercept, breakout_detected

async def handle_breakout_and_order(what_type_of_candle, hlp, trendline_y, line_name, point, session, headers, is_real_money, symbol, line_type, calculate_new_trendline=False, slope=None, intercept=None):
    """
    Handle the breakout logic and conditional order execution, with an optional calculation of a new trendline.

    Args:
    - what_type_of_candle: this is the zone we exited out of, direction we think were going.
    - hlp: Means highest_lowest_point, so that we always have a line when plotting. testing this new feature
    - trendline_y: The y-value of the trendline at the x-position of the current candle.
    - line_name: The name of the line associated with the current analysis.
    - point: The point associated with the current breakout analysis. Can be lh or candle['candle_index'] based on the context.
    - session: The aiohttp client session for making HTTP requests.
    - headers: HTTP request headers.
    - is_real_money: Boolean indicating if real money trading is activated.
    - symbol: The trading symbol.
    - line_type: 'Bull' for bullish breakouts or 'Bear' for bearish breakouts.
    - calculate_new_trendline (bool, optional): Boolean indicating if a new trendline calculation is needed based on the current candle.
    - slope (float, optional): The slope of the trendline (required if calculate_new_trendline is True).
    - intercept (float, optional): The intercept of the trendline (required if calculate_new_trendline is True).
    """

    # Calculate new trendline if required, needed for both line types
    if calculate_new_trendline and slope is not None and intercept is not None:
        trendline_y = slope * point + intercept  # Recalculate trendline_y with new slope and intercept
        print(f"                [HBAO TRENDLINE] UPDATE: {trendline_y}")
    
    print(f"                [HBAO FLAG] UPDATE 1: {line_name}, active")
    update_line_data(line_name=line_name, line_type=line_type, status="active", point_1=(hlp[0], hlp[1]), point_2=(point, trendline_y))
    
    #Check emas
    if line_type == 'Bull':
        ema_condition_met, ema_price_distance_met = await above_below_ema('above', EMA_MAX_DISTANCE)
    else:  # 'Bear'
        ema_condition_met, ema_price_distance_met = await above_below_ema('below', EMA_MAX_DISTANCE)
    
    #check if points are valid
    vp_1, vp_2 = check_valid_points(line_name) #vp means valid point

    # Check if trade limits have been reached in this zone
    multi_order_condition_met = check_order_type_json(what_type_of_candle)

    # Check if trade time is aligned with economic events
    time_result = check_order_time_to_event_time(MINS_BEFORE_MAJOR_NEWS_ORDER_CANCELATION)

    print(f"                [HBAO CONDITIONS] {ema_condition_met}, {vp_1}, {vp_2}, {multi_order_condition_met}, {ema_price_distance_met}, {time_result}")
    if ema_condition_met and vp_1 and vp_2 and multi_order_condition_met and ema_price_distance_met and time_result: # if all conditions met, then authorize order, buy
        action = 'call' if line_type == 'Bull' else 'put'
        print(f"                [HBAO ORDER CONFIRMED] Buy Signal ({action.upper()})")
        success = await buy_option_cp(is_real_money, symbol, action, session, headers, STRATEGY_NAME)
        if success: #incase order was canceled because of another active
            add_candle_type_to_json(what_type_of_candle)
        else:
            print(f"                [HBAO ORDER FAIL] Buy Signal ({action.upper()}), what_type_of_candle = {what_type_of_candle}")
        print(f"                [HBAO FLAG] UPDATE 2: {line_name}, complete")
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return True
    else:
        reason = determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, multi_order_condition_met, time_result)
        
        action = 'CALL' if line_type == 'Bull' else 'PUT'
        print(f"                [HBAO ORDER CANCELED] Buy Signal ({action}); {reason}.")
        #if any of the vp_1 or vp_2 are false, don't go through. but if vp_1 and vp_2 are both true and not ema_condition_met is true then go through
        if not ema_condition_met and vp_1 and vp_2: #and not multi_order_condition_met:
            print(f"                [HBAO FLAG] UPDATE 3: {line_name}, complete")
            update_line_data(line_name=line_name, line_type=line_type, status="complete") #test this out next day to see if this fixes the wait-until above/below emas to buy error.
        return False
    
def calculate_slope_intercept(points, start_point, flag_type="bull"):
    # flag_type can only equal "bull" or "bear"

    # Calculate initial slope (m) and intercept (c) using the latest point in the list
    # Get the latest in the list [1,0,-1] each one is a X,Y coordinate
    latest_point = points[-1]
    if start_point[0] >= latest_point[0]:
        print("        [CSI INVALID POINTS] First point is later than second point.")
        return None, None, None
    # Slope formula: m = (y2 - y1) / (x2 - x1)
    slope = (latest_point[1] - start_point[1]) / (latest_point[0] - start_point[0])
    print(f"        [CSI POINTS SLOPE] {start_point} | {latest_point}")
    # Rearrangement of the slope-intercept form: c = y − mx 
    intercept = start_point[1] - slope * start_point[0]
    print(f"        [CSI VALID SLOPE] Slope: {slope}, Intercept: {intercept}")

    if len(points) == 1:
        return slope, intercept, latest_point

    # Initialize the second_point as the latest_point
    second_point = latest_point

    # Check if any other points are above (for bull) or below (for bear) the line
    for point in points:
        # Calculate the expected y-value on the line for the current x-value
        # Y = MX + B ; Slope intercept form
        expected_y = slope * point[0] + intercept

        if (flag_type == "bull" and point[1] > expected_y) or (flag_type == "bear" and point[1] < expected_y):
            # Found a point above the line, recalculate slope and intercept
            slope = (point[1] - start_point[1]) / (point[0] - start_point[0])
            intercept = start_point[1] - slope * start_point[0]
            second_point = point
            print(f"        [CSI UPDATED SLOPE {flag_type.upper()}] {start_point} | {point}")

    print(f"        [CSI FINAL SLOPE] Slope: {slope}, Intercept: {intercept}, Second Point: {second_point}")
    return slope, intercept, second_point
    
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