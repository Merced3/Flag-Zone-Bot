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
from error_handler import error_log_and_discord_message
import re

config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def read_config():
    with open(config_path, 'r') as f:
        config = json.load(f)
    return config
config = read_config()

SYMBOL = config["SYMBOL"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
STOP_LOSS_PERCENTAGE = config["STOP_LOSS_PERCENTAGE"]
RETRY_COUNT = 3
RETRY_DELAY = 3  # seconds

global unique_order_id
global order_quantity
global current_order_active
unique_order_id = None
current_order_active = False
global partial_exits
todays_orders_profit_loss_list = [] #added the variable here instead of tll_trading_strategy.py

# Define sell targets based on order quantity
sell_targets = {
    1: [20],
    2: [20],
    3: [20],
    4: [20],
    5: [20],
    6: [20, 35], 
    7: [20, 35],
    8: [20, 35],
    9: [20, 35],
    10: [20, 35],
    11: [20, 35],
    12: [20, 35, 55],
    13: [20, 35, 55],
    14: [20, 35, 55],
    15: [20, 35, 55],
    16: [20, 35, 55],
    17: [20, 35, 55],
    18: [20, 35, 55],
    19: [20, 35, 55],
    20: [20, 35, 55]
}

#do this, unless you find a adaptible solution that can handle all-use cases. 
sell_quantities = {
    1: [1],
    2: [2],
    3: [3],
    4: [4],
    5: [5],
    6: [5, 1],
    7: [6, 1],
    8: [7, 1],
    9: [8, 1],
    10: [9, 1],
    11: [10, 1],
    12: [10, 1, 1],
    13: [11, 1, 1],
    14: [12, 1, 1],
    15: [13, 1, 1],
    16: [14, 1, 1],
    17: [15, 1, 1],
    18: [15, 2, 1],
    19: [16, 2, 1],
    20: [17, 2, 1]
}
#sell_quantities = 10: [5, 3, 1, 1]
#sell_targets = 10: [20, 35, 55, 70]

def get_unique_order_id_and_is_active():
    #print(f"\nget_unique_order_id_and_is_active():\nunique_order_id: {unique_order_id}\ncurrent_order_active: {current_order_active}\n")
    return unique_order_id, current_order_active

def get_profit_loss_orders_list():
    return todays_orders_profit_loss_list

async def get_option_bid_price(symbol, strike, expiration_date, option_type, session):
    #only realtime data
    quote_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}markets/options/chains?symbol={symbol}&expiration={expiration_date}"
    headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
    
    async with session.get(quote_url, headers=headers) as response:
        if response.status != 200:
            print(f"    Received unexpected status code {response.status}: {await response.text()}")
            return None
        try:
            response_json = await response.json()
            # Here you'll need to navigate through the returned JSON to find the bid price of the specific option
            options_data = response_json.get('options', {}).get('option', [])
            target_strike = float(strike)
            filtered_options = [option for option in options_data if option['strike'] == target_strike and option['option_type'] == option_type]
            
            if filtered_options:
                # Displaying the first matching option
                return filtered_options[0]['bid']
            else:
                print("Option not found")
                return None
        except Exception as e:
            await error_log_and_discord_message(e, "order_handler", "get_option_bid_price", "Error parsing JSON")
            return None

def calculate_max_drawdown(start_price, lowest_price, write_to_file=None, order_log_name=None):
    max_drawdown = ((start_price - lowest_price)/start_price) *100
    
    if write_to_file is None:
        return "{:.2f}".format(max_drawdown)
    else:
        with open(order_log_name, "a") as log_file:
            log_file.write(f"Lowest Bid Price: {lowest_price}, Max-Drawdown: {max_drawdown:.2f}%\n")
            log_file.flush()

