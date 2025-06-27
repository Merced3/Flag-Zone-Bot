import glob
import os
import math
import json
from pathlib import Path
from shared_state import indent, print_log, safe_read_json, safe_write_json
from utils.json_utils import read_config
from utils.data_utils import check_valid_points
from paths import LINE_DATA_PATH, STATES_DIR

# ----------------------
# ⚙️ Configuration
# ----------------------

USE_DICT_STATE = True  # Set to True to use in-memory dictionary storage
STATE_MEMORY = {}  # Holds state files in memory when USE_DICT_STATE is True

# ----------------------
# 🚩 Flag Detection & Breakout Processing
# ----------------------

async def identify_flag(candle, indent_lvl=2, print_satements=True):
    completed_flag_names = []
    ensure_states_dir_exists(STATES_DIR)
    state_files = list(STATE_MEMORY.keys()) if USE_DICT_STATE else glob.glob(os.path.join(STATES_DIR, "state_*.json"))

    for state_file_path in state_files:
        state = get_state(state_file_path, indent_lvl)
        flag_type, flag_names, start_point, slope, intercept, point_type, candle_points, breakout_info = unpack_state(state)

        if print_satements:
            print_log(f"{indent(indent_lvl-1)}[IDF] {flag_type}, '{state_file_path}'")

        if flag_type:
            make_new_flag, current_oc_high, current_oc_low = check_starting_conditions(flag_type, start_point, candle)

            if make_new_flag:
                if slope is not None and intercept is not None:
                    slope, intercept, flag_names, breakout_info, completed_flag_names, point_type, candle_points = await process_breakout_detection(
                        indent_lvl+1, slope, intercept, candle, flag_type, point_type, candle_points, start_point,
                        completed_flag_names, flag_names, breakout_info, print_satements, state_file_path)

                start_point, candle_points, slope, intercept, point_type = await start_new_flag_values(
                    indent_lvl+1, candle, flag_type, current_oc_high, current_oc_low, print_satements)
                breakout_info = return_breakout_info_setup(None, False)
            else:
                candle_points = add_candle_to_candle_points(flag_type, candle, candle_points)

            total_candles = 1 + len(candle_points)
            if print_satements:
                print_log(f"{indent(indent_lvl)}[IDF] Total candles: {total_candles};")

            if total_candles >= read_config('FLAGPOLE_CRITERIA')['MIN_NUM_CANDLES'] and (slope is None or intercept is None):
                slope, intercept, first_point, second_point = calculate_slope_intercept(
                    indent_lvl+1, candle_points, start_point, flag_type, print_satements)
                state_id = os.path.basename(state_file_path).replace(".json", "")
                line_name = f"{state_id}_flag_{flag_type}"
                update_line_data(indent_lvl+1, line_name, flag_type, status="active", point_1=first_point, point_2=second_point, print_statements=print_satements)
                breakout_info = return_breakout_info_setup(None, False)

            elif slope is not None and intercept is not None:
                if print_satements:
                    print_log(f"{indent(indent_lvl)}[IDF PBD 2] process_breakout_detection()")
                slope, intercept, flag_names, breakout_info, completed_flag_names, point_type, candle_points = await process_breakout_detection(
                    indent_lvl+1, slope, intercept, candle, flag_type, point_type, candle_points, start_point,
                    completed_flag_names, flag_names, breakout_info, print_satements, state_file_path)

        else:
            if print_satements:
                print_log(f"{indent(indent_lvl)}[IDF] No Support Candle: {flag_type}")

        update_state(state_file_path, flag_names, flag_type, start_point, slope, intercept, point_type, candle_points, breakout_info, indent_lvl+1)

    manage_states(1, print_satements=print_satements)
    return completed_flag_names

