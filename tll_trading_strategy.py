# tll_trading_strategy.py, meaning 'Temporal Lattice Leap Trading Strategy'
import os
import json
import asyncio
from datetime import datetime, timedelta, time
from submit_order import find_what_to_buy, submit_option_order, submit_option_order_v2, get_order_status, get_expiration, calculate_quantity
from order_handler import get_profit_loss_orders_list, get_unique_order_id_and_is_active, manage_active_order, sell_rest_of_active_order, manage_active_fake_order
from print_discord_messages import print_discord
from error_handler import error_log_and_discord_message
from data_acquisition import get_account_balance, add_markers
import pytz
import cred
import aiohttp

STRATEGY_NAME = "TEMPORAL LATTICE LEAP"

STRATEGY_DESCRIPTION = """ """

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config

config = read_config()
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
NUM_OUT_MONEY = config["NUM_OUT_OF_MONEY"]
SYMBOL = config["SYMBOL"]
TIMEFRAMES = config["TIMEFRAMES"]

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f'{SYMBOL}_{TIMEFRAMES[0]}.log')  # Adjust the path accordingly

active_order = {
    'order_id': None,
    'order_retrieval': None,
    'entry_price': None,
    'quantity': None,
    'partial_exits': []
}

last_processed_candle = None 



MESSAGE_IDS_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'message_ids.json')
message_ids_dict = {}
def load_message_ids():
    if os.path.exists(MESSAGE_IDS_FILE_PATH):
        with open(MESSAGE_IDS_FILE_PATH, 'r') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    else:
        return {}

def read_last_n_lines(file_path, n): #code from a previous ema tradegy, thought it may help. pls edit if need be.
    # Ensure the logs directory exists
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)

    # Check if the file exists, if not, create an empty file
    if not os.path.isfile(file_path):
        with open(file_path, 'w') as file:
            pass

    with open(file_path, 'r') as file:
        lines = file.readlines()
        last_n_lines = lines[-n:]
        return [json.loads(line.strip()) for line in last_n_lines]
    
new_york_tz = pytz.timezone('America/New_York')

MARKET_CLOSE = time(16, 0)

used_buying_power = {}

ACCOUNT_BALANCE = config["ACCOUNT_BALANCES"]

def get_papertrade_BP():
    #get every orders cost that is in USED_BUYING_POWER, calculate how much all of it added togther costs
    all_order_costs = sum(used_buying_power.values())
    current_balance = config["ACCOUNT_BALANCES"][0]
    current_bp_left = current_balance - all_order_costs
    return current_bp_left


async def execute_trading_strategy(zones):
    print("Starting execute_trading_strategy()...")
    global last_processed_candle

    message_ids_dict = load_message_ids()
    print("message_ids_dict: ", message_ids_dict)

    async with aiohttp.ClientSession() as session:  # Initialize HTTP session
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        try:
            while True:
                # Check if current time is within one minute of market close
                current_time = datetime.now(new_york_tz).time()
                if current_time >= (datetime.combine(datetime.today(), MARKET_CLOSE) - timedelta(minutes=1)).time():
                    # If within one minute of market close, exit all positions
                    await sell_rest_of_active_order(message_ids_dict, "Market closing soon. Exiting all positions.")
                    todays_profit_loss = sum(get_profit_loss_orders_list()) #returns todays_orders_profit_loss_list
                    end_of_day_account_balance = ACCOUNT_BALANCE[0] + todays_profit_loss
                    print(f"ACCOUNT_BALANCE[0]: {ACCOUNT_BALANCE[0]}, todays_profit_loss: {todays_profit_loss}\nend_of_day_account_balance: {end_of_day_account_balance}")
                    
                    with open(config_path, 'r') as f: # Read existing config
                        config = json.load(f)
                    config["ACCOUNT_BALANCES"][1] = end_of_day_account_balance # Update the ACCOUNT_BALANCES
                    with open(config_path, 'w') as f: # Write back the updated config
                        json.dump(config, f, indent=4)  # Using indent for better readability
                    break

                current_last_candle = read_last_n_lines(LOG_FILE_PATH, 1)  # Read the latest candle
                if current_last_candle and current_last_candle != last_processed_candle:
                    last_processed_candle = current_last_candle
                    #get that candle, look at its open and close values
                    candle = last_processed_candle[0]
                    #print(f"    New candle: {candle}\n    Open: {candle['open']}\n    Close: {candle['close']}")
                    #print("Zones: ", zones)
                    #now get the zones
                    for box_name, (count, high_low_of_day, buffer) in zones.items(): #checking every zone
                        if "support" in box_name:
                            PDL = high_low_of_day #Previous Day Low
                            if candle['open'] <= buffer and candle['close'] >= buffer: #
                                print("    buy CALL") #simulate buy
                                await buy_option_cp(IS_REAL_MONEY, SYMBOL, "call", session, headers)
                            elif candle['open'] >= PDL and candle['close'] <= PDL:
                                print("    buy PUT") #simulate buy
                                await buy_option_cp(IS_REAL_MONEY, SYMBOL, "put", session, headers)
                            #else:
                                #do nothing, wait for another candle to meet thses specifications
                            
                        elif "resistance" in box_name:
                            PDH = high_low_of_day #Previous Day High
                            if candle['open'] >= buffer and candle['close'] <= buffer: #fails to break pdh, instead it dreaks buffer
                                print("    buy PUT") #simulate buy
                                await buy_option_cp(IS_REAL_MONEY, SYMBOL, "put", session, headers)
                            elif candle['open'] <= PDH and candle['close'] >= PDH: #breaks pdh
                                print("    buy CALL") #simulate buy
                                await buy_option_cp(IS_REAL_MONEY, SYMBOL, "call", session, headers)
                            #else:
                                #do nothing, wait for another candle to meet thses specifications

                else:
                    await asyncio.sleep(1)  # Wait for new candle data

        except Exception as e:
            await error_log_and_discord_message(e, "tll_trading_strategy", "execute_trading_strategy")

