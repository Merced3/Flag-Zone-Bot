#test_end_of_day_calculation.py
from print_discord_messages import bot, print_discord
from main import calculate_day_performance
from buy_option import message_ids_dict
import asyncio
import cred
import json
import os

start_of_day_account_balance = 94194.0
end_of_day_account_balance = 93094.0

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)

def get_correct_message_ids(_message_ids_dict):
    # Load `message_ids.json` from the file
    json_file_path = 'message_ids.json'
    if os.path.exists(json_file_path):
        with open(json_file_path, 'r') as file:
            json_message_ids_dict = json.load(file)
            #print (f"{json_message_ids_dict}")
    else:
        json_message_ids_dict = {}

    # Check if `message_ids_dict` is empty or if `json_message_ids_dict` has more information
    if not _message_ids_dict or len(json_message_ids_dict) >= len(_message_ids_dict):
        _message_ids_dict = json_message_ids_dict
    
    return _message_ids_dict


async def main():
    global message_ids_dict

    # Ensure bot is ready
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")

    message_ids_dict = get_correct_message_ids(message_ids_dict)

    output_message = await calculate_day_performance(message_ids_dict, start_of_day_account_balance, end_of_day_account_balance)
    await print_discord(output_message)

if __name__ == "__main__":
    print("Starting EODC...")
    #EODC means End Of Day Calculation
    loop = asyncio.get_event_loop()
    loop.create_task(bot_start())
    loop.create_task(main())
    loop.run_forever()