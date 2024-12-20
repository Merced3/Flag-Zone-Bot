import asyncio
from datetime import datetime, timedelta
import pytz
from error_handler import print_log
from main import clear_log

# Simulate a mock clock for testing
mock_current_time = datetime(2024, 12, 16, 9, 15)  # Start at a specific time for testing
new_york = pytz.timezone('America/New_York')

async def main():
    global mock_current_time  # Use a global mock time for testing

    while True:
        # Simulated current time in New York
        current_time = new_york.localize(mock_current_time)
        print(f"Mock Current Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')} (New York Time)")

        # Check if today is Monday to Friday
        if current_time.weekday() in range(0, 5):  # 0=Monday, 4=Friday
            # Check if the time is 9:20 AM New York time
            target_time = new_york.localize(
                datetime.combine(current_time.date(), datetime.strptime("09:20:00", "%H:%M:%S").time())
            )

            if current_time >= target_time:
                print(f"Running initial_setup and main_loop at {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                await initial_setup()
                await main_loop()

                # Wait until tomorrow's 9:20 AM
                print("Simulating wait until the next day's 9:20 AM...")
                mock_current_time += timedelta(days=1)  # Fast-forward to the next day
                mock_current_time = mock_current_time.replace(hour=9, minute=15, second=0)  # Reset to 9:15 AM
                await asyncio.sleep(1)  # Short sleep to simulate a new loop iteration
                continue
            else:
                print("Waiting for 9:20 AM...")
        else:
            print(f"Today is {current_time.strftime('%A')}. Market is closed.")

        # Fast-forward mock time by 1 minute for testing
        mock_current_time += timedelta(minutes=1)
        #await asyncio.sleep(0.1)  # Simulate time passing quickly (0.1s = 1 minute)
        
async def initial_setup():
    print("Mock initial_setup executed.")

async def main_loop():
    print("Mock main_loop executed.")

if __name__ == "__main__":
    #main works...
    #asyncio.run(main())

    #print/clear logs work...
    #print_log("This is the first test log entry.")
    #print_log("Logging another message to ensure everything works.")
    #clear_log(None, None, "terminal_output.log")

    print("Testing Starts...")
