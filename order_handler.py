#order_handler.py
import cred
import aiohttp
import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
from print_discord_messages import bot, print_discord, edit_discord_message, get_message_content
from submit_order import submit_option_order, get_order_status
from error_handler import error_log_and_discord_message, print_log
from data_acquisition import add_markers, is_ema_broke, get_current_candle_index, get_latest_ema_values, update_order_details, read_config
import time
import re

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

config = read_config()

#SYMBOL = config["SYMBOL"]
#TIMEFRAMES = config["TIMEFRAMES"]
#IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
#STOP_LOSS_PERCENTAGE = config["STOP_LOSS_PERCENTAGE"]
#TAKE_PROFIT_PERCENTAGES = config["TAKE_PROFIT_PERCENTAGES"]
RETRY_COUNT = 3
RETRY_DELAY = 3  # seconds

global buy_entry_price
global message_ids_dict
global unique_order_id
global order_quantity
global current_order_active
unique_order_id = None
current_order_active = False
global partial_exits
todays_orders_profit_loss_list = [] #added the variable here instead of tll_trading_strategy.py

LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def calculate_bid_percentage(buy_entry_price, sold_bid_price):
    """
    Calculate the percentage change between the buy entry price and the sold bid price.

    Args:
    - buy_entry_price (float): The price at which the asset was bought.
    - sold_bid_price (float): The price at which the asset was sold or trimmed.

    Returns:
    - float: The percentage change.
    """
    try:
        percentage_change = ((sold_bid_price - buy_entry_price) / buy_entry_price) * 100
        return round(percentage_change, 2)  # Rounding to 2 decimal places
    except ZeroDivisionError:
        return 0.0

def distribute_remaining_contracts(remaining, n_targets):
    proportions = {
        1: [1.0],  # If only 1 target, put everything on it
        2: [0.7, 0.3],  # 70% on the first target, 30% on the second
        3: [0.6, 0.3, 0.1],  # Distribution across three targets
        4: [0.5, 0.25, 0.15, 0.1]  # Distribution across four targets
    }
    if n_targets > len(proportions):
        n_targets = len(proportions) # Limit num of proportions

    distribution = []
    allocated = 0

    for proportion in proportions.get(n_targets, []):
        contracts_for_target = int(remaining * proportion + 0.5)  # Round up if .5 or more
        allocated += contracts_for_target
        distribution.append(contracts_for_target)

    # Handle any discrepancies due to rounding
    while allocated < remaining:
        for i in range(len(distribution)):
            distribution[i] += 1
            allocated += 1
            if allocated == remaining:
                break

    while allocated > remaining:  # In case of over-allocation
        for i in range(len(distribution)):
            if distribution[i] > 0:
                distribution[i] -= 1
                allocated -= 1
                if allocated == remaining:
                    break

    return distribution

def calculate_sell_points(buy_entry_price, percentages):
    return [buy_entry_price * (1 + p / 100) for p in percentages]

def generate_sell_info(order_quantity, buy_entry_price, total_cost):
    sell_targets = {}
    sell_quantities = {}

    # Helper function to calculate the total cost at a given profit target for a specific number of contracts
    def calculate_cost_at_target(n_contracts, target_percentage):
        profit_per_contract = buy_entry_price * (1 + target_percentage / 100)
        return n_contracts * profit_per_contract * 100

    for i in range(1, order_quantity + 1):
        cost_at_first_target = calculate_cost_at_target(i, read_config("TAKE_PROFIT_PERCENTAGES")[0])
        if cost_at_first_target >= total_cost:
            sell_targets[order_quantity] = [read_config("TAKE_PROFIT_PERCENTAGES")[0]]
            sell_quantities[order_quantity] = [i]

            #calculate remaining contracts
            remaining_contracts = order_quantity - i
            if remaining_contracts >= 1:
                distribution = distribute_remaining_contracts(remaining_contracts, len(read_config("TAKE_PROFIT_PERCENTAGES")) - 1)
                sell_targets[order_quantity] = read_config("TAKE_PROFIT_PERCENTAGES")[:1 + len(distribution)]
                sell_quantities[order_quantity] = [i] + distribution
            
            # Cleanup zeros from sell_quantities and adjust sell_targets accordingly
            # For example: converting this {6: [5, 1, 0, 0]} to this {6: [5, 1]}
            for qty, quantities in sell_quantities.items():
                valid_indexes = [i for i, q in enumerate(quantities) if q > 0]
                sell_quantities[qty] = [quantities[i] for i in valid_indexes]
                sell_targets[qty] = [read_config("TAKE_PROFIT_PERCENTAGES")[i] for i in valid_indexes]

            return sell_targets, sell_quantities

def get_unique_order_id_and_is_active():
    #print(f"\nget_unique_order_id_and_is_active():\nunique_order_id: {unique_order_id}\ncurrent_order_active: {current_order_active}\n")
    return unique_order_id, current_order_active

def get_profit_loss_orders_list():
    return todays_orders_profit_loss_list

