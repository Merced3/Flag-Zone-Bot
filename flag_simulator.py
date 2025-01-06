# flag_simulator.py; it's purpopse is to simulate different Logs/Zones To make sure that my flags are redundent and reliable.
import os
import json
import asyncio
import threading
from datetime import datetime
from calculate_avg_trim_distance import get_avg_trim_from_folder
from data_acquisition import read_last_n_lines, restart_state_json, determine_order_cancel_reason, record_priority_candle, clear_priority_candles, add_markers, update_state, check_valid_points, check_order_type_json, is_angle_valid, empty_log, reset_json, load_json_df, count_flags_in_json, above_below_ema, resolve_flags, add_candle_type_to_json, get_test_data_and_allocate, is_ema_broke, get_current_candle_index, candle_ema_handler, candle_close_in_zone, start_new_flag_values, restart_flag_data
from chart_visualization import setup_simulation_environment, update_2_min, initiate_shutdown

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config
# Accessing control pannel
config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
SYMBOL = config["SYMBOL"]
TIMEFRAMES = config["TIMEFRAMES"]
MIN_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MIN_NUM_CANDLES"]
MAX_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MAX_NUM_CANDLES"]
EMA_MAX_DISTANCE = config["EMA_MAX_DISTANCE"]
TRADE_IN_BUFFERS = config["TRADE_IN_BUFFERS"]

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f'{SYMBOL}_{TIMEFRAMES[0]}.log')  # Adjust the path accordingly

global sim_order_details
sim_order_details = {
    "call_or_put": None,
    "buy_entry_price": None,
    "current_order_active": False,
    "trim_flag_1": False,
    "trim_flag_2": False,
    "trim_flag_3": False,
    
}
global global_trims
global_trims = {'average': None, 'minimum': None, 'maximum': None}

global last_processed_candle
last_processed_candle = None

async def testing_new_flag_process(interval = 2):
    global global_trims
    print("Allocating Data...")
    folder_name = "8_2_2024"
    zones, tp_lines = get_test_data_and_allocate(folder_name) # '9_13_2024' folder name for example

    print(f"\nZones:\n{zones}\n\ntp_lines:\n{tp_lines}\n")
    
    # GET TRIMS IF ANY THIS DAY
    global_trims = get_avg_trim_from_folder(folder_name)
    print(f"global_trims:\n{global_trims}")
    
    print("\n[Simulator Setup]")
    # Setup environment in a separate thread as it includes blocking calls
    threading.Thread(target=lambda: setup_simulation_environment(zones, tp_lines, interval), name="setup_simulation_environment()").start()
    # This 'setup_simulation_environment()' function uses the log file in my log's folder, the file contains previous days of 2min chart OCHL
    # candle stick chart data. What the thread function does is use 2 log files, one empty and one filled with the data, and it add's one candle
    # to the empty file every 'interval'. that's why below we wait until we can read first candle in the log file path. then when we do we start 
    # the 'new_candle_ema_setup()' 

    restart_state_json(True)  # Reset 'state.json' at the beginning
    
    # Wait for the simulation to start and populate data
    while True:
        await asyncio.sleep(0.5)  # Check every half second
        f_candle = read_last_n_lines(LOG_FILE_PATH, 1)
        if f_candle:
            #print(f"    [TNFP] First candle processed: {f_candle[0]}")
            break

    # NEW SETUP
    await new_candle_ema_setup(zones)

