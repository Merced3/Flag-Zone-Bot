# utils/log_utils.py
import json
from shared_state import print_log
from paths import LOGS_DIR, STORAGE_DIR, TERMINAL_LOG, ORDER_LOG_PATH, SPY_15_MINUTE_CANDLES_PATH, MARKERS_PATH, EMAS_PATH, MESSAGE_IDS_PATH, LINE_DATA_PATH, ORDER_CANDLE_TYPE_PATH, PRIORITY_CANDLES_PATH
from utils.json_utils import reset_json, read_config
import pandas as pd
import os

def read_log_to_df(log_file_path):
    """Read log data into a DataFrame."""
    return pd.read_json(log_file_path, lines=True)

def write_to_log(data, symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with filepath.open("a") as file:
        json_data = json.dumps(data)
        file.write(json_data + "\n")

def clear_log(symbol=None, timeframe=None, terminal_log=None):
    filepath = None
    if symbol and timeframe:
        filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    if terminal_log:
        filepath = LOGS_DIR / terminal_log
    if filepath and filepath.exists():
        filepath.unlink()

"""def read_log_file(log_file_path):
    try:
        with open(log_file_path, 'r') as file:
            return file.read()
    except FileNotFoundError:
        print_log(f"File {log_file_path} not found.")
        return ""

def write_log_data_as_string(data, symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with filepath.open("a") as file:
        file.write(data + "\n")"""

def empty_log(filename):
    """
    Empties the contents of the specified log file.

    Args:
    filename (str): The base name of the log file without extension.
    """
    # Ensure the logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
    
    # Path to the log file
    log_file_path = os.path.join(LOGS_DIR, f'{filename}.log')

    # Open the file in write mode to truncate it
    with open(log_file_path, 'w') as file:
        pass  # Opening in write mode ('w') truncates the file automatically

    print_log(f"[CLEARED]'{filename}.log' has been emptied.")

def clear_symbol_log(symbol, timeframe):
    filepath = LOGS_DIR / f"{symbol}_{timeframe}.log"
    if filepath.exists():
        filepath.unlink()

def clear_terminal_log():
    if TERMINAL_LOG.exists():
        TERMINAL_LOG.unlink()

def clear_temp_logs_and_order_files():
    # Only keep the main order archive
    protected_files = {
        ORDER_LOG_PATH,
        SPY_15_MINUTE_CANDLES_PATH
    }

    files_to_delete = set()

    # 1. Delete temp order_log* files and all CSVs in logs/ (except protected)
    for file_path in LOGS_DIR.glob('*order_log*'):
        if file_path not in protected_files:
            files_to_delete.add(file_path)
    for file_path in LOGS_DIR.glob('*.csv'):
        if file_path not in protected_files:
            files_to_delete.add(file_path)

    # 2. Clean all relevant JSON state files in storage/
    json_reset_instructions = {
        MARKERS_PATH: [],
        EMAS_PATH: [],
        MESSAGE_IDS_PATH: {},
        LINE_DATA_PATH: {},
        ORDER_CANDLE_TYPE_PATH: [],
        PRIORITY_CANDLES_PATH: []
    }
    for filename, default_value in json_reset_instructions.items():
        reset_json(str(STORAGE_DIR / filename), default_value)

    # 3. Delete all files found in logs/
    for file_path in files_to_delete:
        try:
            os.remove(file_path)
            print_log(f"[RESET] Deleted file: {file_path.name}")
        except Exception as e:
            print_log(f"An error occurred while deleting {file_path}: {e}")

    # 4. Still clear symbol and terminal logs
    clear_symbol_log(read_config('SYMBOL'), "2M")
    clear_symbol_log(read_config('SYMBOL'), "15M")
    clear_terminal_log()

def read_last_n_lines(file_path, n):
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