async def get_option_bid_price(symbol, strike, expiration_date, option_type, session):
    #only realtime data
    quote_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}markets/options/chains?symbol={symbol}&expiration={expiration_date}"
    headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
    
    while True:
        try:
            async with session.get(quote_url, headers=headers) as response:
                if response.status != 200:
                    print_log(f"    [get_option_bid_price] Received unexpected status code {response.status}: {await response.text()}")
                    await asyncio.sleep(1)  # Wait a second before retrying
                    continue
                
                try:
                    response_json = await response.json()
                    options_data = response_json.get('options', {}).get('option', [])
                    target_strike = float(strike)
                    filtered_options = [
                        option for option in options_data 
                        if option['strike'] == target_strike and option['option_type'] == option_type
                    ]
                    
                    if filtered_options:
                        return filtered_options[0]['bid']
                    else:
                        print_log("    [get_option_bid_price] Option not found, retrying...")
                        await asyncio.sleep(1)  # Wait a second before retrying

                except asyncio.TimeoutError:
                    print_log(f"[INTERNET CONNECTION]  get_option_bid_price() Timeout Error, retrying...")
                    await asyncio.sleep(1)  # Wait a second before retrying
                except Exception as e:
                    await error_log_and_discord_message(e, "order_handler", "get_option_bid_price", "Error parsing JSON")
                    await asyncio.sleep(1)  # Wait a second before retrying

        except aiohttp.ClientOSError as e:
            print_log(f"[INTERNET CONNECTION] Client OS Error: {e}. Retrying...")
            await asyncio.sleep(1)  # Wait a second before retrying
        except Exception as e:
            print_log(f"Unexpected error occurred: {e}. Retrying...")
            await asyncio.sleep(1)  # Wait a second before retrying        

def calculate_max_drawdown_and_gain(start_price, lowest_price, highest_price, write_to_file=None, order_log_name=None, unique_order_id=None):
    # Calculate maximum drawdown
    max_drawdown = ((start_price - lowest_price) / start_price) * 100
    # Calculate maximum gain
    max_gain = ((highest_price - start_price) / start_price) * 100
    
    if write_to_file is None:
        return "{:.2f}".format(max_drawdown)
    else:
        with open(order_log_name, "a") as log_file:
            log_file.write(f"Lowest Bid Price: {lowest_price}, Max-Drawdown: {max_drawdown:.2f}%\n")
            log_file.write(f"Highest Bid Price: {highest_price}, Max-Gain: {max_gain:.2f}%\n")
            log_file.flush()
            #TODO: add 'lowest_bid,max_drawdown,highest_bid,max_gain' into order_log.csv
            update_order_details('order_log.csv', unique_order_id, lowest_bid=lowest_price, max_drawdown=max_drawdown,
                         highest_bid=highest_price, max_gain=max_gain)

