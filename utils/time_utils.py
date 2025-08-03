# utils/time_utils.py, Candlestick time calc, add_seconds_to_time, etc.
import pytz
from datetime import datetime, timedelta
import time

def generate_candlestick_times(start_time, end_time, interval, exclude_first=False):
    new_york_tz = pytz.timezone('America/New_York')
    start = new_york_tz.localize(datetime.combine(datetime.today(), start_time.time()))
    end = new_york_tz.localize(datetime.combine(datetime.today(), end_time.time()))
    
    times = []
    while start <= end:
        times.append(start)
        start += interval
        
    if exclude_first and times:
        return times[1:]  # Skip the first timestamp (09:30:00)
    return times

def add_seconds_to_time(time_str, seconds):
    time_obj = datetime.strptime(time_str, '%H:%M:%S')
    new_time_obj = time_obj + timedelta(seconds=seconds)
    return new_time_obj.strftime('%H:%M:%S')

def to_unix_timestamp(year, month, day, hour, minute, second=0):
    dt = datetime(year, month, day, hour, minute, second)
    return int(time.mktime(dt.timetuple()) * 1000)  # Convert to milliseconds

def convert_unix_timestamp_to_time(unix_timestamp, timezone_offset=-5):
    time = datetime.utcfromtimestamp(unix_timestamp / 1000) + timedelta(hours=timezone_offset)
    return time.strftime('%m/%d %H:%M:%S')

