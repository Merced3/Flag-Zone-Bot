#test_end_of_day_calculation.py
from print_discord_messages import bot, print_discord
from main import calculate_day_performance, reseting_values, get_correct_message_ids
from buy_option import message_ids_dict
import asyncio
import cred
import json
import os

start_of_day_account_balance = 65249.0
end_of_day_account_balance = 63803.0

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)


async def main():

    # Ensure bot is ready
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")

    message_ids_dict = get_correct_message_ids()

    # TODO: USE THIS if you just want end of day message 
    output_message = await calculate_day_performance(message_ids_dict, start_of_day_account_balance, end_of_day_account_balance)
    await print_discord(output_message)
    
    # TODO: This isn't needed but incase files weren't ever sent to discord nor resetted.
    await reseting_values(start_of_day_account_balance, end_of_day_account_balance)

if __name__ == "__main__":
    print("Starting End of Day Calculation...")
    #EODC means End Of Day Calculation
    loop = asyncio.get_event_loop()
    loop.create_task(bot_start())
    loop.create_task(main())
    loop.run_forever()