async def manage_active_order(active_order_details, _message_ids_dict):
    global message_ids_dict
    global buy_entry_price
    global unique_order_id # f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
    global order_quantity
    global current_order_active
    global partial_exits

    async with aiohttp.ClientSession() as session:  # Creating a new session using a context manager
        order_id = active_order_details["order_retrieval"]
        
        if read_config("REAL_MONEY_ACTIVATED"):
            order_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/orders/{order_id}"
            headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        else:
            order_url = f"{cred.TRADIER_SANDBOX_BASE_URL}accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/orders/{order_id}"
            headers = {"Authorization": f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}", "Accept": "application/json"}

        if not active_order_details.get("partial_exits"):
            active_order_details["partial_exits"] = []
        
        unique_order_id =   active_order_details["order_id"]
        message_ids_dict = _message_ids_dict
        buy_entry_price =   active_order_details["entry_price"]
        order_quantity  =   active_order_details["quantity"]
        total_cost = order_quantity * (buy_entry_price * 100)
        sell_targets, sell_quantities = generate_sell_info(order_quantity, buy_entry_price, total_cost)
        partial_exits = active_order_details["partial_exits"]
        sell_points = calculate_sell_points(buy_entry_price, sell_targets[order_quantity])

        print_once_flag = True
        current_order_active = True
        lowest_bid_price = None
        highest_bid_price = None
        buy_price_already_writen = None
        remaining_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)

        while current_order_active:  # Loop to manage an individual order
            if unique_order_id is None:  # Check if the order was cleared
                print_log("Order was cleared. Exiting management loop.")
                break

            async with session.get(order_url, headers=headers) as response:
                if response.status == 429:  # Too Many Requests, This is too not abuse Tradier Api requests
                    print_log("Rate limit exceeded, sleeping...")
                    await asyncio.sleep(60)  # Sleep for a minute
                elif response.status != 200:
                    print_log(f"    Received unexpected status code {response.status}: {await response.text()}")
                    continue
                        
                # submit_order.py, get_order_status(), 'unique_order_key' looks like this \/
                # unique_order_key = f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
                # Split 'unique_order_id' into its components
                if unique_order_id:
                    parts = unique_order_id.split('-')
                    if len(parts) >= 5:
                        symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
                        order_log_name = f"order_log({symbol}_{option_type}_{strike}_{_timestamp}).txt"

                        
                        expiration_date_obj = datetime.strptime(expiration_date, "%Y%m%d")# Convert the expiration date to 'YYYY-MM-DD' format
                        formatted_expiration_date = expiration_date_obj.strftime("%Y-%m-%d")

                        # Check if we should print the message
                        if print_once_flag:
                            print_log(f"    Starting get_option_bid_price({symbol}, {strike}, {formatted_expiration_date}, {option_type}, session, headers)\n")
                            print_once_flag = False  # Set flag to False so it doesn't print again
                                
                        #Starting get_option_bid_price(SPY, 419, 2023-11-01, put, session, headers)
                        current_bid_price = await get_option_bid_price(
                            symbol=symbol, 
                            strike=strike, 
                            expiration_date=formatted_expiration_date, 
                            option_type=option_type, 
                            session=session, 
                            headers=headers
                        )

                        if current_bid_price is not None:
                            # Update the lowest bid price
                            if lowest_bid_price is None or current_bid_price < lowest_bid_price:
                                lowest_bid_price = current_bid_price
                            # Update the highest bid price
                            if highest_bid_price is None or current_bid_price > highest_bid_price:
                                highest_bid_price = current_bid_price
                            
                            # Open the log file and write the bid price
                            with open(order_log_name, "a") as log_file:
                                if buy_price_already_writen is None:
                                    log_file.write(f"Buy Entry Price: {buy_entry_price}\n")
                                    buy_price_already_writen = True
                                log_file.write(f"{current_bid_price}\n")
                                log_file.flush()  # Ensure the data is written to the file

            # Check for stop loss condition
            if isinstance(read_config("STOP_LOSS_PERCENTAGE"), str): # if STOP_LOSS_PERCENTAGE is string
                # Handling string type STOP_LOSS_PERCENTAGE, e.g., "EMA 13"
                if "EMA" in read_config("STOP_LOSS_PERCENTAGE"):
                    ema_value = read_config("STOP_LOSS_PERCENTAGE").split(' ')[-1]
                    if is_ema_broke(ema_value, read_config("SYMBOL"), read_config("TIMEFRAMES")[0], option_type):
                        await sell_rest_of_active_order("13ema Trailing stop Hit")
                        break
            elif isinstance(read_config("STOP_LOSS_PERCENTAGE"), (int, float)): # if STOP_LOSS_PERCENTAGE is number
                if current_bid_price is not None and buy_entry_price is not None:
                    current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                    if current_loss_percentage <= read_config("STOP_LOSS_PERCENTAGE"):
                        print_log(f"\nStop loss triggered at {current_loss_percentage}% loss.")
                        await sell_rest_of_active_order("Stop Loss Triggered")
                        break
            elif isinstance(read_config("STOP_LOSS_PERCENTAGE"), list) and len(read_config("STOP_LOSS_PERCENTAGE")) == 2:  # if STOP_LOSS_PERCENTAGE is a list containing an EMA and a percentage
                    ema_string, loss_percentage = read_config("STOP_LOSS_PERCENTAGE")
                    if isinstance(ema_string, str) and "EMA" in ema_string and isinstance(loss_percentage, (int, float)):
                        ema_value = ema_string.split(' ')[-1]
                        if is_ema_broke(ema_value, read_config("SYMBOL"), read_config("TIMEFRAMES")[0], option_type):
                            if current_bid_price is not None and buy_entry_price is not None:
                                current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                                if current_loss_percentage <= loss_percentage:
                                    await sell_rest_of_active_order("13ema Trailing stop Hit and is more than desired percentage")
                                    break

            #this handles the sell targets
            for i, sell_point in enumerate(sell_points):
                # Check if this target has already been hit and part of the order sold
                already_sold = any(sale['target'] == sell_point for sale in partial_exits)
                if current_bid_price >= sell_point and not already_sold:
                    sell_quantity = min(sell_quantities[order_quantity][i], remaining_quantity)

                    # Unpack the returned values from the sell function
                    sold_bid_price, sold_quantity, success = await sell(
                        sell_quantity, unique_order_id, message_ids_dict, f"Hit Sell Target Of {sell_point}"
                    )

                    if success and sold_quantity is not None and sold_bid_price is not None:
                        sale_info = {
                            "target": sell_point,
                            "sold_price": sold_bid_price,  # Using actual sold bid price
                            "quantity": sold_quantity,  # Using actual sold quantity
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        partial_exits.append(sale_info)
                        remaining_quantity -= sold_quantity
                        print_log(f"Sold {sold_quantity} at {sold_bid_price} target, {remaining_quantity} remaining.")

                        # Calculate Percentage for more data tracking...
                        bid_percentage = calculate_bid_percentage(buy_entry_price, sold_bid_price)
                        if remaining_quantity <= 0:
                            await add_markers("sell", None, None, bid_percentage)
                        else:
                            await add_markers("trim", None, None, bid_percentage)
                        
                        #have 'already_sold' some how afftected right here, i think that will help with selling issue
                        
                        with open(order_log_name, "a") as log_file:
                            log_file.write(f"Sold {sold_quantity} at {sold_bid_price}\n")
                            log_file.flush()
                        if remaining_quantity <= 0:
                            calculate_max_drawdown_and_gain(buy_entry_price, lowest_bid_price, highest_bid_price, True, order_log_name, unique_order_id)
                            #print end of message calculations
                            _message_ = await get_message_content(message_ids_dict[unique_order_id])  
                            if _message_ is not None:
                                trade_info = calculate_profit_percentage(_message_, unique_order_id)
                                new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                                await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content)
                                current_order_active = False
                                unique_order_id = None
                            else:
                                await print_discord("Could not fetch message content.")
                            break
                    else:
                        print_log("Sell order failed. Retrying...")
            if remaining_quantity <= 0:
                unique_order_id = None
                break
            # Wait before checking again
            await asyncio.sleep(.5)

