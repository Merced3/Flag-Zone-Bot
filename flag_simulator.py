#flag_simulator.py; it's purpopse is to simulate different Logs/Zones To make sure that my flags are redundent and reliable.
import os
import json
from data_acquisition import read_last_n_lines, restart_state_json, determine_order_cancel_reason, record_priority_candle, clear_priority_candles, add_markers, update_state, check_valid_points, check_order_type_json, is_angle_valid
import asyncio

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config

config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
SYMBOL = config["SYMBOL"]
TIMEFRAMES = config["TIMEFRAMES"]
MIN_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MIN_NUM_CANDLES"]
MAX_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MAX_NUM_CANDLES"]

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f'{SYMBOL}_{TIMEFRAMES[0]}.log')  # Adjust the path accordingly

#TODO: IMPORTANT TO CHANGE
zones = {}

async def testing_new_flag_process():

    #Testing While Running: 'resistance PDH' or 'support Buffer' or "support_1 Buffer"
    what_type_of_candle = None #TODO None 
    #Testing While Running: True
    havent_cleared = False #TODO False

    restart_state_json(True)

    try:
        while True:

            #somehow cycle through candles in SPY_2M.log file. simulating candles coming in one by one

            current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)

            if current_last_candle and current_last_candle != last_processed_candle:
                last_processed_candle = current_last_candle
                #get that candle, look at its OHLC values
                candle = last_processed_candle[0]

                #Handle the zones
                for box_name, (x_pos, high_low_of_day, buffer) in zones.items(): 
                    # Determine zone type
                    zone_type = "support" if "support" in box_name else "resistance" if "resistance" in box_name else "PDHL"
                    PDH_or_PDL = high_low_of_day  # PDH for resistance, PDL for support
                    box_top = PDH_or_PDL if zone_type in ["resistance", "PDHL"] else buffer  # PDH or Buffer as top for resistance/PDHL
                    box_bottom = buffer if zone_type in ["resistance", "PDHL"] else PDH_or_PDL  # Buffer as bottom for resistance/PDHL
                    check_is_in_another_zone = False
                    action = None # Initialize action to None or any default value
                    # Check if the candle shoots through the zone
                    if candle['open'] < box_bottom:
                        if candle['close'] > box_top:
                            # Candle shoots up through the zone
                            #END 1 was wrong, changed it to start.
                            action = "[START 1]" # CALLS
                            candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
                            check_is_in_another_zone = True
                        elif box_bottom < candle['close'] < box_top:
                            #went up, closed Inside of box
                            action = '[END 2]'
                    elif candle['open'] > box_top:
                        if candle['close'] < box_bottom:
                            # Candle shoots down through the zone
                            action = "[START 4]" # PUTS
                            candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                            check_is_in_another_zone = True
                        elif box_top > candle['close'] > box_bottom:
                            #went down, closed Inside of box
                            action = "[END 5]"
                    elif candle['close'] > box_top and candle['open'] <= box_top:
                        # Candle closes above the zone, potentially starting an upward trend
                        action = "[START 7]" # CALLS
                        candle_type = "PDH" if zone_type in ["resistance", "PDHL"] else "Buffer" #buffer is support
                    elif candle['close'] < box_bottom and candle['open'] >= box_bottom:
                        # Candle closes below the zone, potentially starting a downward trend
                        action = "[START 8]" # PUTS
                        candle_type = "PDL" if zone_type in ["support", "PDHL"] else "Buffer" #buffer if resistance
                        
                    if check_is_in_another_zone:
                        # Additional checks to refine action based on closing inside any other zone
                        for other_box_name, (_, other_high_low_of_day, other_buffer) in zones.items():
                            if other_box_name != box_name:  # Ensure we're not checking the same zone
                                other_box_top = other_high_low_of_day if "resistance" in other_box_name or "PDHL" in other_box_name else other_buffer
                                other_box_bottom = other_buffer if "resistance" in other_box_name or "PDHL" in other_box_name else other_high_low_of_day
                                    
                                # Check if the candle closed inside this other zone
                                if other_box_bottom <= candle['close'] <= other_box_top:
                                    # Modify action to [END #] since we closed inside of another zone
                                    action = "[END 9]"
                                    print(f"    [MODIFIED ACTION] Candle closed inside another zone ({other_box_name}), changing action to {action}.")
                                    break  # Exit the loop since we've found a zone that modifies the action
                    if action:
                        what_type_of_candle = f"{box_name} {candle_type}" if "START" in action else None
                        #havent_cleared = True if what_type_of_candle is not None else False
                        print(f"    [INFO] {action} what_type_of_candle = {what_type_of_candle}; havent_cleared = {havent_cleared}")

            else:
                await asyncio.sleep(1)  # Wait for new candle data
    except Exception as e:
        print(f"[ERROR] {e}")


