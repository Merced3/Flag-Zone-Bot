from main import get_dates, main
from data_acquisition import get_candle_data, ws_connect
from chart_visualization import plot_candles_and_boxes
from tll_trading_strategy import buy_option_cp, message_ids_dict
from print_discord_messages import bot, print_discord, get_message_content
import cred
import asyncio
import aiohttp
import os
import pandas as pd
import json
from pathlib import Path

config_path = Path(__file__).resolve().parent / 'config.json'
def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config

config = read_config()
SYMBOL = config["SYMBOL"]
DAYS = config["PAST_DAYS"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]

#start_date, end_date = get_dates(DAYS)
#print(f"Start and End days: \n{start_date}, {end_date}\n")

async def bot_start():
    await bot.start(cred.DISCORD_TOKEN)


async def simulation():
    await bot.wait_until_ready()
    print(f"We have logged in as {bot.user}")

    headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}

    await print_discord(f"Starting Bot, Real Money Activated" if IS_REAL_MONEY else f"Starting Bot, Real-Paper-Trading Activated")
    print()

    #this function/section works; Good Job
    #await testing_get_balances_and_calculate_end_of_day_results(real_money_activated)
    #await asyncio.sleep(420000)
    # Initialize session with aiohttp
    async with aiohttp.ClientSession() as session:
        for _ in range(11):
            await buy_option_cp(IS_REAL_MONEY, SYMBOL, "call", session, headers)
            await asyncio.sleep(5)
            await buy_option_cp(IS_REAL_MONEY, SYMBOL, "put", session, headers)
            await asyncio.sleep(5)



if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    
    # Start the bot and the main coroutine
    loop.create_task(bot_start())
    loop.create_task(simulation())

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("Manually interrupted, cleaning up...")
    finally:
        pending = asyncio.all_tasks(loop=loop)
        for task in pending:
            task.cancel()
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
        loop.close()