async def new_candle_ema_setup(zones):
    global last_processed_candle
    print(f"\n\n\n|- - - - - [STARTING SIMULATOR] - - - - -|\n")
    f_candle = read_last_n_lines(LOG_FILE_PATH, 1)
    print(f"    [ETS INFO] First candle processed: {f_candle[0]}")
    what_type_of_candle = candle_zone_handler(f_candle[0], None, zones, True)
    try:
        while True:
            current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)
            # We get candles one by one until there are no more
            if current_last_candle and current_last_candle != last_processed_candle:
                #Add current candle to last processed candle so we can pause whatever time to give candles enough time to calculate everything
                last_processed_candle = current_last_candle
                candle = last_processed_candle[0]
                print_candle(candle)

                # candle_zone_handler() handles if current candle is shooting above, below through zones and ends inside zones.
                what_type_of_candle = candle_zone_handler(candle, what_type_of_candle, zones, False)
                # The Reason the zones are important is because they are previously calculated high and low previous day boxes
                # that are to help us stay away from chop since this is a trend strategy.

                # candle_ema_handler() will return 'bearish' or 'bullish' if were above or below the 200 ema
                bull_or_bear_candle = candle_ema_handler(candle)
                # Above determines if were looking at bear or bull flags, if it switches from bearish to 
                # bullish and vice versa, it forgets everything it caculated before so it can calculate 
                # for a new flag type. this is somewhat aright and somewhat works but i need a new system 
                # that calculates not just one flag at a time but multiple at the same time weather it be bear or bull.

                is_in_zone = candle_close_in_zone(candle, zones) # is or isn't in zones
                able_to_buy = not is_in_zone # if so, don't buy inside zones
                
                # Simulate order management if an order is active
                if sim_order_details["current_order_active"]:
                    await manage_sim_order(candle)

                if bull_or_bear_candle is not None:
                    #record the candle data
                    await record_priority_candle(candle, what_type_of_candle) 
                    # record_priority_candle() add's candle into 'priority_candles.json' which is where we 
                    # get all the candles and calculate based off of what is in the json file. Sometime 
                    # the 'priority_candles.json' is resetted because of new higher high candles made (and 
                    # were looking at BULL flags) or new lower low candles are made (because were looking 
                    # at BEAR flags, decided based off 'candle_ema_handler' function)
                    priority_candles = load_json_df('priority_candles.json')
                    num_flags = count_flags_in_json()
                    # So 'load_json_df()' turns all the candles in 'priority_candles.json' info a 'df' or dataframe.
                    # 'count_flags_in_json()' looks at 'line_data.json' and see's if there are any COMPLETED flags, 
                    # hence them being lines, then add them all up then return the number (int) so we can name the 
                    # next flag ('flag_#') that comes and we don't have to worry about replacing values of previous 
                    # flags or duplicating flag names.
                    last_candle = priority_candles.iloc[-1] # I think this just grabs last candle in the 'df' meaning the current candle.
                    last_candle_dict = last_candle.to_dict()
                    await identify_flag(last_candle_dict, num_flags, what_type_of_candle, bull_or_bear_candle, able_to_buy)
                    # 'identify_flag()' is where the calculations are made to find bear or bull flags one by one, not in the multi-handling system that we need.
                else:
                    restart_flag_data(what_type_of_candle)
                    # 'restart_flag_data()' does 3 things, clears 'priority_candles.json', restarts 'state.json', and 
                    # mark uncompleted flags in 'line_data.json' as completed so that we don't forget that flag and 
                    # don't replace it values with the new oposite type of flag that is coming up even tho the recently 
                    # completed "flag" has no use to us, this setup might serve as a hinderence to us. IDK LMK.

            else:
                await asyncio.sleep(1)  # Use asyncio sleep for non-blocking wait
    except Exception as e:
        print(f"[MAIN ERROR] {e}")

# Other code... candle_zone_handler(), identify_flag() and other functions...

def candle_zone_handler(candle, type_of_candle, boxes, first_candle = False):
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
        if box_name == 'PDHL' and first_candle: 
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
        
    if type_of_candle is not None:
        return type_of_candle      

