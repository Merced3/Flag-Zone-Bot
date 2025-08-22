# paths.py
from pathlib import Path

BASE = Path(__file__).resolve().parent

# Config
CONFIG_PATH = BASE / 'config.json'

# Logs
LOGS_DIR = BASE / 'logs'
CANDLE_LOGS = {
    "2M": LOGS_DIR / 'SPY_2M.log',
    "5M": LOGS_DIR / 'SPY_5M.log',
    "15M": LOGS_DIR / 'SPY_15M.log'
}
TERMINAL_LOG = LOGS_DIR / 'terminal_output.log'

# Storage
STORAGE_DIR = BASE / 'storage'
OBJECTS_PATH = STORAGE_DIR / 'objects' / 'objects.json'
TIMELINE_PATH = STORAGE_DIR / 'objects' / 'timeline.json'
CSV_CANDLES_PATH = STORAGE_DIR / 'SPY_15_minute_candles.csv'

# EMA directory + dynamic EMA path retrieval
EMAS_DIR = STORAGE_DIR / 'emas'
EMA_STATE_PATH = EMAS_DIR / "ema_state.json"
def get_ema_path(timeframe: str):
    return EMAS_DIR / f"{timeframe}.json"

# JSONs
LINE_DATA_PATH = STORAGE_DIR / 'line_data.json'
MARKERS_PATH = STORAGE_DIR / 'markers.json'
MESSAGE_IDS_PATH = STORAGE_DIR / 'message_ids.json'
ORDER_CANDLE_TYPE_PATH = STORAGE_DIR / 'order_candle_type.json'
PRIORITY_CANDLES_PATH = STORAGE_DIR / 'priority_candles.json'
WEEK_ECOM_CALENDER_PATH = STORAGE_DIR / 'week_ecom_calendar.json'

# CSVs
ORDER_LOG_PATH = STORAGE_DIR / 'order_log.csv'
SPY_15_MINUTE_CANDLES_PATH = STORAGE_DIR / 'SPY_15_minute_candles.csv'
AFTERMARKET_EMA_PATH = STORAGE_DIR / f"SPY_2_minute_AFTERMARKET.csv"
PREMARKET_EMA_PATH = STORAGE_DIR / f"SPY_2_minute_PREMARKET.csv"
MERGED_EMA_PATH = STORAGE_DIR / f"SPY_MERGED.csv"

def get_merged_ema_csv_path(timeframe: str):
    return STORAGE_DIR / f"merged_ema_{timeframe}.csv"

# STATES
STATES_DIR = BASE / 'states'

# PHOTOS
SPY_2M_CHART_PATH = STORAGE_DIR / 'SPY_2M_chart.png'
SPY_5M_CHART_PATH = STORAGE_DIR / 'SPY_5M_chart.png'
SPY_15M_CHART_PATH = STORAGE_DIR / 'SPY_15M_chart.png'
SPY_15M_ZONE_CHART_PATH = STORAGE_DIR / 'SPY_15M-zone_chart.png'


def pretty_path(path: Path, short: bool = True):
    from paths import BASE
    try:
        return path.relative_to(BASE) if not short else path.name
    except ValueError:
        return path.name