async def process_breakout_detection(indent_lvl, slope, intercept, candle, flag_type, point_type, candle_points, start_point, completed_flag_names, flag_names, breakout_info, print_satements, state_file_path):
    trendline_y = slope * candle['candle_index'] + intercept
    if print_satements:
        print_log(f"{indent(indent_lvl)}[PBD] Slope: {slope}; Intercept: {intercept}")

    detected = await check_for_bullish_breakout(indent_lvl+1, candle, trendline_y, print_satements) if flag_type == 'bull' else await check_for_bearish_breakout(indent_lvl+1, candle, trendline_y, print_satements)
    if print_satements:
        print_log(f"{indent(indent_lvl)}[PBD] Breakout detected: {detected}")

    current_point = formated_candle_point(flag_type, candle)
    candle_points, point_type = filter_candles(indent_lvl+1, start_point, candle_points, current_point, flag_type, print_satements, point_type)
    
    if print_satements:
        print_log(f'{indent(indent_lvl)}[PBD] Last Candle Breakout Active? [{breakout_info["is_active"]}]')

    state_id = state_file_path if USE_DICT_STATE else Path(state_file_path).stem
    line_name = f"{state_id}_flag_{flag_type}"
    
    if not breakout_info["is_active"] and detected:
        first_point = get_active_flag_point_1(line_name, indent_lvl=indent_lvl)
        completed_flag_name = update_line_data(
            indent_lvl,
            line_name,
            flag_type,
            status="complete",
            point_1=(first_point["x"], first_point["y"]) if first_point else (None, None),
            point_2=(candle['candle_index'], trendline_y),
            print_statements=print_satements
        )
        create_state(indent_lvl, flag_type, current_point, print_satements=print_satements)
        point_type = {
            "mode": "pivot",
            "last_pivot_point": current_point
        }
        if print_satements:
            print_log(f"{indent(indent_lvl)}[PBD] Handling Breakout...")
        success, completed_flag = handle_breakout(indent_lvl+1, flag_type, completed_flag_name, print_satements)
        if success:
            completed_flag_names.append(completed_flag)

    slope, intercept, first_point, second_point = calculate_slope_intercept(indent_lvl+1, candle_points, start_point, flag_type, print_satements, current_point[0])
    update_line_data(indent_lvl+1, line_name, flag_type, status="active", point_1=first_point, point_2=second_point, print_statements=print_satements)
    breakout_info = return_breakout_info_setup(current_point, True) if detected else return_breakout_info_setup(None, False)

    return slope, intercept, flag_names, breakout_info, completed_flag_names, point_type, candle_points

async def check_for_bearish_breakout(indent_lvl, candle, trendline_y, print_satements):
    if print_satements:
        print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT] Potential Breakout Detected")

    if candle['close'] < trendline_y and candle['close'] <= candle['open']:
        if print_satements:
            print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT CONFIRMED] Candle Closed Below Trend Line")
        return True
    else:
        if print_satements:
            print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT FAILED] Candle Went UP")
        return False

async def check_for_bullish_breakout(indent_lvl, candle, trendline_y, print_satements):
    if print_satements:
        print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT] Potential Breakout Detected")

    if candle['close'] > trendline_y and candle['open'] <= candle['close']:
        if print_satements:
            print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT CONFIRMED] Candle Closed Above Trend Line")
        return True
    else:
        if print_satements:
            print_log(f"{indent(indent_lvl)}[CFBB BREAKOUT FAILED] Candle Went DOWN")
        return False

def handle_breakout(indent_lvl, line_type, line_name, print_satements):
    #check if points are valid
    vp_1, vp_2, line_degree_angle, correct_flag = check_valid_points(indent_lvl+1, line_name, line_type, print_satements) #vp means valid point
    if print_satements:
        print_log(f"{indent(indent_lvl)}[HB CONDITIONS] {line_name}: {vp_1}, {vp_2}, {line_degree_angle}, {correct_flag}")
    
    # Check if lines points and flag is valid
    action = 'CALL' if line_type == 'Bull' else 'PUT'
    if vp_1 and vp_2 and correct_flag:
        if print_satements:
            print_log(f"{indent(indent_lvl)}[HB] FLAG CONFIRMED ({action})")
        return True, line_name
    else:
        reason = determine_flag_cancel_reason(vp_1, vp_2, correct_flag)
        if print_satements:
            print_log(f"{indent(indent_lvl)}[HB] FlAG CANCELED ({action}); {reason}.")
        return False, None
    
# ----------------------
# 🏁 Flag Initialization & Updates
# ----------------------

