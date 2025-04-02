# shared_state.py
from pathlib import Path
import asyncio
import json
import time

# Global shared variables
latest_price = None  # To store the latest price
price_lock = asyncio.Lock()  # To ensure thread-safe access

latest_sentiment_score = {"score": 0} # Used for order_handler.py access

# Define the logs directory and file path
LOGS_DIR = Path(__file__).resolve().parent / 'logs'
LOG_FILE_PATH = LOGS_DIR / 'terminal_output.log'

def print_log(message: str):
    """
    Logs a message to the terminal and appends it to a log file.
    Includes a timestamp for each entry.
    """
    #timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    #formatted_message = f"{timestamp} {message}"

    # Print the message to the console
    print(message)

    # Ensure the logs folder exists
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # Ensure the log file exists
    if not LOG_FILE_PATH.exists():
        LOG_FILE_PATH.touch()  # Create the file if it doesn't exist

    # Append the message to the log file
    with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(message + "\n")

def indent(level=1):
    """
    Returns a string with `level` indentation of 4 spaces.
    
    Args:
        level (int): Number of indentation levels (each level = 4 spaces).
        
    Returns:
        str: Indentation string.
    """
    if level==0 or level==None:
        return ""
    return " " * (4 * level)

def safe_read_json(file_path, retries=5, delay=0.1, default=None, indent_lvl=None):
    """
    Safely reads a JSON file, with retry logic for handling concurrent access and errors. Ensures the returned value matches the type of `default`.

    Args:
        file_path (str or Path): The path to the JSON file.
        retries (int): Number of retries if an error occurs.
        delay (float): Delay between retries, in seconds.
        default: The default value to return if reading fails. Determines the expected return type.

    Returns:
        Any: Parsed JSON content if successful, or the `default` value (with matching type).
    """
    if default is None:
        default = []  # Default to an empty list if not specified

    expected_type = type(default)  # Determine the type of the expected return value
    file_path = Path(file_path)

    for attempt in range(retries):
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

                # Check if the returned data matches the expected type
                if not isinstance(data, expected_type):
                    print_log(f"{indent(indent_lvl)}[SAFE READ] Mismatched type. Converting {type(data)} to {expected_type}.")
                    if expected_type == list:
                        return list(data) if isinstance(data, (dict, set)) else [data]
                    elif expected_type == dict:
                        # Special handling for legacy list structure in 'line_data.json'
                        if isinstance(data, list) and file_path.name == "line_data.json":
                            return {
                                "active_flags": data,
                                "completed_flags": []
                            }
                        return dict(data) if isinstance(data, (list, set)) else {}
                    elif expected_type == str:
                        return str(data)
                    elif expected_type == int:
                        return int(data) if str(data).isdigit() else 0
                    elif expected_type == float:
                        return float(data) if isinstance(data, (int, str)) else 0.0
                    else:
                        return default  # Return the default value if conversion is not possible

                return data  # Return the data as is if the type matches
        except FileNotFoundError:
            print_log(f"{indent(indent_lvl)}[SAFE READ] File not found: {file_path}")
            return default
        except json.JSONDecodeError:
            print_log(f"{indent(indent_lvl)}[SAFE READ] Invalid JSON in {file_path}, retrying... (Attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print_log(f"{indent(indent_lvl)}[SAFE READ] Failed to parse JSON after {retries} attempts.")
                return default
        except PermissionError:
            print_log(f"{indent(indent_lvl)}[SAFE READ] Permission denied: {file_path}, retrying... (Attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print_log(f"{indent(indent_lvl)}[SAFE READ] Permission denied after {retries} attempts.")
                return default
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[SAFE READ] Unexpected error: {e}")
            return default

    return default  # Fallback return in case of unexpected issues

def safe_write_json(file_path, content, retries=5, delay=0.1, indent_lvl=None):
    """
    Safely writes content to a JSON file, with retry logic for handling concurrent access and errors.

    Args:
        file_path (str or Path): The path to the JSON file.
        content (Any): The content to write to the JSON file (must be JSON-serializable).
        retries (int): Number of retries if an error occurs. Defaults to 5.
        delay (float): Delay between retries, in seconds. Defaults to 0.1.
        indent_lvl (int, optional): Indentation level for logging.

    Returns:
        bool: True if the write operation is successful, False otherwise.
    """
    file_path = Path(file_path)

    for attempt in range(retries):
        try:
            # Write JSON content to file
            temp_file = file_path.with_suffix(".tmp")
            with open(temp_file, 'w') as f:
                json.dump(content, f, indent=4)
            temp_file.replace(file_path)  # Atomically replace the original file

            #print_log(f"{indent(indent_lvl)}[SAFE WRITE] Successfully wrote to '{file_path}'")
            return True  # Successfully written

        except PermissionError:
            print_log(f"{indent(indent_lvl)}[SAFE WRITE] Permission denied: {file_path}, retrying... (Attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print_log(f"{indent(indent_lvl)}[SAFE WRITE] Permission denied after {retries} attempts.")
                return False

        except Exception as e:
            print_log(f"{indent(indent_lvl)}[SAFE WRITE] Unexpected error: {e}, retrying... (Attempt {attempt + 1}/{retries})")
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                print_log(f"{indent(indent_lvl)}[SAFE WRITE] Failed to write after {retries} attempts.")
                return False

    return False  # Fallback return in case of failure