async def manage_active_order(active_order_details, message_ids_dict):
    global unique_order_id # f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
    global order_quantity
    global current_order_active
    global partial_exits

    async with aiohttp.ClientSession() as session:  # Creating a new session using a context manager
        order_id = active_order_details["order_retrieval"]
        
        if IS_REAL_MONEY:
            order_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/orders/{order_id}"
            headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
        else:
            order_url = f"{cred.TRADIER_SANDBOX_BASE_URL}accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/orders/{order_id}"
            headers = {"Authorization": f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}", "Accept": "application/json"}

        if not active_order_details.get("partial_exits"):
            active_order_details["partial_exits"] = []
        
        unique_order_id =   active_order_details["order_id"]

        buy_entry_price =   active_order_details["entry_price"]
        order_quantity  =   active_order_details["quantity"]
        targets = sell_targets.get(order_quantity, [])
        quantities_to_sell = sell_quantities.get(order_quantity, [])
        
        partial_exits = active_order_details["partial_exits"]
        sell_points = calculate_sell_points(buy_entry_price, targets)

        print_once_flag = True
        current_order_active = True
        lowest_bid_price = None
        buy_price_already_writen = None
        remaining_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)

        while current_order_active:  # Loop to manage an individual order
            if unique_order_id is None:  # Check if the order was cleared
                print("Order was cleared. Exiting management loop.")
                break

            async with session.get(order_url, headers=headers) as response:
                if response.status == 429:  # Too Many Requests, This is too not abuse Tradier Api requests
                    print("Rate limit exceeded, sleeping...")
                    await asyncio.sleep(60)  # Sleep for a minute
                elif response.status != 200:
                    print(f"    Received unexpected status code {response.status}: {await response.text()}")
                    continue
                        
                # submit_order.py, get_order_status(), 'unique_order_key' looks like this \/
                # unique_order_key = f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
                # Split 'unique_order_id' into its components
                if unique_order_id:
                    parts = unique_order_id.split('-')
                    if len(parts) >= 5:
                        symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
                        order_log_name = f"order_log({symbol}_{option_type}_{strike}_{_timestamp})"

                        
                        expiration_date_obj = datetime.strptime(expiration_date, "%Y%m%d")# Convert the expiration date to 'YYYY-MM-DD' format
                        formatted_expiration_date = expiration_date_obj.strftime("%Y-%m-%d")

                        # Check if we should print the message
                        if print_once_flag:
                            print(f"    Starting get_option_bid_price({symbol}, {strike}, {formatted_expiration_date}, {option_type}, session, headers)\n")
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
                            # Open the log file and write the bid price
                            with open(order_log_name, "a") as log_file:
                                if buy_price_already_writen is None:
                                    log_file.write(f"Buy Entry Price: {buy_entry_price}\n")
                                    buy_price_already_writen = True
                                log_file.write(f"{current_bid_price}\n")
                                log_file.flush()  # Ensure the data is written to the file

            # Check for stop loss condition
            if current_bid_price is not None and buy_entry_price is not None:
                current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                if current_loss_percentage <= STOP_LOSS_PERCENTAGE:
                    print(f"\nStop loss triggered at {current_loss_percentage}% loss.")
                    await sell_rest_of_active_order(message_ids_dict, "Stop Loss Triggered")
                    break

            #this handles the sell targets
            for i, sell_point in enumerate(sell_points):
                # Check if this target has already been hit and part of the order sold
                already_sold = any(sale['target'] == sell_point for sale in partial_exits)
                if current_bid_price >= sell_point and not already_sold:
                    sell_quantity = min(quantities_to_sell[i], remaining_quantity)

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
                        print(f"Sold {sold_quantity} at {sold_bid_price} target, {remaining_quantity} remaining.")
                        
                        #have 'already_sold' some how afftected right here, i think that will help with selling issue
                        
                        with open(order_log_name, "a") as log_file:
                            log_file.write(f"Sold {sold_quantity} at {sold_bid_price}\n")
                            log_file.flush()
                        if remaining_quantity <= 0:
                            calculate_max_drawdown(buy_entry_price, lowest_bid_price, True, order_log_name)
                            #print end of message calculations
                            _message_ = await get_message_content(message_ids_dict[unique_order_id])  
                            if _message_ is not None:
                                trade_info = calculate_profit_percentage(_message_)
                                new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                                await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content)
                                current_order_active = False
                                unique_order_id = None
                            else:
                                await print_discord("Could not fetch message content.")
                            break
                    else:
                        print("Sell order failed. Retrying...")
            if remaining_quantity <= 0:
                unique_order_id = None
                break
            # Wait before checking again
            await asyncio.sleep(.5)