def check_starting_conditions(flag_type, start_point, candle):
    """
    Checks whether a new flag should be created.
    """
    current_oc_high = max(candle['close'], candle['open'])
    current_oc_low = min(candle['close'], candle['open'])

    make_bull_starting_point = flag_type == "bull" and (start_point is None or current_oc_high > start_point[1])
    make_bear_starting_point = flag_type == "bear" and (start_point is None or current_oc_low < start_point[1])

    return make_bull_starting_point or make_bear_starting_point, current_oc_high, current_oc_low

async def start_new_flag_values(indent_level, candle, candle_flag_type, current_oc_high, current_oc_low, print_satements):
    # Set new starting point
    current_hl = candle['high'] if candle_flag_type == "bull" else candle['low']
    important_candle_value = current_oc_high if candle_flag_type == "bull" else current_oc_low
    start_point = (candle['candle_index'], important_candle_value, current_hl)
    if print_satements:
        print_log(f"{indent(indent_level)}[SNFV] {'Highest' if candle_flag_type=='bull' else 'Lowest'} Point: {start_point}")
    point_type = {
        "mode": "flow",
        "last_pivot_point": None
    }

    return start_point, [], None, None, point_type

def update_line_data(indent_lvl, line_name, line_type, status=None, point_1=None, point_2=None, print_statements=True):
    data = safe_read_json(LINE_DATA_PATH, default={}, indent_lvl=indent_lvl+1)

    if not isinstance(data, dict):
        data = {}

    data.setdefault("active_flags", [])
    data.setdefault("completed_flags", [])
    
    # Define the updated flag line entry
    line_data = {
        "name": line_name,
        "type": line_type,
        "point_1": {"x": point_1[0], "y": point_1[1]} if point_1 else {"x": None, "y": None},
        "point_2": {"x": point_2[0], "y": point_2[1]} if point_2 else {"x": None, "y": None},
    }

    if status == "complete":
        # Give completed flags a new unique name to avoid overwriting
        completed_name = f"{line_name}_{count_flags(line_type)}"
        line_data["name"] = completed_name
        data["completed_flags"].append(line_data)
    else:
        # Remove any existing active version before updating
        data["active_flags"] = [line for line in data["active_flags"] if line["name"] != line_name]
        data["active_flags"].append(line_data)

    saved_correctly = safe_write_json(LINE_DATA_PATH, data, indent_lvl=indent_lvl+1)
    
    if print_statements:
        status_msg = "SAVED" if saved_correctly else "FALIED to save"
        location = "completed_flags" if status == "complete" else "active_flags"
        print_log(f"{indent(indent_lvl)}[ULD FLAG] '{line_data['name']}' → {status_msg} to '{location}'")

    return line_data["name"]

def count_flags(flag_type):
    """
    Counts all flags (active + completed) of a specific type.
    """
    try:
        with open(LINE_DATA_PATH, 'r') as file:
            data = json.load(file)
            all_flags = data.get("active_flags", []) + data.get("completed_flags", [])
            return len([flag for flag in all_flags if flag.get('type') == flag_type])
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

def get_active_flag_point_1(line_name, indent_lvl=0):
    """
    Retrieves the 'point_1' from an active flag in line_data.json using the given line_name.
    """
    try:
        data = safe_read_json(LINE_DATA_PATH, default={}, indent_lvl=indent_lvl+1)
        for flag in data.get("active_flags", []):
            if flag["name"] == line_name:
                return flag.get("point_1", (None, None))
    except Exception as e:
        print_log(f"{indent(indent_lvl)}[GAFP1 ERROR] {e}")
    return (None, None)

# ----------------------
# 🏗️ State Management & Persistence
# ----------------------

def get_state(state_file_path, indent_lvl):
    """
    Loads state from memory or file.
    """
    return STATE_MEMORY.get(state_file_path, get_state_structure()) if USE_DICT_STATE else \
        safe_read_json(state_file_path, default=get_state_structure(), indent_lvl=indent_lvl+1)

def unpack_state(state):
    """
    Extracts state variables for easy use.
    """
    return state["flag_type"], state["flag_names"], state["start_point"], state["slope"], state["intercept"], \
           state["point_type"], state["candle_points"], state["breakout_tracker"]

