from error_handler import error_log_and_discord_message, print_log
from order_handler import get_unique_order_id_and_is_active, manage_active_order, sell_rest_of_active_order, manage_active_fake_order
from submit_order import find_what_to_buy, submit_option_order, submit_option_order_v2, get_order_status, get_expiration, calculate_quantity
from data_acquisition import get_account_balance, add_markers, read_config
from print_discord_messages import print_discord
from datetime import datetime
import os
import json
import asyncio

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

config = read_config()
#IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
#NUM_OUT_MONEY = config["NUM_OUT_OF_MONEY"]
#SYMBOL = config["SYMBOL"]
#TIMEFRAMES = config["TIMEFRAMES"]
#ACCOUNT_BALANCE = config["ACCOUNT_BALANCES"]
#MIN_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MIN_NUM_CANDLES"]
#MAX_NUM_CANDLES = config["FLAGPOLE_CRITERIA"]["MAX_NUM_CANDLES"]
#OPTION_EXPIRATION_DTE = config["OPTION_EXPIRATION_DTE"]
#ACCOUNT_ORDER_PERCENTAGE = config["ACCOUNT_ORDER_PERCENTAGE"]

message_ids_dict = {}
used_buying_power = {}

def get_papertrade_BP():
    #get every orders cost that is in USED_BUYING_POWER, calculate how much all of it added togther costs
    all_order_costs = sum(used_buying_power.values())
    current_balance = config["ACCOUNT_BALANCES"][0]
    current_bp_left = current_balance - all_order_costs
    return current_bp_left

async def buy_option_cp(real_money_activated, ticker_symbol, cp, session, headers, strategy_name):
    # Extract previous option type from the unique_order_id
    unique_order_id, current_order_active = get_unique_order_id_and_is_active()
    prev_option_type = unique_order_id.split('-')[1] if unique_order_id else None

    # Check if there's an active order of the same type
    if current_order_active and prev_option_type == cp:
        print_log(f"Canceling buy Order, same order type '{cp}' is already active.")
        return False, None, None, None, None
    elif current_order_active and prev_option_type != cp:
        # Sell the current active order if it's of a different type
        await sell_rest_of_active_order(message_ids_dict, "Switching option type.")

    try:
        bid = None
        side = "buy_to_open"
        order_type = "market"  # order_type = "limit" if bid else "market"
        expiration_date = get_expiration(read_config("OPTION_EXPIRATION_DTE"))
        strike_price, strike_ask_bid = await find_what_to_buy(ticker_symbol, cp, read_config("NUM_OUT_OF_MONEY"), expiration_date, session, headers)
        #print(f"Strike, Price: {strike_price}, {strike_ask_bid}")
        
        quantity = calculate_quantity(strike_ask_bid, read_config("ACCOUNT_ORDER_PERCENTAGE"))    
        #order math, making sure we have enough buying power to fulfill order
        if real_money_activated:
            buying_power = await get_account_balance(real_money_activated, bp=True)
        else:
            buying_power = get_papertrade_BP()
        commission_fee = 0.35
        buffer = 0.25
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
**{strategy_name}**
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
            return False, None, None, None, None

        if strike_price is None:
            # If no appropriate strike price found, cancel the buy operation
            await print_discord(f"**Appropriate strike was not found**\nstrike_price = None, Canceling buy.\n(Since not enough info)")
            return False, None, None, None, None

        if real_money_activated: 
            order_result = await submit_option_order(real_money_activated, ticker_symbol, strike_price, cp, bid, expiration_date, quantity, side, order_type)
            if order_result:
                await add_markers("buy", None, None, 0)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                unique_order_ID, order_bid_entry_price, order_quantity = await get_order_status(strategy_name, real_money_activated, order_result['order_id'], "buy", ticker_symbol, cp, strike_price, expiration_date, timestamp, message_ids_dict)

                # Whenever you decide to start managing an active order
                # send orders to active order script, to constantly read
                active_order = {# Your active order details
                    'order_id': unique_order_ID,
                    'order_retrieval': order_result['order_id'],
                    'entry_price': order_bid_entry_price,
                    'quantity': order_quantity,
                    'partial_exits': []
                }
                order_cost = (active_order["entry_price"] * 100) * active_order["quantity"]
                # TODO: add 'ticker_symbol,strike_price,cp,active_order["quantity"],active_order["entry_price"],order_cost' into 'ticker_symbol,strike_price,option_type, order_quantity,order_bid_price,total_investment' order_log.csv
                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_order(active_order, message_ids_dict))
                if task.done():
                    print_log("Task completed.")
                return True, strike_price, quantity, active_order["entry_price"], order_cost
        else:
            active_order = await submit_option_order_v2(strategy_name, ticker_symbol, strike_price, cp, expiration_date, session, headers, message_ids_dict, buying_power)
            if active_order is not None:
                await add_markers("buy", None, None, 0)
                order_cost = (active_order["entry_price"] * 100) * active_order["quantity"]
                # TODO: add 'ticker_symbol,strike_price,cp,active_order["quantity"],active_order["entry_price"],order_cost' into 'ticker_symbol,strike_price,option_type, order_quantity,order_bid_price,total_investment' order_log.csv
                used_buying_power[active_order['order_id']] = order_cost
                loop = asyncio.get_event_loop()
                task = loop.create_task(manage_active_fake_order(active_order, message_ids_dict))
                if task.done():
                    print_log("Task completed.")
                return True, strike_price, quantity, active_order["entry_price"], order_cost
            else:
                print_log("Canceled Trade")
        #return True

    except Exception as e:
        await error_log_and_discord_message(e, "tll_trading_strategy", "buy_option_cp")


