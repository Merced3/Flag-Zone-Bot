# utils/json_utils.py, Load/save/validate JSON, config helpers
import json
from shared_state import indent, print_log
from error_handler import error_log_and_discord_message
from utils.file_utils import get_current_candle_index
import pandas as pd
import os
from paths import CONFIG_PATH, MESSAGE_IDS_PATH, ORDER_CANDLE_TYPE_PATH, EMAS_PATH, PRIORITY_CANDLES_PATH, LINE_DATA_PATH

def read_config(key=None):
    """Reads the configuration file and optionally returns a specific key."""
    with CONFIG_PATH.open("r") as f:
        config = json.load(f)
    if key is None:
        return config  # Return the whole config if no key is provided
    return config.get(key)  # Return the specific key's value or None if key doesn't exist

# I DONT SEE ANYWHERE IN THE PROGRAM WHERE THIS IS USED, SO I DONT KNOW IF IT IS NEEDED
def load_message_ids():
    if os.path.exists(MESSAGE_IDS_PATH):
        with open(MESSAGE_IDS_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    else:
        return {}

def update_config_value(key, value):
    """Update a single key in the config file with a new value."""
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    config[key] = value
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=4)

def load_json_df(file_path):
    with open(file_path, 'r') as file:
        data = json.load(file)
    return pd.DataFrame(data)

def update_ema_json(json_path, new_ema_values):
    """Update the EMA JSON file with new EMA values by appending."""
    try:
        with open(json_path, 'r') as file:
            ema_data = json.load(file)
    except json.JSONDecodeError:
        ema_data = []  # Initialize as empty list if file is corrupt or empty

    # Append new EMA values
    ema_data.append(new_ema_values)

    # Write the updated list back to the file
    with open(json_path, 'w') as file:
        json.dump(ema_data, file, indent=4)

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

async def read_ema_json(position):
    try:
        with open(EMAS_PATH, "r") as file:
            emas = json.load(file)
            latest_ema = emas[position]
            return latest_ema
    except FileNotFoundError:
        print_log("EMAs.json file not found.")
        return None
    except KeyError:
        print_log(f"EMA type [{position}] not found in the latest entry.")
        return None
    except Exception as e:
        await error_log_and_discord_message(e, "ema_strategy", "read_last_ema_json")
        return None
    
def reset_json(file_path, contents):
    with open(file_path, 'w') as f:
        json.dump(contents, f, indent=4)
        print_log(f"[RESET] Cleared file: {file_path}")

def get_correct_message_ids():
    if os.path.exists(MESSAGE_IDS_PATH):
        with open(MESSAGE_IDS_PATH, 'r') as file:
            json_message_ids_dict = json.load(file)
            #print (f"{json_message_ids_dict}")
    else:
        json_message_ids_dict = {}
    
    return json_message_ids_dict

def add_candle_type_to_json(candle_type):
    # Read the current contents of the file, or initialize an empty list if file does not exist
    try:
        with open(ORDER_CANDLE_TYPE_PATH, 'r') as file:
            candle_types = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print_log("File not found or is empty. Starting a new list.")
        candle_types = []

    # Append the new candle_type to the list
    candle_types.append(candle_type)

    # Write the updated list back to the file
    with open(ORDER_CANDLE_TYPE_PATH, 'w') as file:
        json.dump(candle_types, file, indent=4)  # Using indent for better readability of the JSON file

def check_order_type_json(candle_type):
    try:
        with open(ORDER_CANDLE_TYPE_PATH, 'r') as file:
            candle_types = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        print_log("Error reading the file or file not found. Assuming no orders have been placed.")
        candle_types = []

    # Count how many times the given candle_type appears in the list
    num_of_matches = candle_types.count(candle_type)
    #print(num_of_matches)
    # Compare the count with the threshold
    if num_of_matches >= read_config('ORDERS_ZONE_THRESHOLD'):
        return False, num_of_matches # More or equal matches than the threshold, do not allow more orders

    return True, num_of_matches  # Fewer matches than the threshold, allow more orders

def clear_priority_candles(indent_level):
    with open(PRIORITY_CANDLES_PATH, 'w') as file:
        json.dump([], file, indent=4)
    print_log(f"{indent(indent_level)}[RESET] {PRIORITY_CANDLES_PATH} = [];")

async def record_priority_candle(candle, zone_type_candle):
    # Load existing data or initialize an empty list
    try:
        with open(PRIORITY_CANDLES_PATH, 'r') as file:
            candles_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        candles_data = []

    current_candle_index = get_current_candle_index()

    # Append the new candle data along with its type
    candle_with_type = candle.copy()
    candle_with_type['zone_type'] = zone_type_candle
    #candle_with_type['dir_type'] = bull_or_bear_candle
    candle_with_type['candle_index'] = current_candle_index
    candles_data.append(candle_with_type)

    # Save updated data back to the file
    with open(PRIORITY_CANDLES_PATH, 'w') as file:
        json.dump(candles_data, file, indent=4)

def restart_state_json(indent_level, state_file_path):
    initial_state = {
        'flag_names': [],
        'flag_type': None,
        'start_point': None,
        'slope': None,
        'intercept': None,
        'candle_points': []
        
    }
    
    with open(state_file_path, 'w') as file:
        json.dump(initial_state, file, indent=4)
    print_log(f"{indent(indent_level)}[RESET] State JSON file has been reset to initial state.")

def resolve_flags(indent_level):
    
    if LINE_DATA_PATH.exists():
        with open(LINE_DATA_PATH, 'r') as file:
            line_data = json.load(file)
    else:
        print_log(f"{indent(indent_level)}[FLAG ERROR] File {LINE_DATA_PATH} not found.")
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
                print_log(f"{indent(indent_level)}[FLAG] Active flags resolved.")
            # Skip adding the flag to updated_line_data if it's active and has invalid points
        else:
            updated_line_data.append(flag)

    # Save the updated data back to the JSON file
    with open(LINE_DATA_PATH, 'w') as file:
        json.dump(updated_line_data, file, indent=4)

def save_message_ids(order_id, message_id):
    # Load existing data
    if MESSAGE_IDS_PATH.exists():
        with open(MESSAGE_IDS_PATH, 'r') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = {}
    else:
        existing_data = {}

    # Update existing data with new data
    existing_data[order_id] = message_id

    # Write updated data back to file
    with open(MESSAGE_IDS_PATH, 'w') as f:
        json.dump(existing_data, f, indent=4)