def get_state_structure():
    """
    Defines the structure of the state file.
    This ensures consistency across all state-related operations.

    Returns:
        dict: Default structure for state files.
    """
    return {
        # Flag Identification
        "flag_type": None,  # "bear" or "bull"
        "flag_names": [],  # ["flag_bear_1", "flag_bear_2", "flag_bull_3", ...]

        # Trendline Information
        "start_point": None,  # [X, Y, Y²]
        "slope": None,
        "intercept": None,

        # Price Action Context
        "point_type": {
            "mode": None, # "pivot" or "flow"
            "last_pivot_point": None
        }, 
        "candle_points": [],  # [[X, Y, Y²], [X, Y, Y²], ...] -> Stores pivot or flow points

        # Breakout Tracking
        "breakout_tracker": {
            "last_breakout_candle": None,  # Stores the last candle that triggered a breakout
            "is_active": False  # Indicates whether the breakout condition is currently active
        }
    }

def create_state(indent_lvl, flag_type, start_point, print_satements=True):
    """
    Creates a new state entry, either in memory (`STATE_MEMORY`) or in a file (`states/`).

    Args:
        indent_lvl (int): Indentation level for logging.
        flag_type (str): Type of the flag ('bear' or 'bull').
        start_point (tuple): Starting point of the flag (X, Y, Y²).
        directory (str): Directory to store state JSON files if using file-based storage.

    Returns:
        str: The name or key of the created state.
    """
    
    if USE_DICT_STATE:
        # Extract existing numbers from STATE_MEMORY keys
        existing_numbers = sorted(
            [int(k.split("_")[1]) for k in STATE_MEMORY.keys() if k.startswith("state_") and k.split("_")[1].isdigit()]
        )
    else:
        # Extract existing numbers from actual files
        existing_files = [f for f in os.listdir(STATES_DIR) if f.startswith("state_") and f.endswith(".json")]
        existing_numbers = sorted(
            [int(f.split("_")[1].split(".")[0]) for f in existing_files if f.split("_")[1].split(".")[0].isdigit()]
        )
    
    # Find the lowest missing state number
    state_number = 1
    for num in existing_numbers:
        if num != state_number:
            break  # Found the first missing number
        state_number += 1  # Increment to find the next available number
    
    # Construct the correct name
    state_name = f"state_{state_number}"
    state_file = STATES_DIR / f"{state_name}.json"

    # Initialize state structure
    state_data = get_state_structure()
    state_data["flag_type"] = flag_type
    state_data["start_point"] = start_point
    state_data["point_type"] = {
        "mode": "flow",
        "last_pivot_point": None
    }

    if USE_DICT_STATE:
        STATE_MEMORY[state_name] = state_data  # Store in memory
    else:
        safe_write_json(state_file, state_data, indent_lvl=indent_lvl)  # Save to file

    if print_satements:
        print_log(f"{indent(indent_lvl)}[CTS] Created '{flag_type}' state: {state_name}")
    return state_name

def manage_states(indent_lvl, print_satements=True):
    if print_satements:
        print_log(f"{indent(indent_lvl)}[MSF] Managing State Files...")
    
    if USE_DICT_STATE:
        state_files = list(STATE_MEMORY.keys())  # Get all in-memory state keys
    else:
        state_files = STATES_DIR / "state_*.json"
    
    # Sort state files numerically
    state_files.sort(key=lambda f: int(os.path.basename(f).split('_')[1].split('.')[0]))
    
    seen_start_points = {}

    for state_file in state_files:
        if USE_DICT_STATE:
            state = STATE_MEMORY.get(state_file, get_state_structure())
        else:
            state = safe_read_json(state_file, default=get_state_structure(), indent_lvl=indent_lvl+1)

        start_point = tuple(state["start_point"])
        if start_point in seen_start_points:
            if USE_DICT_STATE:
                del STATE_MEMORY[state_file]
            else:
                os.remove(state_file)
            if print_satements:
                print_log(f"{indent(indent_lvl)}[MSF] Removed duplicate state: {state_file}")
        else:
            seen_start_points[start_point] = state_file

