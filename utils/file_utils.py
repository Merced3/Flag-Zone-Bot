# utils/file_utils.py, General file system utilities
from paths import LOGS_DIR

def get_current_candle_index(timeframe: str) -> int:
    """
    Returns the index of the most recent candle in the log file for the given timeframe.
    Timeframe should be one of: '2M', '5M', '15M', etc.
    """
    log_file_path = LOGS_DIR / f'SPY_{timeframe}.log'

    try:
        with open(log_file_path, 'r') as file:
            lines = file.readlines()
        return len(lines) - 1 if lines else 0
    except FileNotFoundError:
        return 0