def safe_write_to_file(path, data, max_retries=3, retry_delay=0.25):
    for attempt in range(max_retries):
        try:
            with open(path, "a") as log_file:
                log_file.write(data)
                log_file.flush()
            return True  # Successfully written
        except PermissionError as e:
            print_log(f"Permission denied on attempt {attempt+1}: {e}")
            time.sleep(retry_delay)
    return False  # Failed to write after retries

async def manage_active_fake_order(active_order_details, _message_ids_dict):
    global message_ids_dict
    global buy_entry_price
    global unique_order_id
    global order_quantity
    global current_order_active
    global partial_exits

    if active_order_details is None:
        return

    # Initialize variables from active_order_details
    unique_order_id = active_order_details["order_id"]
    message_ids_dict = _message_ids_dict
    buy_entry_price = active_order_details["entry_price"]
    order_quantity = active_order_details["quantity"]
    total_cost = order_quantity * (buy_entry_price * 100)
    sell_targets, sell_quantities = generate_sell_info(order_quantity, buy_entry_price, total_cost)
    partial_exits = active_order_details.get("partial_exits", [])
    sell_points = calculate_sell_points(buy_entry_price, sell_targets[order_quantity])
    
    print_once_flag = True
    current_order_active = True
    lowest_bid_price = None
    highest_bid_price = None
    buy_price_already_writen = None
    remaining_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)
    last_check_candle_index = None
    last_checked_ema_index = None

    async with aiohttp.ClientSession() as session:
        retry_attempts = 0
        while current_order_active:
            # For simulation, we can use a static or randomly generated current bid price.
            # In a real scenario, this would be fetched from live market data.

            # submit_order.py, get_order_status(), 'unique_order_key' looks like this \/
            # unique_order_key = f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
            # Split 'unique_order_id' into its components
            try:
                if unique_order_id:
                    parts = unique_order_id.split('-')
                    if len(parts) >= 5:
                        symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
                        order_log_name = f"order_log_{symbol}_{option_type}_{strike}_{_timestamp}.txt"
                        expiration_date_obj = datetime.strptime(expiration_date, "%Y%m%d")# Convert the expiration date to 'YYYY-MM-DD' format
                        formatted_expiration_date = expiration_date_obj.strftime("%Y-%m-%d")
                        try:
                            with open(order_log_name, "a") as log_file:
                                if buy_price_already_writen is None:
                                    log_file.write(f"Buy Entry Price: {buy_entry_price}\n")
                                    buy_price_already_writen = True
                        except Exception as e:
                            await error_log_and_discord_message(e, "order_handler", "manage_active_fake_order", f"Error writing to file {order_log_name}")

                        # Check if we should print the message
                        if print_once_flag:
                            #print(f"    Starting get_option_bid_price({symbol}, {strike}, {formatted_expiration_date}, {option_type}, session)\n")
                            current_order_cost = order_quantity * (buy_entry_price * 100)
                            print_log(f"\nBought {order_quantity} at {buy_entry_price} resulting in a cost of ${current_order_cost:.2f}")
                            print_once_flag = False  # Set flag to False so it doesn't print again
                                        
                        current_bid_price = await get_option_bid_price(
                            symbol=symbol, 
                            strike=strike, 
                            expiration_date=formatted_expiration_date, 
                            option_type=option_type, 
                            session=session
                        )

                        if current_bid_price is not None:
                            # Update the lowest bid price
                            if lowest_bid_price is None or current_bid_price < lowest_bid_price:
                                lowest_bid_price = current_bid_price
                            # Update the highest bid price
                            if highest_bid_price is None or current_bid_price > highest_bid_price:
                                highest_bid_price = current_bid_price
                            
                            # Open the log file and write the bid price
                            if not safe_write_to_file(order_log_name, f"{current_bid_price}\n"):
                                print_log(f"Failed to write to {order_log_name} after retries.")
                            #with open(order_log_name, "a") as log_file: #ERROR HAPPEND HERE ------------------------------------------
                                #log_file.write(f"{current_bid_price}\n")
                                #log_file.flush()  # Ensure the data is written to the file

                # Check for stop loss condition
                if isinstance(read_config("STOP_LOSS_PERCENTAGE"), str): # if STOP_LOSS_PERCENTAGE is string
                    # Handling string type STOP_LOSS_PERCENTAGE, e.g., "EMA 13"
                    if "EMA" in read_config("STOP_LOSS_PERCENTAGE"):
                        ema_value = read_config("STOP_LOSS_PERCENTAGE").split(' ')[-1]
                        if is_ema_broke(ema_value, read_config("SYMBOL"), read_config("TIMEFRAMES")[0], option_type):
                            await sell_rest_of_active_order("13ema Trailing stop Hit")
                            break
                elif isinstance(read_config("STOP_LOSS_PERCENTAGE"), (int, float)): # if STOP_LOSS_PERCENTAGE is number
                    if current_bid_price is not None and buy_entry_price is not None:
                        current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                        if current_loss_percentage <= read_config("STOP_LOSS_PERCENTAGE"):
                            Sell_order_cost = remaining_quantity * (current_bid_price * 100)
                            print_log(f"    [STOP LOSS] {current_loss_percentage:.2f}% loss. Sold {remaining_quantity} at {current_bid_price}, costing ${Sell_order_cost:.2f}")
                            await sell_rest_of_active_order("Stop Loss Triggered")
                            break
                elif isinstance(read_config("STOP_LOSS_PERCENTAGE"), list) and len(read_config("STOP_LOSS_PERCENTAGE")) == 2:  # if STOP_LOSS_PERCENTAGE is a list containing an EMA and a percentage
                    ema_string, loss_percentage = read_config("STOP_LOSS_PERCENTAGE")
                    if isinstance(ema_string, str) and "EMA" in ema_string and isinstance(loss_percentage, (int, float)):
                        # Get EMA value and current candle index
                        ema_value = ema_string.split(' ')[-1]
                        current_candle_index = get_current_candle_index()
                        current_latest_ema_value, current_index_ema = get_latest_ema_values(ema_value) # we don't need current_latest_ema_value unless for something else
                        
                        # Check if the current candle and ema is different since last checked
                        if (current_candle_index != last_check_candle_index 
                            and current_index_ema != last_checked_ema_index 
                            and current_candle_index == current_index_ema):

                            last_check_candle_index = current_candle_index
                            last_checked_ema_index = current_index_ema
                            broke_13_ema = is_ema_broke(ema_value, read_config("SYMBOL"), read_config("TIMEFRAMES")[0], option_type)
                            print_log(f"    [MAFO] Current EMA index: {last_checked_ema_index}")
                            print_log(f"    [MAFO] Current Candle Index: {last_check_candle_index}")
                            print_log(f"    [MAFO] Broke 13 ema: {broke_13_ema}")
                            # Check if a partial exit has already occurred and if the 13 EMA is broken
                            if partial_exits and broke_13_ema:
                                await sell_rest_of_active_order("13ema Trailing stop Hit after partial exit")
                                break
                            
                            # If no partial exit has occurred, see if were below loss percentage then sell, sell order else stay in order.
                            if current_bid_price is not None and buy_entry_price is not None:
                                current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                                print_log(f"    [MAFO] Current Bid and Loss: {current_bid_price}, {current_loss_percentage}% | {loss_percentage}%")
                                if current_loss_percentage <= loss_percentage and broke_13_ema:
                                    await sell_rest_of_active_order("13ema Trailing stop Hit and is more than desired percentage")
                                    break
 
                #this handles the sell targets
                for i, sell_point in enumerate(sell_points):
                    # Determine if this sell target has already been hit
                    already_sold = any(sale['target'] == sell_point for sale in partial_exits)
                    
                    # Check if all previous sell points (if any) have been sold
                    # This is True if for all sell points before the current one, there exists a corresponding sale in partial_exits
                    all_previous_sold = all(any(sale['target'] == sp for sale in partial_exits) for sp in sell_points[:i])
                    
                    # Identify if the current sell point is the last one, and all previous sell points have been sold
                    is_runner = (i == len(sell_points) - 1) and all_previous_sold

                    if current_bid_price >= sell_point and not already_sold and not is_runner:
                        print_log(f"        [SELL ACTION] Selling at sell point {sell_point}. Sell quantities: {sell_quantities[order_quantity][i]}")
                        sell_quantity = min(sell_quantities[order_quantity][i], remaining_quantity)
                        sale_info = {
                            "target": sell_point,
                            "sold_price": current_bid_price,  # Using actual sold bid price
                            "quantity": sell_quantity,  # Using actual sold quantity
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        partial_exits.append(sale_info)
                        remaining_quantity -= sell_quantity
                        sold_order_cost = (current_bid_price * 100) * sell_quantity
                        print_log(f"Sold {sell_quantity} at {current_bid_price} target, {remaining_quantity} remaining. Order Cost: ${sold_order_cost:.2f}")

                        # Calculate Percentage for more data tracking...
                        bid_percentage = calculate_bid_percentage(buy_entry_price, current_bid_price)
                        if remaining_quantity <= 0:
                            await add_markers("sell", None, None, bid_percentage)
                        else:
                            await add_markers("trim", None, None, bid_percentage)

                        with open(order_log_name, "a") as log_file:
                            log_file.write(f"Sold {sell_quantity} at {current_bid_price}\n")
                            log_file.flush()

                        total_value = (current_bid_price * 100) * sell_quantity
                        _message_ = f"Sold {sell_quantity} {symbol} contracts for ${total_value:.2f}, Fill: {current_bid_price}"
                        if unique_order_id in message_ids_dict:
                            original_msg_id = message_ids_dict[unique_order_id]
                            try:
                                original_content = await get_message_content(original_msg_id)
                                if original_content:
                                    updated_content = original_content + "\n" + _message_
                                    #update discord order message
                                    await edit_discord_message(original_msg_id, updated_content)
                                else:
                                    print_log(f"Could not retrieve original message content for ID {original_msg_id}")
                            except Exception as e:  # Catch any exception to avoid stopping the loop
                                await error_log_and_discord_message(e, "order_handler", "manage_active_fake_order", "An error occurred while getting or edditing message")
                        else:
                            print_log(f"Message ID for order {unique_order_id} not found in dictionary. Dictionary contents:\n{message_ids_dict}")

                        if remaining_quantity <= 0:
                            calculate_max_drawdown_and_gain(buy_entry_price, lowest_bid_price, highest_bid_price, True, order_log_name, unique_order_id)
                            #print end of message calculations
                            _message_ = await get_message_content(message_ids_dict[unique_order_id])  
                            if _message_ is not None:
                                trade_info = calculate_profit_percentage(_message_, unique_order_id)
                                new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                                order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                                await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)
                                # Verify if the file was sent and then delete the log file
                                if os.path.exists(order_log_name):
                                    os.remove(order_log_name)
                                    print_log(f"Order log file {order_log_name} deleted.")
                            else:
                                await print_discord("Could not fetch message content.")
                            current_order_active = False
                            unique_order_id = None
                            break
                    elif is_runner:
                        #print(f"        [RUNNER DETECTED] Preparing to check runner conditions for sell point {sell_point}")
                        if is_ema_broke("13", read_config("SYMBOL"), read_config("TIMEFRAMES")[0], option_type):
                            await sell_rest_of_active_order("13ema Hit")
                            break
                        
                
                if remaining_quantity <= 0:
                    all_sells = 0
                    for sells in partial_exits:
                        sell_cost = (sells["sold_price"] * 100) * sells["quantity"]
                        all_sells = all_sells + sell_cost

                    profit_loss = all_sells - current_order_cost 
                    print_log(f"(manage_active_fake_order) Profit/Loss: ${profit_loss:.2f}")
                    todays_orders_profit_loss_list.append(profit_loss)
                    unique_order_id = None
                    break
                
                # Wait before checking again
                await asyncio.sleep(.5)
            except aiohttp.ClientOSError as e:
                print_log(f"[MAFO] Encountered an error: {e}. Retrying in {RETRY_DELAY} seconds.")
                await asyncio.sleep(RETRY_DELAY)
                # Retry loop continues indefinitely until it succeeds or the process is stopped

