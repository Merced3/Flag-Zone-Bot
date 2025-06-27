# tools/backfill_15m_candles.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
from shared_state import print_log
from utils.json_utils import read_config
import cred
import asyncio
from data_acquisition import get_candle_data
from utils.data_utils import get_dates
import pandas as pd

"""
backfill_15m_candles.py

This script retrieves and appends historical 15-minute candlestick data for the symbol defined in config.json.

⏳ What It Does:
- Fetches data in 30-day batches (by default) using the Polygon API.
- Continues backward in time until no new data is returned or API limits are hit.
- Appends the data to `storage/SPY_15_minute_candles.csv`, avoiding duplicates.
- Ensures the CSV is clean and consistently formatted with the column order:
  ['timestamp', 'open', 'close', 'high', 'low'] and timestamps like 'YYYY-MM-DD HH:MM:SS'.

📅 When to Use:
Use this when you want to:
- Populate older 15M candle history.
- Refresh your dataset after accidentally wiping data.
- Expand your backtestable historical range.

⚠️ Notes:
- You *do not* need to run this during live trading or after each day.
- Only run this once or occasionally when you need more data.
- Check `CSV_PATH` inside the script to confirm the target file.

📦 Output File:
→ storage/SPY_15_minute_candles.csv
"""

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
CSV_PATH = STORAGE_DIR / "SPY_15_minute_candles.csv"

async def get_save_15m_candle_data(number_of_days=30, specific_date=None):
    start_date, end_date = get_dates(number_of_days) if specific_date is None else get_dates(number_of_days, None, specific_date)
    print_log(f"\n15m) Start and End days: {start_date}, {end_date}")
    candle_15m_data = await get_candle_data(cred.POLYGON_API_KEY, read_config('SYMBOL'), 15, "minute", start_date, end_date)
    save_to_csv(candle_15m_data)
    
    if not candle_15m_data.empty: # Find the *oldest* date in the new data, use as next start
        min_timestamp = candle_15m_data['timestamp'].min() # Parse min date in timestamp column for next iteration
        if isinstance(min_timestamp, str): # If timestamp is in format 'YYYY-MM-DD HH:MM:SS', get date part only
            bookmark_date = min_timestamp[:10]
        else:  # in case it's a pd.Timestamp
            bookmark_date = min_timestamp.strftime('%Y-%m-%d')
        return bookmark_date
    return start_date

def save_to_csv(data):
    
    def ensure_str_timestamp(df):
        if pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            df['timestamp'] = df['timestamp'].astype(str)
        return df
    
    columns_to_keep = ['timestamp', 'open', 'close', 'high', 'low']
    
    try:
        if CSV_PATH.exists() and CSV_PATH.stat().st_size > 0:
            existing = pd.read_csv(CSV_PATH)
            existing = ensure_str_timestamp(existing)
            existing = existing[columns_to_keep]
        else:
            existing = pd.DataFrame(columns=columns_to_keep)
    except Exception as e:
        print_log(f"[DEBUG] Could not read existing file (might be empty/corrupt): {e}")
        existing = pd.DataFrame(columns=columns_to_keep)

    data = ensure_str_timestamp(data)
    data = data[columns_to_keep]

    combined = pd.concat([existing, data], ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset=['timestamp'])
    after = len(combined)

    # Optional: sort by timestamp for safety
    combined['timestamp'] = pd.to_datetime(combined['timestamp'])
    combined = combined.sort_values('timestamp')
    combined['timestamp'] = combined['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')

    combined = combined[columns_to_keep]  # Reorder just in case
    combined.to_csv(CSV_PATH, index=False)
    print_log(f"Removed {before - after} duplicate rows.")
    print_log(f"Final num rows: {len(combined)}")

async def main():
    start_date = None
    CHUNK_SIZE = 30

    while True:
        old_start = start_date
        start_date = await get_save_15m_candle_data(CHUNK_SIZE, start_date)
        print_log(f"Backfilled batch ending at {start_date}")

        if start_date == old_start or start_date is None:
            print_log("No more new data or hit API/data limit. Stopping backfill.")
            break
        await asyncio.sleep(0.5)

    # --- DATA RANGE CHECK ---
    df = pd.read_csv(CSV_PATH)
    # Make sure timestamp is a string (or convert to datetime if needed)
    if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
        df['timestamp'] = pd.to_datetime(df['timestamp'])

    first_ts = df['timestamp'].min()
    last_ts = df['timestamp'].max()
    delta = last_ts - first_ts
    # Also show how many years, months, days
    days = delta.days
    years = days // 365
    rem_days = days % 365
    months = rem_days // 30
    final_days = rem_days % 30

    print_log("\n--- Historical Data Coverage ---")
    print_log(f"Oldest 15m candle: {first_ts.strftime('%Y-%m-%d %H:%M:%S')}")
    print_log(f"Newest 15m candle: {last_ts.strftime('%Y-%m-%d %H:%M:%S')}")
    print_log(f"Total days: {days} ({years} years, {months} months, {final_days} days)")
    print_log(f"Total rows: {len(df)}")
    print_log("--- End Coverage ---\n")

if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())