async def manage_active_fake_order(active_order_details, message_ids_dict):
    global unique_order_id
    global order_quantity
    global current_order_active
    global partial_exits

    if active_order_details is None:
        return

    # Initialize variables from active_order_details
    unique_order_id = active_order_details["order_id"]
    buy_entry_price = active_order_details["entry_price"]
    order_quantity = active_order_details["quantity"]
    targets = sell_targets.get(order_quantity, [])
    quantities_to_sell = sell_quantities.get(order_quantity, [])
    partial_exits = active_order_details.get("partial_exits", [])
    sell_points = calculate_sell_points(buy_entry_price, targets)
    
    print_once_flag = True
    current_order_active = True
    lowest_bid_price = None
    buy_price_already_writen = None
    remaining_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)

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
                        order_log_name = f"order_log({symbol}_{option_type}_{strike}_{_timestamp})"
                        expiration_date_obj = datetime.strptime(expiration_date, "%Y%m%d")# Convert the expiration date to 'YYYY-MM-DD' format
                        formatted_expiration_date = expiration_date_obj.strftime("%Y-%m-%d")
                        with open(order_log_name, "a") as log_file:
                            if buy_price_already_writen is None:
                                log_file.write(f"Buy Entry Price: {buy_entry_price}\n")
                                buy_price_already_writen = True

                        # Check if we should print the message
                        if print_once_flag:
                            #print(f"    Starting get_option_bid_price({symbol}, {strike}, {formatted_expiration_date}, {option_type}, session)\n")
                            current_order_cost = order_quantity * (buy_entry_price * 100)
                            print(f"\nBought {order_quantity} at {buy_entry_price} resulting in a cost of ${current_order_cost:.2f}")
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
                            # Open the log file and write the bid price
                            with open(order_log_name, "a") as log_file:
                                log_file.write(f"{current_bid_price}\n")
                                log_file.flush()  # Ensure the data is written to the file

                # Check for stop loss condition
                if current_bid_price is not None and buy_entry_price is not None:
                    current_loss_percentage = ((current_bid_price - buy_entry_price) / buy_entry_price) * 100
                    if current_loss_percentage <= STOP_LOSS_PERCENTAGE:
                        Sell_order_cost = remaining_quantity * (current_bid_price * 100)
                        print(f"Stop loss triggered at {current_loss_percentage:.2f}% loss. Sold {remaining_quantity} at {current_bid_price}, costing ${Sell_order_cost:.2f}")
                        await sell_rest_of_active_order(message_ids_dict, "Stop Loss Triggered")
                        break

                #this handles the sell targets
                for i, sell_point in enumerate(sell_points):
                    # Check if this target has already been hit and part of the order sold
                    already_sold = any(sale['target'] == sell_point for sale in partial_exits)
                    if current_bid_price >= sell_point and not already_sold:
                        sell_quantity = min(quantities_to_sell[i], remaining_quantity)

                        sale_info = {
                            "target": sell_point,
                            "sold_price": current_bid_price,  # Using actual sold bid price
                            "quantity": sell_quantity,  # Using actual sold quantity
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }
                        partial_exits.append(sale_info)
                        remaining_quantity -= sell_quantity
                        sold_order_cost = (current_bid_price * 100) * sell_quantity
                        print(f"Sold {sell_quantity} at {current_bid_price} target, {remaining_quantity} remaining. Order Cost: ${sold_order_cost:.2f}")
                            
                        with open(order_log_name, "a") as log_file:
                            log_file.write(f"Sold {sell_quantity} at {current_bid_price}\n")
                            log_file.flush()

                        total_value = (current_bid_price * 100) * sell_quantity
                        _message_ = f"Sold {sell_quantity} {symbol} contracts for ${total_value:.2f}, Fill: {current_bid_price}"
                        if unique_order_id in message_ids_dict:
                            original_msg_id = message_ids_dict[unique_order_id]
                            try:
                                original_content = await get_message_content(original_msg_id, "412")
                                if original_content:
                                    updated_content = original_content + "\n" + _message_
                                    #update discord order message
                                    await edit_discord_message(original_msg_id, updated_content)
                                else:
                                    print(f"Could not retrieve original message content for ID {original_msg_id}")
                            except Exception as e:  # Catch any exception to avoid stopping the loop
                                await error_log_and_discord_message(e, "order_handler", "manage_active_fake_order", "An error occurred while getting or edditing message")
                        else:
                            print(f"Message ID for order {unique_order_id} not found in dictionary. Dictionary contents:\n{message_ids_dict}")

                        if remaining_quantity <= 0:
                            calculate_max_drawdown(buy_entry_price, lowest_bid_price, True, order_log_name)
                            #print end of message calculations
                            _message_ = await get_message_content(message_ids_dict[unique_order_id], "427")  
                            if _message_ is not None:
                                trade_info = calculate_profit_percentage(_message_)
                                new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                                order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                                await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)
                                # Verify if the file was sent and then delete the log file
                                if os.path.exists(order_log_name):
                                    os.remove(order_log_name)
                                    print(f"Order log file {order_log_name} deleted.")
                            else:
                                await print_discord("Could not fetch message content.")
                            current_order_active = False
                            unique_order_id = None
                            break
                if remaining_quantity <= 0:
                    all_sells = 0
                    for sells in partial_exits:
                        sell_cost = (sells["sold_price"] * 100) * sells["quantity"]
                        all_sells = all_sells + sell_cost

                    profit_loss = all_sells - current_order_cost 
                    print(f"(manage_active_fake_order) Profit/Loss: ${profit_loss:.2f}")
                    todays_orders_profit_loss_list.append(profit_loss)
                    unique_order_id = None
                    break
                # Wait before checking again
                await asyncio.sleep(.5)
            except aiohttp.ClientOSError as e:
                if retry_attempts < RETRY_COUNT:
                    print(f"Encountered an error: {e}. Retrying in {RETRY_DELAY} seconds.")
                    await asyncio.sleep(RETRY_DELAY)
                    retry_attempts += 1
                else:
                    print("Maximum retry attempts reached. Exiting the loop.")
                    break