async def identify_flag(candle, num_flags, what_type_of_candle):
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

    candle_direction = None
    # Check if the 'type' key exists in the candle dictionary
    if 'type' in candle and ('support' in candle['type'] and 'Buffer' in candle['type']) or ('resistance' in candle['type'] and 'PDH' in candle['type']) or ('PDHL PDH' in candle['type']):
        # Bull Candles, We look at Higher Highs
        candle_direction = "bullish"
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_high is None or candle['high'] > current_high:
            # NEW CODE: Somehow check if there already is a flag and if current candle is higher then slopes highest high, if it is it should buy
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'
                )   
            current_high = candle['high']
            highest_point = (candle['candle_index'], current_high)
            print(f"        [Highest Point] New: {highest_point}")
            lower_highs = [] #resetting values
            slope, intercept = None, None #resetting values
            clear_priority_candles(True, what_type_of_candle) #resetting priority candle values because previous candles before the highest one serves no purpose
            await record_priority_candle(candle, what_type_of_candle)
        else: 
            if candle['high'] == current_high and candle['candle_index'] > highest_point[0]:
                #Ok, heres what happened we have a slope and intercept available but we had a equal higher high which should have made a buy order.
                if slope is not None and intercept is not None:
                    slope, intercept, breakout_detected = await process_breakout_detection(
                        line_name, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'
                    ) 
                highest_point = (candle['candle_index'], current_high)
                print(f"        [Highest Point] Updated: {highest_point}")
                lower_highs = [] #resetting values
                slope, intercept = None, None #resetting values
                clear_priority_candles(True, what_type_of_candle) #resetting priority candle values because previous candles before the highest one serves no purpose
                await record_priority_candle(candle, what_type_of_candle)
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
                    update_line_data(line_name, "Bull", "active", highest_point, [None, None])
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'
                        )
                else:
                    print("        [INVALID SLOPE] First point is later than second point.")
                    slope, intercept = None, None
            else:
                print("        [SLOPE] calculation failed or not applicable.")
        elif slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'
            )

        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'
            )
    
    elif ('support' in candle['type'] and 'PDL' in candle['type']) or ('resistance' in candle['type'] and 'Buffer' in candle['type']) or ('PDHL PDL' in candle['type']):
        # Bear Candles, we look at lower lows
        candle_direction = "bearish"
        line_name = f"flag_{num_flags}"
        # Update the current high to the new candle's high if it's higher than the current high
        if current_low is None or candle['low'] < current_low:
            if slope is not None and intercept is not None:
                slope, intercept, breakout_detected = await process_breakout_detection(
                    line_name, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bearish'
                )
            current_low = candle['low']
            lowest_point = (candle['candle_index'], current_low)
            print(f"        [Lowest Point] New: {lowest_point}")
            higher_lows = [] #resetting values
            slope, intercept = None, None #resetting values
            clear_priority_candles(True, what_type_of_candle) #resetting priority candle values because previous candles before the highest one serves no purpose
            await record_priority_candle(candle, what_type_of_candle)
        else: 
            if candle['low'] == current_low and candle['candle_index'] > lowest_point[0]:
                if slope is not None and intercept is not None:
                    slope, intercept, breakout_detected = await process_breakout_detection(
                        line_name, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bearish'
                    )
                lowest_point = (candle['candle_index'], current_low)
                print(f"        [Lowest Point] Updated: {current_low}")
                higher_lows = [] #resetting values
                slope, intercept = None, None #resetting values
                clear_priority_candles(True, what_type_of_candle) #resetting priority candle values because previous candles before the highest one serves no purpose
                await record_priority_candle(candle, what_type_of_candle)
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
                    update_line_data(line_name, "Bear", "active", lowest_point, [None, None]) #lets see if the [None, None] fixes the ongoing flag problem
                    #check if there are any points above the line
                    if slope is not None and intercept is not None:
                        slope, intercept, breakout_detected = await process_breakout_detection(
                            line_name, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bearish'
                        )
                else:
                    print("        [INVALID SLOPE] First point is later than second point.")
                    slope, intercept = None, None
            else:
                print("        [SLOPE] calculation failed or not applicable.")

        elif slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bearish'
            )

        # Check for breakout
        if slope is not None and intercept is not None:
            slope, intercept, breakout_detected = await process_breakout_detection(
                line_name, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bearish'
            )
    else:
        print(f"        [No Support Candle] type = {candle}")    
    
    # Write the updated state back to the JSON file
    with open(state_file_path, 'w') as file:
        json.dump(state, file, indent=4)
    print(f"    [CANDLE DIR] {candle_direction}")
    
    update_state(state_file_path, current_high, highest_point, lower_highs, current_low, lowest_point, higher_lows, slope, intercept, candle)