#right now i have real_money_activated == false
async def buy_option_cp(real_money_activated, ticker_symbol, cp, session, headers):
    # Extract previous option type from the unique_order_id
    unique_order_id, current_order_active = get_unique_order_id_and_is_active()
    prev_option_type = unique_order_id.split('-')[1] if unique_order_id else None

    # Check if there's an active order of the same type
    if current_order_active and prev_option_type == cp:
        print(f"Canceling buy Order, same order type '{cp}' is already active.")
        return
    elif current_order_active and prev_option_type != cp:
        # Sell the current active order if it's of a different type
        await sell_rest_of_active_order(message_ids_dict, "Switching option type.")

    try:
        bid = None
        side = "buy_to_open"
        order_type = "market"  # order_type = "limit" if bid else "market"
        expiration_date = get_expiration("not specified")
        strike_price, strike_ask_bid = await find_what_to_buy(ticker_symbol, cp, NUM_OUT_MONEY, expiration_date, session, headers)
        #print(f"Strike, Price: {strike_price}, {strike_ask_bid}")
        
        quantity = calculate_quantity(strike_ask_bid, 0.1)    
        #order math, making sure we have enough buying power to fulfill order
        if real_money_activated:
            buying_power = await get_account_balance(real_money_activated, bp=True)
        else:
            buying_power = get_papertrade_BP()
        commission_fee = 0.35
        buffer = 0.25 # 50 cents
        strike_bid_cost = strike_ask_bid * 100 # 0.32 is actually 32$ when dealing with option contracts
        order_cost = (strike_bid_cost + commission_fee) * quantity
        order_cost_buffer = ((strike_bid_cost+buffer) + commission_fee) * quantity
        f_order_cost = "{:,.2f}".format(order_cost) # 'f_' means formatted
        f_order_cost_buffer = "{:,.2f}".format(order_cost_buffer) # formatted
        #print(f"order_cost_buffer: {order_cost_buffer}\nbuying_power: {buying_power}")

        # If contract cost more than what buying power we
        # have left, cancel the buy and send discord message.
        if order_cost_buffer >= buying_power:
            message = f"""
**NOT ENOUGH BUYING POWER LEFT**
-----
Canceling Order for Strategy: 
**{STRATEGY_NAME}**
-----
**Buying Power:** ${buying_power}
**Order Cost Buffer:** ${f_order_cost_buffer}
Order Cost Buffer exceded BP
-----
**Strike Price:** {strike_price}
**Option Type:** {cp}
**Quantity:** {quantity} contracts
**Price:** ${strike_ask_bid}
**Total Cost:** ${f_order_cost}
"""
            await print_discord(message)
            return

        if strike_price is None:
            # If no appropriate strike price found, cancel the buy operation
            await print_discord(f"**Appropriate strike was not found**\nstrike_price = None, Canceling buy.\n(Since not enough info)")
            return

        if real_money_activated: 
            #stuff...
            order_result = await submit_option_order(real_money_activated, ticker_symbol, strike_price, cp, bid, expiration_date, quantity, side, order_type)
            if order_result:
                await add_markers("buy")
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                unique_order_ID, order_bid_entry_price, order_quantity = await get_order_status(STRATEGY_NAME, real_money_activated, order_result['order_id'], "buy", ticker_symbol, cp, strike_price, expiration_date, timestamp, message_ids_dict)

                # Whenever you decide to start managing an active order
                # send orders to active order script, to constantly read
                active_order = {# Your active order details
                    'order_id': unique_order_ID,
                    'order_retrieval': order_result['order_id'],
                    'entry_price': order_bid_entry_price,
                    'quantity': order_quantity,
                    'partial_exits': []
                }

                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_order(active_order, message_ids_dict))
                if task.done():
                    print("Task completed.")
        else:
            active_order = await submit_option_order_v2(STRATEGY_NAME, ticker_symbol, strike_price, cp, expiration_date, session, headers, message_ids_dict, buying_power)
            if active_order is not None:
                await add_markers("buy")
                order_cost = (active_order["entry_price"] * 100) * active_order["quantity"]
                used_buying_power[active_order['order_id']] = order_cost
                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_fake_order(active_order, message_ids_dict))
                if task.done():
                    print("Task completed.")
            else:
                print("Canceled Trade")

    except Exception as e:
        await error_log_and_discord_message(e, "tll_trading_strategy", "buy_option_cp")