async def sell(quantity, unique_order_key, message_ids_dict, reason_for_selling):
    #selling logic here
    bid = None
    side = "sell_to_close"
    order_type = "market"
    print(f"\n    message_ids_dict[unique_order_key]: {message_ids_dict[unique_order_key]}")

    symbol, cp, strike, expiration_date, timestamp_from_order_id = unique_order_key.split('-')[:5]
    
    message_channel = bot.get_channel(cred.DISCORD_CHANNEL_ID)
    if message_channel is None:
        print(f"Failed to find Discord channel with ID {cred.DISCORD_CHANNEL_ID}")
        return None, None, None
    print(f"    REASON FOR SELLING: {reason_for_selling}")
    #execute sell
    order_result = await submit_option_order(
        IS_REAL_MONEY, symbol, strike, cp, bid, expiration_date, quantity, side, order_type
    )
    if order_result:
        unique_order_ID, order_bid_price, order_quantity = await get_order_status(
            strategy_name=None,
            real_money_activated=IS_REAL_MONEY,
            order_id=order_result['order_id'],
            b_s="sell",
            ticker_symbol=symbol,
            cp=cp,
            strike=strike,
            expiration_date=expiration_date,
            order_timestamp=timestamp_from_order_id,
            message_ids_dict=message_ids_dict
        )

        print(f"    sell() = {order_bid_price}, {order_quantity}, {True}\n")

        return order_bid_price, order_quantity, True

    if order_result == "rejected":
        return None, None, False
    
    return None, None, False