async def sell(quantity, unique_order_key, message_ids_dict, reason_for_selling):
    #selling logic here
    bid = None
    side = "sell_to_close"
    order_type = "market"
    print_log(f"\n    message_ids_dict[unique_order_key]: {message_ids_dict[unique_order_key]}")

    symbol, cp, strike, expiration_date, timestamp_from_order_id = unique_order_key.split('-')[:5]
    
    message_channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if message_channel is None:
        print_log(f"Failed to find Discord channel with ID {cred.DISCORD_CHANNEL_ID}")
        return None, None, None
    print_log(f"    REASON FOR SELLING: {reason_for_selling}")
    #execute sell
    order_result = await submit_option_order(
        read_config("REAL_MONEY_ACTIVATED"), symbol, strike, cp, bid, expiration_date, quantity, side, order_type
    )
    if order_result:
        unique_order_ID, order_bid_price, order_quantity = await get_order_status(
            strategy_name=None,
            real_money_activated=read_config("REAL_MONEY_ACTIVATED"),
            order_id=order_result['order_id'],
            b_s="sell",
            ticker_symbol=symbol,
            cp=cp,
            strike=strike,
            expiration_date=expiration_date,
            order_timestamp=timestamp_from_order_id,
            message_ids_dict=message_ids_dict
        )

        print_log(f"    sell() = {order_bid_price}, {order_quantity}, {True}\n")

        return order_bid_price, order_quantity, True

    if order_result == "rejected":
        return None, None, False
    
    return None, None, False

