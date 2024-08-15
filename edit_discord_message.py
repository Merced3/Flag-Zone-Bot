"""
The purpose of this script was to edit discord order message because 
when my wifi would go out, i would still see the bid prices of my phone
and i want the end of day calculation to run smoothly without any 
complications. trying to keep the orders as real-representative as possible.
"""

from print_discord_messages import bot, print_discord, edit_discord_message, get_message_content
from pathlib import Path
import asyncio
from order_handler import calculate_profit_percentage, generate_sell_info
import cred

async def bot_start():
    print(f"Running bot_start()...")
    await bot.start(cred.DISCORD_TOKEN)

async def edit_sell_rest_of_order(unique_order_id, message_id):
    parts = unique_order_id.split('-')
    if len(parts) >= 5:
        symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
        order_log_name = f"order_log_{symbol}_{option_type}_{strike}_{_timestamp}.txt"
    
        _message_ = await get_message_content(message_id)
        trade_info = calculate_profit_percentage(_message_, unique_order_id)
        new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
        order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
        await edit_discord_message(message_id, new_user_msg_content, None, order_log_file_path) 

async def edit_sell_trim_of_order(unique_order_id, message_id, sell_quantity, total_value, current_bid_price):
    parts = unique_order_id.split('-')
    if len(parts) >= 5:
        symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
        order_log_name = f"order_log_{symbol}_{option_type}_{strike}_{_timestamp}.txt"

        _message_ = f"Sold {sell_quantity} {symbol} contracts for ${total_value:.2f}, Fill: {current_bid_price}"
        original_content = await get_message_content(message_id)
        updated_content = original_content + "\n" + _message_
        await edit_discord_message(message_id, updated_content)

async def edit_sell_message():
    print(f"Running edit_sell_message()...")
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")
    await print_discord(f"Starting Bot message editor")

    unique_order_id = "SPY-call-553.0-20240815-20240815122242162738"
    message_id = 1273693366361657486
    await edit_sell_trim_of_order(unique_order_id, message_id, 12, 552, 0.46)
    await edit_sell_trim_of_order(unique_order_id, message_id, 13, 559, 0.43)
    await edit_sell_rest_of_order(unique_order_id, message_id)
 
# find quantities, so we know how much to trim by
#sell_targets, sell_quantities = generate_sell_info(150, 0.31, 4650.0)
#print(f"{sell_targets}, {sell_quantities}")
#Terminal output: {150: [20, 50, 100, 200, 300]}, {150: [125, 12, 6, 4, 3]}

async def edit_end_of_day_calculations(message_id):
    #this is for when EODC doesn't work correctly
    print(f"Running edit_end_of_day_calculations()...")
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")
    await print_discord(f"Starting Bot message editor:")

    # actually the meat of the program
    #original_content = await get_message_content(message_id)
    #print(f"\n\n{original_content}") #which was this below:
    # All Trades:
    # $673.00, 14.46%✅
    # $1211.00, 26.04%✅

    # Total BP Used Today:
    # $9,303.00

    # Account balance:
    # Start: $93,590.00
    # End: $93,590.00

    # Profit/Loss: $0.00
    # Percent Gain/Loss: 0.00%

    updated_content = """
All Trades:
$673.00, 14.46%✅
$1211.00, 26.04%✅

Total BP Used Today:
$9,303.00

Account balance:
Start: $93,590.00
End: $95,474.00

Profit/Loss: $1,894.00
Percent Gain/Loss: 2.01%
    """
    await edit_discord_message(message_id, updated_content)
    print("\nDone!")




if __name__ == "__main__":
    print(f"Starting...")
    loop = asyncio.get_event_loop()
    tasks = [
        loop.create_task(bot_start()),
        loop.create_task(edit_end_of_day_calculations(1273733125419176079))
        #loop.create_task(edit_sell_message())
    ]

    try:
        loop.run_until_complete(asyncio.gather(*tasks))
    except KeyboardInterrupt:
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
    finally:
        loop.close()