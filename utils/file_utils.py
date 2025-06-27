# utils/file_utils.py, General file system utilities
from paths import LOGS_DIR

def get_current_candle_index(type="2min"):
    log_file_path = None
    if type == "2min":
        log_file_path = LOGS_DIR / 'SPY_2M.log'
    elif type == "5min":
        log_file_path = LOGS_DIR / 'SPY_5M.log'
    elif type == "15min":
        log_file_path = LOGS_DIR / 'SPY_15M.log'
    else:
        raise ValueError("Unsupported candle type. Use '2min', '5min', or '15min'.")
    with open(log_file_path, 'r') as file:
        lines = file.readlines()
    if not lines:
        return None  # Return None if the log file is empty
    # The index of the last candle is the length of the lines list minus 1
    return len(lines) - 1