def calculate_sell_points(buy_entry_price, percentages):
    return [buy_entry_price * (1 + p / 100) for p in percentages]

def calculate_profit_percentage(message, unique_order_id):
    # Extract buy details based on the new Discord message format
    buy_pattern = r"\*\*(.+?)\*\*\n-----\n\*\*Ticker Symbol:\*\* (.+?)\n\*\*Strike Price:\*\* (.+?)\n\*\*Option Type:\*\* (call|put)\n\*\*Quantity:\*\* (\d+) contracts\n\*\*Price:\*\* \$(\d+\.\d+)\n\*\*Total Investment:\*\* \$(\d+\.\d+)\n-----"
    buy_match = re.search(buy_pattern, message)
    if not buy_match:
        return "Invalid Buy Details"
    
    # Extract information
    strategy_name, ticker_symbol, strike_price, cp_value, buy_quantity, buy_price, total_investment = buy_match.groups()
    buy_quantity = int(buy_quantity)
    buy_price = float(buy_price)
    total_investment = float(total_investment)


    # Extract sell details
    sell_pattern = r"Sold (\d+) .+? contracts for \$(\d+\.\d+), Fill: (\d+\.\d+)"
    sell_matches = re.findall(sell_pattern, message)
    if not sell_matches:
        return "Invalid Sell Details"
    
    # Calculate the total sales
    total_sales = sum([float(sale[1]) for sale in sell_matches])
    # Calculate average bid
    total_contracts_sold = sum([int(sale[0]) for sale in sell_matches])
    total_bid_value = sum([int(sale[0]) * float(sale[2]) for sale in sell_matches])
    avg_bid = total_bid_value / total_contracts_sold
    # Calculate profit or loss
    profit_or_loss = total_sales - total_investment
    profit_or_loss_percentage = (profit_or_loss / total_investment) * 100
    
    #TODO: add 'avg_bid:.3f', 'profit_or_loss:.2f', 'profit_or_loss_percentage:.2f' to 'avg_sold_bid,total_profit,total_percentage' in order_log.csv
    update_order_details('order_log.csv', unique_order_id, avg_sold_bid=avg_bid, total_profit=profit_or_loss, total_percentage=profit_or_loss_percentage)

    if profit_or_loss_percentage >= 0: 
        #if trade is positive
        return f"\n-----\n**AVG BID:**    ${avg_bid:.3f}\n**TOTAL:**    ${profit_or_loss:.2f}✅\n**PERCENT:**    {profit_or_loss_percentage:.2f}%"

    else: 
        # if negitive
        return f"\n-----\n**AVG BID:**    ${avg_bid:.3f}\n**TOTAL:**    ${profit_or_loss:.2f}❌\n**PERCENT:**    {profit_or_loss_percentage:.2f}%"