async def identify_flag(candle, num_flags, what_type_of_candle, bull_or_bear_candle, able_to_buy = True):
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
    
    # Check if the 'type' key exists in the candle dictionary
    if 'type' in candle:
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
                    line_name, slope, intercept, candle, what_type_of_candle, able_to_buy, candle_type
                )
                
            start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle)
                
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
                line_name, slope, intercept, candle, what_type_of_candle, able_to_buy, candle_type
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
                    start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle)
            elif breakout_detected: 
                if flag_counter < 2:
                    flag_counter = flag_counter +1
                    print(f"    [IDF] Forming flag {flag_counter} for current start_point.")
                else:
                    print(f"    [IDF] Maximum flags reached for start_point, resetting start_point and candle_points.")
                    start_point, candle_points, slope, intercept, flag_counter = await start_new_flag_values(candle, candle_type, current_oc_high, current_oc_low, what_type_of_candle)
    else:
        print(f"    [IDF No Support Candle] type = {what_type_of_candle}; {bull_or_bear_candle}")    
    
    if not able_to_buy and breakout_detected:
        #broke out while inside zone.
        print(f"    [IDF] Breakout Detected and inside of zone.")
    
    # Write the updated state back to the JSON file
    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)
    print(f"    [IDF CANDLE DIR] {what_type_of_candle}, Flag Count: {flag_counter}")
    update_state(state_file_path, flag_counter, start_point, candle_points, slope, intercept)

async def process_breakout_detection(line_name, slope, intercept, candle, what_type_of_candle, able_to_buy, breakout_type='bull'):
    # Calculate trendline y-value using the translated line
    trendline_y = slope * candle['candle_index'] + intercept
    detected = False

    if breakout_type == 'bull':
        candle_oc = candle['open'] if candle['open'] >= candle['close'] else candle['close']
        if candle_oc > trendline_y:
            print(f"    [PBD Breakout Detected] {line_name} detected bullish breakout at {candle_oc}")
            # Handle the breakout
            slope, intercept, detected = await check_for_bullish_breakout(
                line_name, (candle['candle_index'], candle_oc, candle['high']), slope, intercept, candle, what_type_of_candle, able_to_buy
            )
    else:  # bearish
        candle_oc = candle['close'] if candle['close'] <= candle['open'] else candle['open']
        if candle_oc < trendline_y:
            print(f"    [PBD Breakout Detected] {line_name} detected bearish breakout at {candle_oc}")
            # Handle the breakout
            slope, intercept, detected = await check_for_bearish_breakout(
                line_name, (candle['candle_index'], candle_oc, candle['low']), slope, intercept, candle, what_type_of_candle, able_to_buy
            )
    
    return slope, intercept, detected

async def check_for_bearish_breakout(line_name, point, slope, intercept, candle, what_type_of_candle, able_to_buy):
    
    if slope and intercept is not None:
        trendline_y = slope * point[0] + intercept

        if point[1] < trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {point}")

            # Check if the candle associated with this higher low completely closes below the trendline
            if candle['close'] < trendline_y and candle['close'] <= candle['open']:
                print(f"            [CFBB BREAKOUT 1] Closed under from {trendline_y} at {candle['close']}")
                success = await handle_breakout_and_order(
                    candle, what_type_of_candle, trendline_y, line_name, point[0], line_type="Bear", able_to_buy=able_to_buy
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
                candle, what_type_of_candle, trendline_y, line_name, candle['candle_index'], line_type="Bear", calculate_new_trendline=True, slope=slope, intercept=intercept, able_to_buy=able_to_buy
            )
            if success:
                return None, None, True
            else:
                print(f"            [CFBB TRUE BREAKOUT 2] Condition Failure")
                update_line_data(line_name=line_name, line_type="Bear", status="complete")
                return None, None, True
    return slope, intercept, False

