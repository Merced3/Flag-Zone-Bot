#error_handler.py
import os
import traceback
from pathlib import Path
from datetime import datetime

# Define the logs directory and file path
LOGS_DIR = Path(__file__).resolve().parent / 'logs'
LOG_FILE_PATH = LOGS_DIR / 'terminal_output.log'

async def error_log_and_discord_message(e, script_name, func_name, custom_message=None):
    error_type = type(e).__name__
    error_message = str(e)
    error_traceback = traceback.format_exc()
    current_time = datetime.now().isoformat()

    from print_discord_messages import print_discord 

    if "()" in func_name:
        func_name = func_name.replace("()", "")
    if ".py" in script_name:
        script_name = script_name.replace(".py", "")
    

    detailed_error_info = custom_message if custom_message else f"An error occurred in {script_name}.py"

    # Summarized error message for Discord
    discord_error_message = (
        f"⚠️ A critical error has occurred in `{script_name}.py`:\n"
        f"Time: {current_time}\n"
        f"Location: {func_name}()\n"
        f"Error Type: {error_type}\n"
        f"Message: {error_message}\n"
        f"Please check the logs for more details."
    )

    location = f"{script_name}.py, {func_name}()" if custom_message else f"{func_name}()"

    # Detailed error message for the console/logs
    detailed_error_message = (
        f"\n{detailed_error_info}:\n"
        f"Time: {current_time}\n"
        f"Location: {location}\n"
        f"Type: {error_type}\n"
        f"Message: {error_message}\n"
        f"Traceback:\n{error_traceback}"
    )

    await print_discord(discord_error_message)
    print_log(detailed_error_message)

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