def update_state(state_file_path, flag_names, flag_type, start_point, slope, intercept, point_type, candle_points, breakout_info, indent_lvl):
    
    if USE_DICT_STATE:
        # Use in-memory storage
        state = STATE_MEMORY.get(state_file_path, get_state_structure())
    else:
        # Read from JSON file
        state = safe_read_json(state_file_path, default=get_state_structure(), indent_lvl=indent_lvl)

    # Update state values
    state.update({
        "flag_names": flag_names,
        "flag_type": flag_type,
        "start_point": start_point,
        "slope": slope,
        "intercept": intercept,
        "point_type": point_type
    })

    # Update candle points (remove duplicates and sort)
    new_candle_points = [tuple(cp) for cp in candle_points if cp[0] > start_point[0]]
    state["candle_points"] = sorted(set(new_candle_points), key=lambda x: x[0]) if new_candle_points else []
    
    # Handle breakout tracker logic (if needed)
    if "breakout_tracker" not in state:
        state["breakout_tracker"] = {"last_breakout_candle": None, "is_active": False}
    

    state["breakout_tracker"].update(breakout_info)

    # Save based on storage method
    if USE_DICT_STATE:
        STATE_MEMORY[state_file_path] = state
    else:
        correctly_saved = safe_write_json(state_file_path, state, indent_lvl=indent_lvl)
        if not correctly_saved:
            print_log(f"{indent(indent_lvl)}[US] Failed to save State: {state_file_path}")

# ----------------------
# 📈 Trendline & Slope Calculations
# ----------------------

def calculate_slope_intercept(indent_lvl, points, start_point, flag_type="bull", print_satements=True, current_point_x=None):
    """
    Calculates the slope and intercept for trendlines.
    """
    if print_satements:
        print_log(f"{indent(indent_lvl)}[CSI] Calculating Slope Line...")

    if start_point not in points: # Ensure the start_point is included in the points list
        points = [start_point] + points
    points = sorted(points, key=lambda x: x[0]) # Sort by X
    
    # Calculate slope (m) using the linear regression formula
    n = len(points)
    sum_x = sum(point[0] for point in points)
    sum_y = sum(point[1] for point in points)
    sum_xy = sum(point[0] * point[1] for point in points)
    sum_x_squared = sum(point[0] ** 2 for point in points)
    
    denominator = n * sum_x_squared - sum_x ** 2
    if denominator == 0:  # Check for vertical line or insufficient points
        if print_satements:
            print_log(f"{indent(indent_lvl)}[CSI ERROR] ZeroDivisionError avoided. Vertical line or insufficient data. Points: {points}")
        return None, None, None, None
    
    # m = [n(Σxy) - (Σx)(Σy)] / [n(Σx²) - (Σx)²]
    slope = (n * sum_xy - sum_x * sum_y) / denominator
    mean_x, mean_y = sum_x / n, sum_y / n
    intercept = mean_y - slope * mean_x
    
    # Perform the translation to avoid the slope line cutting through the body of the candles
    intercept = max(point[1] - slope * point[0] for point in points) if flag_type == "bull" else min(point[1] - slope * point[0] for point in points)

    # Validate and log the angle (log optional)
    angle_valid, angle = is_angle_valid(indent_lvl+1, slope, flag_type, print_satements)

    first_new_Y = slope * start_point[0] + intercept    
    first_point = (start_point[0], first_new_Y) if angle_valid else (None, None)
    
    # current_point_x if available, otherwise default to last known point
    second_x = current_point_x if current_point_x is not None else points[-1][0]
    second_new_Y = slope * second_x + intercept
    second_point = (second_x, second_new_Y) if angle_valid else (None, None)
    
    return slope, intercept, first_point, second_point