async def check_for_bullish_breakout(line_name, point, slope, intercept, candle, what_type_of_candle, able_to_buy):
    if slope and intercept is not None:
        #y = mx + b
        trendline_y = slope * point[0] + intercept
        
        if point[1] > trendline_y:
            print(f"            [CFBB BREAKOUT] Potential Breakout Detected at {point}")
            # Check if the candle associated with this lower high closes over the slope intercept (trendline_y)
            if candle['close'] > trendline_y and candle['open'] <= candle['close']:
                print(f"            [CFBB BREAKOUT 1] Closed over from {trendline_y} at {candle['close']}; {candle['open']}")
                #if able_to_buy:
                success = await handle_breakout_and_order(
                    candle, what_type_of_candle, trendline_y, line_name, point[0], line_type="Bull", able_to_buy=able_to_buy
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
            #if able_to_buy:
            success = await handle_breakout_and_order(
                candle, what_type_of_candle, trendline_y, line_name, candle['candle_index'], line_type="Bull", calculate_new_trendline=True, slope=slope, intercept=intercept, able_to_buy=able_to_buy
            )
            if success:
                return slope, intercept, True
            else:
                print(f"            [CFBB BREAKOUT 4] Condition Failure")
                update_line_data(line_name=line_name, line_type="Bull", status="complete")
                return slope, intercept, True
    return slope, intercept, False

async def handle_breakout_and_order(candle, what_type_of_candle, trendline_y, line_name, candle_x, line_type, calculate_new_trendline=False, slope=None, intercept=None, able_to_buy=True):
    global sim_order_details
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
    #ema_condition_met, ema_price_distance_met = True, True
    if line_type == 'Bull':
        ema_condition_met, ema_price_distance_met, ema_distance = await above_below_ema('above', EMA_MAX_DISTANCE, candle['close'])
    else:  # 'Bear'
        ema_condition_met, ema_price_distance_met, ema_distance = await above_below_ema('below', EMA_MAX_DISTANCE, candle['close'])
    
    #check if points are valid
    vp_1, vp_2, line_degree_angle = check_valid_points(line_name) #vp means valid point

    # Check if trade limits have been reached in this zone
    multi_order_condition_met, num_of_matches = check_order_type_json(what_type_of_candle)

    print(f"                [HBAO CONDITIONS] {vp_1}, {vp_2}, {multi_order_condition_met}, {num_of_matches}, {ema_condition_met}, {ema_price_distance_met}, {ema_distance}")
    if ema_condition_met and vp_1 and vp_2 and multi_order_condition_met and ema_price_distance_met: # if all conditions met, then authorize order, buy
        action = 'call' if line_type == 'Bull' else 'put'
        print(f"                [HBAO ORDER CONFIRMED] Buy Signal ({action.upper()})")
        # IMPORTANT: Since we are testing flags we don't need to test the actual buy function.
        #success = await buy_option_cp(is_real_money, symbol, action, session, headers, STRATEGY_NAME)
        #if success: #incase order was canceled because of another active
        if not sim_order_details["current_order_active"]:
            await start_sim_order(candle, candle['close'], what_type_of_candle, action)    
        else:
            print("                [HBAO ORDER] Canceled, active order already in play...")
        #add_candle_type_to_json(what_type_of_candle)
        #print(f"point: {point}")
        #await add_markers("buy", point, candle['close'])
        #else:
            #print(f"    [ORDER FAIL] Buy Signal ({action.upper()}), what_type_of_candle = {what_type_of_candle}")
        print(f"                [HBAO FLAG] UPDATE 2: {line_name}, complete")
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return True
    else:
        #if vp_1 and vp_2:
            #print(f"                [HBAO FLAG] UPDATE 3: {line_name}, active")
            #update_line_data(line_name=line_name, line_type=line_type, status="complete")
        reason = determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, multi_order_condition_met, True)
        
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

def print_candle(candle):
    #{candle['candle_index']}
    timestamp_str = candle["timestamp"]
    timestamp_dt = datetime.fromisoformat(timestamp_str)
    formatted_time = timestamp_dt.strftime("%H:%M:%S")
    num = get_current_candle_index(LOG_FILE_PATH)
    print(f"[{formatted_time}] {num} OHLC: {candle['open']}, {candle['high']}, {candle['low']}, {candle['close']}")