async def check_for_bearish_breakout(line_name, hl, higher_lows, lowest_point, slope, intercept, candle, config, what_type_of_candle):
    
    if slope and intercept is not None:
        trendline_y = slope * hl[0] + intercept

        if hl[1] < trendline_y:
            print(f"        [BREAKOUT] Potential Breakout Detected at {hl}")

            # Check if the candle associated with this higher low completely closes below the trendline
            if candle['close'] < trendline_y:
                success = await handle_breakout_and_order(
                    what_type_of_candle, lowest_point, trendline_y, line_name, hl[0], line_type="Bear"
                )
                if success:
                    return None, None, True
                else:
                    print(f"        [BREAKOUT] Failure; slope, intercept: {slope}, {intercept}, False")
                    return slope, intercept, False 
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
                what_type_of_candle, lowest_point, trendline_y, line_name, candle['candle_index'], line_type="Bear", calculate_new_trendline=True, slope=slope, intercept=intercept
            )
            if success:
                return None, None, True
            else:
                return slope, intercept, False
    return slope, intercept, False

async def check_for_bullish_breakout(line_name, lh, lower_highs, highest_point, slope, intercept, candle, config, what_type_of_candle):
    
    if slope and intercept is not None:
        #y = mx + b
        trendline_y = slope * lh[0] + intercept
        
        if lh[1] > trendline_y:
            print(f"        [BREAKOUT] Potential Breakout Detected at {lh}")
            # Check if the candle associated with this lower high closes over the slope intercept (trendline_y)
            if candle['close'] > trendline_y:
                success = await handle_breakout_and_order(
                    what_type_of_candle, highest_point, trendline_y, line_name, lh[0], line_type="Bull"
                )
                if success:
                    return None, None, True
                else:
                    print(f"        [BREAKOUT] Failure; slope, intercept: {slope}, {intercept}, False")
                    return slope, intercept, False 
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
                what_type_of_candle, highest_point, trendline_y, line_name, candle['candle_index'], line_type="Bull", calculate_new_trendline=True, slope=slope, intercept=intercept
            )
            if success:
                return None, None, True
            else:
                return slope, intercept, False
    return slope, intercept, False