def is_angle_valid(indent_lvl, slope, flag_type, print_satements):
    """
    Calculates the angle of the slope and checks if it is within the valid range specified in the config.
    
    Args:
        slope (float): The slope of the line.
        flag_type (str): The type of flag ('bull' or 'bear').

    Returns:
        tuple: (bool, float) - A boolean indicating if the angle is valid, and the calculated angle in degrees.
    """
    # If slope is exactly zero, set angle to 0
    if slope == 0.0:
        angle = 0.0
    else:
        # Calculate the angle in degrees
        angle = math.atan(slope) * (180 / math.pi)
    
    # Extract min and max angles from config
    min_angle = read_config('FLAGPOLE_CRITERIA')['MIN_ANGLE']
    max_angle = read_config('FLAGPOLE_CRITERIA')['MAX_ANGLE']

    # Adjust the angle check based on bullish or bearish criteria
    if flag_type == "bear":
        # Bearish has positive angles (upward)
        is_valid = max_angle >= angle >= min_angle  
    else:
        # Bullish has negative angles (downward)
        is_valid = -min_angle >= angle >= -max_angle
    
    if print_satements:
        print_log(f"{indent(indent_lvl)}[IAV] Angle/Degree: {angle}, isValid: {is_valid}")
    return is_valid, angle

# ----------------------
# 🔍 Flag & Candle Filtering
# ----------------------

def filter_candles(indent_lvl, start_point, candle_points, current_point, candle_type, print_statements, point_type):
    """
    Filters candle points based on their position relative to a trendline drawn from 
    start_point to current_point. Behavior adapts based on the point_type mode:
    - In "flow" mode: keeps points above (bull) or below (bear) the trendline and adds the current_point if needed.
    - In "pivot" mode: keeps only pivot-valid points that occurred before or at the last_pivot_point and respect both the main trendline and the PCO line.

    Args:
        start_point (tuple): The initial reference point (X, Y, Y2).
        candle_points (list): List of (X, Y, Y2) tuples to evaluate.
        current_point (tuple): The most recent breakout candle (X, Y, Y2).
        candle_type (str): "bull" or "bear" — defines direction of trend.
        print_statements (bool): Whether to print debug logs.
        point_type (dict): Dictionary tracking:
            - mode (str): "flow" or "pivot"
            - last_pivot_point (tuple): Most recent valid pivot reference (used in pivot mode).

    Returns:
        tuple: (filtered_candle_points (list), updated_point_type (dict))
    """

    mode = point_type.get("mode", "flow")
    pivot_cutoff = point_type.get("last_pivot_point", None)
    before_cal = len(candle_points)
    EPSILON = 1e-6  # Tolerance for floating-point equality
    
    x1, y1 = start_point[0], start_point[1]
    x2, y2 = current_point[0], current_point[1]
    slope = (y2 - y1) / (x2 - x1) if x2 - x1 != 0 else float('inf')
    intercept = y1 - slope * x1

    # Prepare PCO line if in pivot mode (Pivot Cut Off)
    if mode == "pivot" and pivot_cutoff:
        pco_x, pco_y = pivot_cutoff[0], pivot_cutoff[1]
        pco_slope = (pco_y - y1) / (pco_x - x1) if pco_x - x1 != 0 else float('inf')
        pco_intercept = y1 - pco_slope * x1

    filtered_points = []

    for point in candle_points:
        x, y = point[0], point[1]
        line_y = slope * x + intercept
        if candle_type == "bull":
            is_valid = y >= line_y - EPSILON
        else:
            is_valid = y <= line_y + EPSILON
        
        is_valid_pivot_point = None
        if mode == "pivot" and pivot_cutoff and is_valid:
            poc_line_y = pco_slope * x + pco_intercept
            if candle_type == "bull":
                is_valid_pivot_point = y >= poc_line_y - EPSILON
            else:
                is_valid_pivot_point = y <= poc_line_y + EPSILON

            if is_valid_pivot_point:
                point_type["last_pivot_point"] = point
                filtered_points.append(point)
                if print_statements:
                    print_log(f"{indent(indent_lvl)}[FC pivot] {point[0]} passed both checks ✅")
        else:
            if print_statements:
                main_line_result = "✅" if is_valid else "❌"
                pco_line_result = "✅" if is_valid_pivot_point else "❌" if is_valid_pivot_point is not None else "N/A"
                failed_reason = ""

                if not is_valid:
                    diff = y - line_y
                    failed_reason += f"MAIN FAIL → y={y:.4f} not {'>=' if candle_type=='bull' else '<='} main_line_y={line_y:.4f} (diff={diff:+.6f}); "
                if is_valid and is_valid_pivot_point is False:
                    failed_reason += f"PCO FAIL → y={y:.4f} not {'>=' if candle_type=='bull' else '<='} pco_y={poc_line_y:.4f}"

                print_log(
                    f"{indent(indent_lvl)}[FC pivot] {point[0]} failed checks: main={main_line_result}, pco={pco_line_result} ❌ | {failed_reason.strip()}"
                )
        if mode == "flow" and is_valid:
            # Check if a point with the same Y value already exists
            existing = next((p for p in filtered_points if abs(p[1] - point[1]) < 1e-6), None)
            if existing:
                # If current point has higher X, replace the old one
                if point[0] > existing[0]:
                    filtered_points.remove(existing)
                    filtered_points.append(point)
                    if print_statements:
                        print_log(f"{indent(indent_lvl)}[FC flow] {point} replaced {existing} ✅ (same Y)")
                else:
                    if print_statements:
                        print_log(f"{indent(indent_lvl)}[FC flow] {point} skipped ❌ (older X for same Y)")
            else:
                filtered_points.append(point)
                if print_statements:
                    print_log(f"{indent(indent_lvl)}[FC flow] {point} added ✅")

    filtered_points = sorted(filtered_points, key=lambda p: p[0]) # Sort by X (candle index)
    after_cal = len(filtered_points)
    
    if print_statements:
        print_log(f"{indent(indent_lvl)}[FC] Before: {before_cal}, After: {after_cal}")

    return filtered_points, point_type