async def sell_rest_of_active_order(reason_for_selling, retry_limit=3):
    global message_ids_dict
    global buy_entry_price
    global unique_order_id # f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
    global order_quantity
    global current_order_active
    global partial_exits

    retry_count = 0

    if current_order_active == False:
        return None
    if read_config("REAL_MONEY_ACTIVATED"):
        while current_order_active and retry_count < retry_limit:
            #calculate how much to sell/remaining quantity
            sell_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)

            #sell/Unpack the returned values from the sell function
            sold_bid_price, sold_quantity, success = await sell(sell_quantity, unique_order_id, message_ids_dict, reason_for_selling)
            
            if success and sold_quantity is not None and sold_bid_price is not None:
                #TODO: add 'time_exited_trade' to 'time_exited' to order_log.csv
                time_exited_trade = datetime.now().strftime("%m/%d/%Y-%I:%M:%S %p") # Convert to ISO format string
                update_order_details('order_log.csv', unique_order_id, time_exited=time_exited_trade)
                bid_percentage = calculate_bid_percentage(buy_entry_price, sold_bid_price)
                await add_markers("sell", None, None, bid_percentage)
                parts = unique_order_id.split('-')
                if len(parts) >= 5:
                    symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
                    order_log_name = f"order_log_{symbol}_{option_type}_{strike}_{_timestamp}.txt"
                    # Read the buy entry price from the log file
                    try:
                        
                        with open(order_log_name, "r") as log_file:
                            lines = log_file.readlines()
                            #buy_entry_price = float(lines[0].split(": ")[1])  #"Buy Entry Price: <price>"
                            bid_prices = [float(line.strip()) for line in lines[1:] if line.strip() and "Sold" not in line]
                            lowest_bid_price = min(bid_prices, default=buy_entry_price)
                            highest_bid_price = max(bid_prices, default=buy_entry_price)
                            #percentage_drop = ((buy_entry_price - lowest_bid_price) / buy_entry_price) * 100
                        #with open(order_log_name, "a") as log_file:
                            #log_file.write(f"Sold rest ({sell_quantity}) at {sold_bid_price}\nLowest Bid Price: {lowest_bid_price}, Max-Drawdown: {percentage_drop:.2f}%\n")
                            calculate_max_drawdown_and_gain(buy_entry_price, lowest_bid_price, highest_bid_price, True, order_log_name, unique_order_id)
                    except Exception as e:
                        await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", f"Error processing order log file")
                        return
                    
                #   Quantity of the order is zero now so we log it in discord
                _message_ = await get_message_content(message_ids_dict[unique_order_id]) 
                if _message_ is not None:
                    trade_info = calculate_profit_percentage(_message_, unique_order_id)
                    new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                    order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                    await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)  
                    
                    if os.path.exists(order_log_name):
                        os.remove(order_log_name)
                        print_log(f"Order log file {order_log_name} deleted.")
    
                    current_order_active = False
                    unique_order_id = None
                else:
                    await print_discord("Could not fetch message content.")

            else:
                # Retry logic
                retry_count += 1
                print_log(f"Retrying sell_rest_of_active_order... Attempt {retry_count}/{retry_limit}")
                await asyncio.sleep(1)  # Wait for 1 second before retrying

        if retry_count >= retry_limit:
            print_log("Reached maximum retry attempts for sell_rest_of_active_order")
            return False  # Indicate failure after all retries

        return True
    else: # this section is for 'submit_option_order_v2()' 
        sell_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)
        parts = unique_order_id.split('-')
        if len(parts) >= 5:
            symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
            order_log_name = f"order_log_{symbol}_{option_type}_{strike}_{_timestamp}.txt"
            # Read the buy entry price from the log file
            try:
                with open(order_log_name, "r") as log_file:
                    lines = log_file.readlines()
                    #buy_entry_price = float(lines[0].split(": ")[1])  #"Buy Entry Price: <price>"
                    sold_bid_price = float(lines[-1].strip())
                    bid_prices = [float(line.strip()) for line in lines[1:] if line.strip() and "Sold" not in line]
                    lowest_bid_price = min(bid_prices, default=buy_entry_price)
                    highest_bid_price = max(bid_prices, default=buy_entry_price)
                    order_cost = (buy_entry_price *100) * order_quantity
                    #percentage_drop = ((buy_entry_price - lowest_bid_price) / buy_entry_price) * 100

                sale_info = {
                    "target": "Not Defined",
                    "sold_price": sold_bid_price,  # Using actual sold bid price
                    "quantity": sell_quantity,  # Using actual sold quantity
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                bid_percentage = calculate_bid_percentage(buy_entry_price, sold_bid_price)
                await add_markers("sell", None, None, bid_percentage)
                partial_exits.append(sale_info)
                #TODO: add 'time_exited_trade' to 'time_exited' to order_log.csv
                time_exited_trade = datetime.now().strftime("%m/%d/%Y-%I:%M:%S %p") # Convert to ISO format string
                update_order_details('order_log.csv', unique_order_id, time_exited=time_exited_trade)
                calculate_max_drawdown_and_gain(buy_entry_price, lowest_bid_price, highest_bid_price, True, order_log_name, unique_order_id)
                #with open(order_log_name, "a") as log_file:
                    #log_file.write(f"Sold rest ({sell_quantity}) at {sold_bid_price}\nLowest Bid Price: {lowest_bid_price}, Max-Drawdown: {percentage_drop:.2f}%\n")
                    
                all_sells = 0
                for sells in partial_exits:
                    sell_cost = (sells["sold_price"] * 100) * sells["quantity"]
                    all_sells = all_sells + sell_cost

                precision = 2 # Define a precision level for rounding (e.g., 2 decimal places)
                order_cost_rounded = round(order_cost, precision)
                all_sells_rounded = round(all_sells, precision)
                profit_loss = all_sells_rounded - order_cost_rounded
                print_log(f"    [ORDER DETIALS] All Sells: {all_sells_rounded}, Order Cost: {order_cost_rounded}")
                print_log(f"    [ORDER DETIALS] Profit/Loss: ${profit_loss:.2f}")
                todays_orders_profit_loss_list.append(profit_loss)

                total_value = (sold_bid_price * 100) * sell_quantity
                _message_ = f"Sold {sell_quantity} {symbol} contracts for ${total_value:.2f}, Fill: {sold_bid_price}"
                if unique_order_id in message_ids_dict:
                    original_msg_id = message_ids_dict[unique_order_id]
                    #print(f"Fetching message content for order ID: {unique_order_id}, Message ID: {original_msg_id}")
                    try:
                        original_content = await get_message_content(original_msg_id)
                        if original_content:
                            updated_content = original_content + "\n" + _message_
                            #update discord order message
                            await edit_discord_message(original_msg_id, updated_content)
                        else:
                            print_log(f"Could not retrieve original message content for ID {original_msg_id}")
                    except Exception as e:  # Catch any exception to avoid stopping the loop
                        await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", "An error occurred while getting or edditing message")
                else:
                    print_log(f"Message ID for order {unique_order_id} not found in dictionary. Dictionary contents:\n{message_ids_dict}")
                #   Quantity of the order is zero now so we log it in discord
                _message_ = await get_message_content(message_ids_dict[unique_order_id])
                if _message_ is not None:
                    trade_info = calculate_profit_percentage(_message_, unique_order_id)
                    new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                    order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                    await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)
                    
                    if os.path.exists(order_log_name):
                        os.remove(order_log_name)
                        print_log(f"Order log file {order_log_name} deleted.")
                
                current_order_active = False
                unique_order_id = None
            
            except Exception as e:
                await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", f"Error processing order log file")
                return