def calculate_sell_points(buy_entry_price, percentages):
    return [buy_entry_price * (1 + p / 100) for p in percentages]

def calculate_profit_percentage(message):
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
    if profit_or_loss_percentage >= 0: 
        #if trade is positive
        return f"\n-----\n**AVG BID:**    ${avg_bid:.3f}\n**TOTAL:**    ${profit_or_loss:.2f}✅\n**PERCENT:**    {profit_or_loss_percentage:.2f}%"

    else: 
        # if negitive
        return f"\n-----\n**AVG BID:**    ${avg_bid:.3f}\n**TOTAL:**    ${profit_or_loss:.2f}❌\n**PERCENT:**    {profit_or_loss_percentage:.2f}%"

async def sell_rest_of_active_order(message_ids_dict, reason_for_selling, retry_limit=3):
    global unique_order_id # f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"
    global order_quantity
    global current_order_active
    global partial_exits

    retry_count = 0

    if current_order_active == False:
        return None
    if IS_REAL_MONEY:
        while current_order_active and retry_count < retry_limit:
            #calculate how much to sell/remaining quantity
            sell_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)

            #sell/Unpack the returned values from the sell function
            sold_bid_price, sold_quantity, success = await sell(sell_quantity, unique_order_id, message_ids_dict, reason_for_selling)

            if success and sold_quantity is not None and sold_bid_price is not None:
                parts = unique_order_id.split('-')
                if len(parts) >= 5:
                    symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
                    order_log_name = f"order_log({symbol}_{option_type}_{strike}_{_timestamp})"
                    # Read the buy entry price from the log file
                    try:
                        with open(order_log_name, "r") as log_file:
                            lines = log_file.readlines()
                            buy_entry_price = float(lines[0].split(": ")[1])  #"Buy Entry Price: <price>"
                            bid_prices = [float(line.strip()) for line in lines[1:] if line.strip() and "Sold" not in line]
                            lowest_bid_price = min(bid_prices, default=buy_entry_price)

                            percentage_drop = ((buy_entry_price - lowest_bid_price) / buy_entry_price) * 100
                        with open(order_log_name, "a") as log_file:
                            log_file.write(f"Sold rest ({sell_quantity}) at {sold_bid_price}\nLowest Bid Price: {lowest_bid_price}, Max-Drawdown: {percentage_drop:.2f}%\n")
                    except Exception as e:
                        await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", f"Error processing order log file")
                        return
                    
                #   Quantity of the order is zero now so we log it in discord
                _message_ = await get_message_content(message_ids_dict[unique_order_id]), "579"  
                if _message_ is not None:
                    trade_info = calculate_profit_percentage(_message_)
                    new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                    order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                    await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)  
                    
                    if os.path.exists(order_log_name):
                        os.remove(order_log_name)
                        print(f"Order log file {order_log_name} deleted.")
    
                    current_order_active = False
                    unique_order_id = None
                else:
                    await print_discord("Could not fetch message content.")

            else:
                # Retry logic
                retry_count += 1
                print(f"Retrying sell_rest_of_active_order... Attempt {retry_count}/{retry_limit}")
                await asyncio.sleep(1)  # Wait for 1 second before retrying

        if retry_count >= retry_limit:
            print("Reached maximum retry attempts for sell_rest_of_active_order")
            return False  # Indicate failure after all retries

        return True
    else: # this section is for 'submit_option_order_v2()' 
        sell_quantity = order_quantity - sum(sale['quantity'] for sale in partial_exits)
        parts = unique_order_id.split('-')
        if len(parts) >= 5:
            symbol, option_type, strike, expiration_date, _timestamp = parts[:5]
            order_log_name = f"order_log({symbol}_{option_type}_{strike}_{_timestamp})"
            # Read the buy entry price from the log file
            try:
                with open(order_log_name, "r") as log_file:
                    lines = log_file.readlines()
                    buy_entry_price = float(lines[0].split(": ")[1])  #"Buy Entry Price: <price>"
                    sold_bid_price = float(lines[-1].strip())
                    bid_prices = [float(line.strip()) for line in lines[1:] if line.strip() and "Sold" not in line]
                    lowest_bid_price = min(bid_prices, default=buy_entry_price)
                    order_cost = (buy_entry_price *100) * order_quantity
                    percentage_drop = ((buy_entry_price - lowest_bid_price) / buy_entry_price) * 100

                sale_info = {
                    "target": "Not Defined",
                    "sold_price": sold_bid_price,  # Using actual sold bid price
                    "quantity": sell_quantity,  # Using actual sold quantity
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                partial_exits.append(sale_info)
                

                with open(order_log_name, "a") as log_file:
                    log_file.write(f"Sold rest ({sell_quantity}) at {sold_bid_price}\nLowest Bid Price: {lowest_bid_price}, Max-Drawdown: {percentage_drop:.2f}%\n")
                    all_sells = 0
                    for sells in partial_exits:
                        sell_cost = (sells["sold_price"] * 100) * sells["quantity"]
                        all_sells = all_sells + sell_cost

                    precision = 2 # Define a precision level for rounding (e.g., 2 decimal places)
                    order_cost_rounded = round(order_cost, precision)
                    all_sells_rounded = round(all_sells, precision)
                    profit_loss = all_sells_rounded - order_cost_rounded
                    print(f"All Sells: {all_sells_rounded}, Order Cost: {order_cost_rounded}")
                    print(f"(sell_rest_of_active_order) Profit/Loss: ${profit_loss:.2f}")
                    todays_orders_profit_loss_list.append(profit_loss)

                total_value = (sold_bid_price * 100) * sell_quantity
                _message_ = f"Sold {sell_quantity} {symbol} contracts for ${total_value:.2f}, Fill: {sold_bid_price}"
                if unique_order_id in message_ids_dict:
                    original_msg_id = message_ids_dict[unique_order_id]
                    #print(f"Fetching message content for order ID: {unique_order_id}, Message ID: {original_msg_id}")
                    try:
                        original_content = await get_message_content(original_msg_id, "633") #this one works and is getting the message
                        if original_content:
                            updated_content = original_content + "\n" + _message_
                            #update discord order message
                            await edit_discord_message(original_msg_id, updated_content)
                        else:
                            print(f"Could not retrieve original message content for ID {original_msg_id}")
                    except Exception as e:  # Catch any exception to avoid stopping the loop
                        await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", "An error occurred while getting or edditing message")
                else:
                    print(f"Message ID for order {unique_order_id} not found in dictionary. Dictionary contents:\n{message_ids_dict}")
                #   Quantity of the order is zero now so we log it in discord
                _message_ = await get_message_content(message_ids_dict[unique_order_id], "645")  
                if _message_ is not None:
                    trade_info = calculate_profit_percentage(_message_)
                    new_user_msg_content = _message_ + trade_info  # Append the trade info to the original message content
                    order_log_file_path = Path(__file__).resolve().parent / f"{order_log_name}"
                    await edit_discord_message(message_ids_dict[unique_order_id], new_user_msg_content, None, order_log_file_path)
                    
                    if os.path.exists(order_log_name):
                        os.remove(order_log_name)
                        print(f"Order log file {order_log_name} deleted.")
                
                current_order_active = False
                unique_order_id = None
            
            except Exception as e:
                await error_log_and_discord_message(e, "order_handler", "sell_rest_of_active_order", f"Error processing order log file")
                return