# ----------------------
# 🛠️ Utility & Helper Functions
# ----------------------

def return_breakout_info_setup(current_point, status):
    return {
        "last_breakout_candle": current_point,
        "is_active": status
    }

def determine_flag_cancel_reason(vp_1, vp_2, correct_flag):
    reasons = []
    if not vp_1 and not vp_2:
        reasons.append(f"Invalid points; Both Points None")
    if not vp_1 or not vp_2:
        point = "Point 1 None" if not vp_1 else "Point 2 None"
        reasons.append(f"Invalid points; {point}")
    if not correct_flag:
        reasons.append("Incorrect Flag values for given flag")
    return "; ".join(reasons) if reasons else "No specific reason"

def formated_candle_point(flag_type, candle):
    # 'oc' means Open or Close
    if flag_type == "bull":              # Bull candle list
        candle_oc = candle['open'] if candle['open']>=candle['close'] else candle['close']
        return (candle['candle_index'], candle_oc, candle['high'])
    else:                                # Bear candle list
        candle_oc = candle['close'] if candle['close']<=candle['open'] else candle['open']
        return (candle['candle_index'], candle_oc, candle['low'])

def add_candle_to_candle_points(flag_type, candle, candle_points):
    # Append point to point list
    candle_points.append(formated_candle_point(flag_type, candle))
    # Organize the points into ascending order, where the X value is the indicator for the order
    candle_points = sorted(candle_points, key=lambda x: x[0])
    return candle_points 

def ensure_states_dir_exists(states_dir):
    if not os.path.exists(states_dir) and not USE_DICT_STATE:
        os.makedirs(states_dir)
        print_log(f"[INIT] Created missing directory: {states_dir}")

def clear_all_states(indent_lvl=1):
    """
    Clears all state data, both from disk and from in-memory dictionary.
    This ensures a fresh start regardless of storage mode.
    """
    if USE_DICT_STATE:
        STATE_MEMORY.clear()
        print_log(f"{indent(indent_lvl)}[RESET] In-memory STATE_MEMORY cleared.")
    else:
        if not os.path.exists(STATES_DIR):
            print_log(f"{indent(indent_lvl)}[RESET] State folder '{STATES_DIR}' does not exist.")
            return
        json_files = glob.glob(os.path.join(STATES_DIR, "*.json"))
        for file in json_files:
            try:
                os.remove(file)
                print_log(f"{indent(indent_lvl)}[RESET] Deleted state file: {file}")
            except Exception as e:
                print_log(f"{indent(indent_lvl)}[RESET ERROR] Could not delete {file}: {e}")