async def start_sim_order(candle, entry_price, what_type_of_candle, action):
    global sim_order_details

    sim_order_details["current_order_active"] = True
    sim_order_details["buy_entry_price"] = entry_price
    sim_order_details["call_or_put"] = action

    add_candle_type_to_json(what_type_of_candle)
    await add_markers("buy", y=candle['close'], percentage=0)

async def manage_sim_order(candle):
    global sim_order_details
    global global_trims

    if global_trims['average'] and global_trims['minimum'] and global_trims['maximum']:
        lowest_trim_possibility = global_trims['minimum']
        avg_trim_possibility = global_trims['average']
        guaranteed_trim_win = global_trims['maximum']
        print(f"    [SIM_ORDER] Using same days trims")
    else:
        lowest_trim_possibility = 0.02
        avg_trim_possibility = 0.4429
        guaranteed_trim_win = 0.94
        print(f"    [SIM_ORDER] Using AVG trims from cumalitive Days")

    # Extract order details from the dictionary
    current_candle_price = candle['high'] if sim_order_details["call_or_put"] == "call" else candle['low']
    #price_difference = abs(current_candle_price - sim_order_details["buy_entry_price"])
    
    print(f"        [SIM_ORDER] current price: {current_candle_price}")
    
    trim_level1 = sim_order_details["buy_entry_price"] + lowest_trim_possibility if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - lowest_trim_possibility
    trim_level2 = sim_order_details["buy_entry_price"] + avg_trim_possibility if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - avg_trim_possibility
    trim_level3 = sim_order_details["buy_entry_price"] + guaranteed_trim_win if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - guaranteed_trim_win
    print(f"        [SIM_ORDER] Trim Levels: {trim_level1}, {trim_level2}, {trim_level3}")
    x =  get_current_candle_index(LOG_FILE_PATH) -1
    # Check trim and sell conditions
    #if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level1) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level1)) and not sim_order_details["trim_flag_1"]:
        #y = trim_level1
        #await add_markers("sim_trim_lwst", x=x, y=y, percentage=20)
        #sim_order_details["trim_flag_1"] = True

    if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level2) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level2)) and not sim_order_details["trim_flag_2"]:
        y = trim_level2
        await add_markers("sim_trim_avg", x=x, y=y, percentage=20)
        sim_order_details["trim_flag_2"] = True
    
    if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level3) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level3)) and not sim_order_details["trim_flag_3"]:
        y = trim_level3
        await add_markers("sim_trim_win", x=x, y=y, percentage=20)
        sim_order_details["trim_flag_3"] = True
    
    # Check if EMA is broken to determine if the order should be sold
    if is_ema_broke("13", SYMBOL, "2M", sim_order_details["call_or_put"]):
        y = candle['close']
        await add_markers("sell", x=x, y=y, percentage=20)      
        # Reset order state
        sim_order_details["trim_flag_1"] = False
        sim_order_details["trim_flag_2"] = False
        sim_order_details["trim_flag_3"] = False
        sim_order_details["call_or_put"] = None
        sim_order_details["buy_entry_price"] = None
        sim_order_details["current_order_active"] = False
        print(f"        [SIM_ORDER] RESET Order state")

async def shutdown(flag=False):
    # Cancel all tasks:
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    # Wait for all tasks to finish:
    await asyncio.gather(*tasks, return_exceptions=True)

    initiate_shutdown()  # This should properly handle Tkinter's quit
    #open log file, empty all of its contents so its ready for the next run.
    if flag:
        clear_data()
    asyncio.get_running_loop().stop()

def clear_data():
    empty_log("SPY_2M")
    restart_state_json(True)
    #clear EMAs.json file
    reset_json('EMAs.json', [])
    #Clear the markers.json file
    reset_json('markers.json', {})
    #clear line_data_TEST.json
    reset_json('line_data.json', [])
    #clear order_candle_type.json
    reset_json('order_candle_type.json', [])
    #clear priority_candles.json
    reset_json('priority_candles.json', [])

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(testing_new_flag_process())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\n[Interrupted by user] shutting down...")
        loop.run_until_complete(shutdown(True))
    finally:
        loop.close()