async def process_breakout_detection(line_name, points, highest_or_lowest_point, slope, intercept, candle, config, what_type_of_candle, breakout_type='bullish'):
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
    for point in points:
        if breakout_type == 'bullish':
            slope, intercept, detected = await check_for_bullish_breakout(
                line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, what_type_of_candle
            )
        else:  # 'bearish'
            slope, intercept, detected = await check_for_bearish_breakout(
                line_name, point, points, highest_or_lowest_point, slope, intercept, candle, config, what_type_of_candle
            )
        if detected:
            breakout_detected = True
            print(f"        [Breakout Detected] {line_name} detected a {breakout_type} breakout at {point}")
            break  # Optional: break if you only care about the first detected breakout
    return slope, intercept, breakout_detected

async def handle_breakout_and_order(what_type_of_candle, hlp, trendline_y, line_name, point, line_type, calculate_new_trendline=False, slope=None, intercept=None):
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
        print(f"        [TRENDLINE] UPDATE: {trendline_y}")
    
    print(f"        [FLAG] UPDATE LINE DATA: {line_name}")
    update_line_data(line_name=line_name, line_type=line_type, status="active", point_1=(hlp[0], hlp[1]), point_2=(point, trendline_y))
    
    #Check emas
    ema_condition_met, ema_price_distance_met = True, True
    #if line_type == 'Bull':
        #ema_condition_met, ema_price_distance_met = await above_below_ema('above', 0.50)
    #else:  # 'Bear'
        #ema_condition_met, ema_price_distance_met = await above_below_ema('below', 0.50)
    
    #check if points are valid
    vp_1, vp_2 = check_valid_points(line_name) #vp means valid point

    # Check if trade limits have been reached in this zone
    multi_order_condition_met = check_order_type_json(what_type_of_candle)

    print(f"        [CONDITIONS] {ema_condition_met}, {vp_1}, {vp_2}, {multi_order_condition_met}, {ema_price_distance_met}")
    if ema_condition_met and vp_1 and vp_2 and multi_order_condition_met and ema_price_distance_met: # if all conditions met, then authorize order, buy
        action = 'call' if line_type == 'Bull' else 'put'
        print(f"    [ORDER CONFIRMED] Buy Signal ({action.upper()})")
        # IMPORTANT: Since we are testing flags we don't need to test the actual buy function.
        #success = await buy_option_cp(is_real_money, symbol, action, session, headers, STRATEGY_NAME)
        #if success: #incase order was canceled because of another active
            #add_candle_type_to_json(what_type_of_candle)
        add_markers("buy")
        #else:
            #print(f"    [ORDER FAIL] Buy Signal ({action.upper()}), what_type_of_candle = {what_type_of_candle}")
        update_line_data(line_name=line_name, line_type=line_type, status="complete")
        return True
    else:
        reason = determine_order_cancel_reason(ema_condition_met, ema_price_distance_met, vp_1, vp_2, multi_order_condition_met)
        
        if not ema_condition_met and (not vp_1 or not vp_2):
            point = "Point 1 None" if not vp_1 else "Point 2 None"
            reason = f"Not above EMAs and Invalid Points; {point}"
        elif not ema_condition_met:
            reason = "Not above EMAs"
        elif not vp_1 or not vp_2:
            point = "Point 1 None" if not vp_1 else "Point 2 None"
            reason = f"Invalid points; {point}"
        
        if not multi_order_condition_met:
            reason = f"Number of trades threshold reached"
        action = 'CALL' if line_type == 'Bull' else 'PUT'
        print(f"    [ORDER CANCELED] Buy Signal ({action}); {reason}.")
        #if any of the vp_1 or vp_2 are false, don't go through. but if vp_1 and vp_2 are both true and not ema_condition_met is true then go through
        if not ema_condition_met and vp_1 and vp_2: #and not multi_order_condition_met:
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

    #update_2_min()