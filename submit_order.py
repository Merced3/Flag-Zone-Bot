#submit_order.py
import cred
from datetime import datetime, timedelta
import requests
from print_discord_messages import print_discord, get_message_content, edit_discord_message
import aiohttp
from error_handler import error_log_and_discord_message
from pathlib import Path
import json
import sys

config_path = Path(__file__).resolve().parent / 'config.json'
MESSAGE_IDS_FILE_PATH = Path(__file__).resolve().parent / 'message_ids.json'

def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config

config = read_config()
SYMBOL = config["SYMBOL"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
ACCOUNT_BALANCE = config["ACCOUNT_BALANCES"][0]

def save_message_ids(order_id, message_id):
    # Load existing data
    if MESSAGE_IDS_FILE_PATH.exists():
        with open(MESSAGE_IDS_FILE_PATH, 'r') as f:
            try:
                existing_data = json.load(f)
            except json.JSONDecodeError:
                existing_data = {}
    else:
        existing_data = {}

    # Update existing data with new data
    existing_data[order_id] = message_id

    # Write updated data back to file
    with open(MESSAGE_IDS_FILE_PATH, 'w') as f:
        json.dump(existing_data, f, indent=4)

async def find_what_to_buy(symbol, cp, num_out_of_the_money, next_expiration_date, session, headers):
    # Replace with actual URL to fetch option chain data
    option_chain_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}markets/options/chains?symbol={symbol}&expiration={next_expiration_date}"
    
    async with session.get(option_chain_url, headers=headers) as response:
        if response.status != 200:
            print(f"Received unexpected status code {response.status}: {await response.text()}")
            return None
        try:
            response_json = await response.json()
            options = response_json.get('options', {}).get('option', [])
            
            # Filter the options based on the 'cp' variable (call or put)
            filtered_options = [opt for opt in options if opt['option_type'] == cp]
            
            # Get the current price to determine the range of strikes to consider
            current_price = await get_current_price(symbol, session, headers)
            if not current_price:
                raise ValueError("Could not determine current price.")
            
            # Determine the strikes to consider based on the current price
            strikes_to_consider = get_strikes_to_consider(current_price, num_out_of_the_money, filtered_options)
            
            #print(f"    Price: {current_price}\n    Strikes to consider:\n{json.dumps(strikes_to_consider, indent=4)}\n")
            
            # Define the price ranges
            price_ranges = [(0.30, 0.50), (0.20, 0.80), (0.10, 1.25)]
            
            # Find the appropriate contract within the asking price ranges
            for lower_bound, upper_bound in price_ranges:
                for strike, ask in strikes_to_consider.items():
                    if lower_bound <= ask <= upper_bound:
                        return strike, ask
            
            print("No contracts found within the specified price ranges.")
            return None
            
        except Exception as e:
            await error_log_and_discord_message(e, "submit_order", "find_what_to_buy", "Error parsing JSON or processing data")
            return None

async def get_current_price(symbol, session, headers):
    quote_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}markets/quotes?symbols={symbol}"

    async with session.get(quote_url, headers=headers) as response:  # And here
        if response.status != 200:
            print(f"Received unexpected status code {response.status}: {await response.text()}")
            return None
        try:
            response_json = await response.json()
            quote = response_json.get('quotes', {}).get('quote', {})
            current_price = quote.get('bid', None)
            return current_price
        except Exception as e:
            await error_log_and_discord_message(e, "submit_order", "get_current_price", "Error parsing JSON")
            return None

async def submit_option_order_v2(strategy_name, symbol, strike, option_type,  expiration_date, session, headers, message_ids_dict, buying_power):

    #TODO: figure out how to get discord messaging working with this
    bid = None
    side = "buy_to_open"
    order_type = "market"
    
    option_chain_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}markets/options/chains?symbol={symbol}&expiration={expiration_date}"

    async with session.get(option_chain_url, headers=headers) as response:
        if response.status != 200:
            print(f"Received unexpected status code {response.status}: {await response.text()}")
            return None
        try:
            response_json = await response.json()
            options = response_json.get('options', {}).get('option', [])
            
            # Filter the options based on the 'cp' variable (call or put)
            filtered_options = [opt for opt in options if opt['option_type'] == option_type]
            
            # Get the ask price for the current contract
            for option in filtered_options:
                #print(f"{option['strike']} == {strike}")
                if option['strike'] == strike:
                    ask = option['ask']
            
            if ask is not None:
                percentage_of_balance = 0.1
                while True:
                    quantity = calculate_quantity(ask, percentage_of_balance, 30)
                    order_cost = (ask * 100) * quantity #order_cost = (ask * 100 + commission_fee) * quantity
                    if order_cost <= buying_power:
                        break  # If the cost fits within the buying power, proceed with this quantity
                    else:
                        percentage_of_balance -= 0.01  # Decrease the percentage and recheck
                        if percentage_of_balance <= 0:
                            # If the percentage drops too low (e.g., below 1%), cancel the order
                            print("Not enough buying power for even a single contract.")
                            return None
            else:
                await error_log_and_discord_message(e, "submit_order", "submit_option_order_v2", "Error getting option [ask] price")

            timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
            unique_order_ID = f"{symbol}-{option_type}-{strike}-{expiration_date}-{timestamp}"
            total_investment = (ask * 100) * quantity
            _message_ = f"**{strategy_name}**\n-----\n**Ticker Symbol:** {symbol}\n**Strike Price:** {strike}\n**Option Type:** {option_type}\n**Quantity:** {quantity} contracts\n**Price:** ${ask:.2f}\n**Total Investment:** ${total_investment:.2f}\n-----"
            message_obj = await print_discord(_message_)
            message_ids_dict[unique_order_ID] = message_obj.id # Save message ID for this specific order
            save_message_ids(unique_order_ID, message_ids_dict[unique_order_ID])
            #print(f"    Saved Message ID {message_obj.id} for {unique_order_ID}. Current dictionary state: {message_ids_dict}") #this dictionary holds all the trades message ID's, those Message ID holds all the info to that specific trade.
                        
            
            active_order = {# Your active order details
                'order_id': unique_order_ID,
                'order_retrieval': None,
                'entry_price': ask,
                'quantity': quantity,
                'partial_exits': []
            }
            return active_order
            
        except Exception as e:
            await error_log_and_discord_message(e, "submit_order", "submit_option_order_v2")
            return None

def get_strikes_to_consider(current_price, num_out_of_the_money, options):
    strikes_to_consider = {}
    for option in options:
        strike = option['strike']
        ask = option['ask']

        # Define the range of strike prices based on current_price and num_out_of_the_money
        lower_bound = current_price - num_out_of_the_money
        upper_bound = current_price + num_out_of_the_money

        if lower_bound <= strike <= upper_bound:
            strikes_to_consider[strike] = ask

    return strikes_to_consider

# real_money_activated dictates if were paper trading or real money trading. 
async def submit_option_order(real_money_activated, symbol, strike, option_type, bid, expiration_date, quantity, side, order_type):
    if real_money_activated:
        order_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/orders"
        headers = {
            "Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",
            "Accept": "application/json"
        }
    else:
        order_url = f"{cred.TRADIER_SANDBOX_BASE_URL}accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/orders"
        headers = {
            "Authorization": f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}",
            "Accept": "application/json"
        }
    
    expiration_date = datetime.strptime(expiration_date, "%Y%m%d").strftime("%y%m%d")
    option_symbol = f"{symbol}{expiration_date}{option_type[0].upper()}{int(float(strike) * 1000):08d}"

    order_type = 'market' if bid is None or bid == 'not specified' else 'limit'

    payload = {
        "class": "option",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "type": order_type,
        "duration": "gtc",
        "option_symbol": option_symbol,
    }

    if order_type == 'limit':
        payload["price"] = bid

    print(f"    Submitting order with payload: {payload}") #---------------------------------------------------------------------

    response = requests.post(order_url, headers=headers, data=payload)
    print(f"    response: {response}")

    if response.status_code == 200:
        response_data = response.json()
        if 'order' in response_data:
            await print_discord("    Order Submitted", f"{symbol} Buy Order Pending" if side=="buy_to_open" else "Sell Order Pending")
            result = {'order_id': response_data['order']['id']}
            if bid and bid != 'not specified':
                result['total_value'] = float(bid) * quantity * 100
            return result
        elif 'error' in response_data['errors']:
            #getting account balance
            if real_money_activated:
                endpoint = f'{cred.TRADIER_BROKERAGE_BASE_URL}v1/accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/balances'
                headers = {'Authorization': f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}",'Accept': 'application/json'}
            else:
                endpoint = f'{cred.TRADIER_SANDBOX_BASE_URL}v1/accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/balances'
                headers = {'Authorization': f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}",'Accept': 'application/json'}
            response = requests.get(endpoint,headers=headers)
            json_response = response.json()
            
            if 'cash' in json_response['balances']:
                account_buying_power = json_response['balances']['cash']['cash_available']
                order_cost = float(bid) * quantity * 100 if bid and bid != 'not specified' else 0
                await print_discord(f"\nOrder submission failed. Settled Funds too low: ${account_buying_power}. Order Cost: ${order_cost}")
            else:
                await print_discord(f"\nOrder submission failed. Settled Funds not available. Account Response content: {response.content}")
        else:
            await print_discord(f"\nOrder submission failed. Response content: {response.content}")
    else:
        if response.status_code == 500:
            error_message = "500 errors typically mean that something isn't working properly with Tradier API. Please let us know by emailing techsupport@tradier.com."
        else:
            error_message = f"Order failed, response content: {response.content}"

        await print_discord(f"\nOrder submission failed. Response status code: {response.status_code}", error_message)
        return None
    
async def get_order_status(strategy_name, real_money_activated, order_id, b_s, ticker_symbol, cp, strike, expiration_date, order_timestamp, message_ids_dict):
    if real_money_activated:
        order_url = f"{cred.TRADIER_BROKERAGE_BASE_URL}accounts/{cred.TRADIER_BROKERAGE_ACCOUNT_NUMBER}/orders/{order_id}"
        headers = {"Authorization": f"Bearer {cred.TRADIER_BROKERAGE_ACCOUNT_ACCESS_TOKEN}", "Accept": "application/json"}
    else:
        order_url = f"{cred.TRADIER_SANDBOX_BASE_URL}accounts/{cred.TRADIER_SANDBOX_ACCOUNT_NUMBER}/orders/{order_id}"
        headers = {"Authorization": f"Bearer {cred.TRADIER_SANDBOX_ACCESS_TOKEN}", "Accept": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        loading_chars = "|/-\\"
        i = 0
        status = 'open'  # Initialize status outside the loop
        while status == 'open':
            async with session.get(order_url, headers=headers) as response:
                response_content = await response.text()
                #print(response_content)  # Add this line to print the response content

                try:
                    response_json = await response.json()
                except Exception as e:
                    await error_log_and_discord_message(e, "submit_order", "get_order_status", "Error parsing JSON")
                    continue
                order = response_json['order']
                status = order['status']

                sys.stdout.write("\033[K")  # Clear the current line
                sys.stdout.write(f"\r{status} {loading_chars[i % len(loading_chars)]}", )#end='', flush=True)
                sys.stdout.flush()

                if status == 'filled':
                    print("")  # Print a newline to move to the next line after the order is filled
                    unique_order_key = f"{ticker_symbol}-{cp}-{strike}-{expiration_date}-{order_timestamp}"#generate_unique_key(ticker_symbol, cp, strike, expiration_date, order_timestamp)
                    order_price = float(order.get('avg_fill_price', 0))
                    order_quantity = int(order.get('quantity', 0))

                    if b_s == "buy":
                        
                        total_investment = order_price * order_quantity * 100
                        #await sell_button_generation(ticker_symbol, order_quantity, cp, strike, expiration_date, order_timestamp)
                        _message_ = f"**{strategy_name}**\n-----\n**Ticker Symbol:** {ticker_symbol}\n**Strike Price:** {strike}\n**Option Type:** {cp}\n**Quantity:** {order_quantity} contracts\n**Price:** ${order_price:.2f}\n**Total Investment:** ${total_investment:.2f}\n-----"
                        
                        message_obj = await print_discord(_message_, delete_last_message=True)
                        message_ids_dict[unique_order_key] = message_obj.id # Save message ID for this specific order
                        save_message_ids(unique_order_key, message_ids_dict[unique_order_key])
                        #print(f"    Saved Message ID {message_obj.id} for {unique_order_key}. Current dictionary state: {message_ids_dict}") #this dictionary holds all the trades message ID's, those Message ID holds all the info to that specific trade.
                        
                    else: #sell
                        total_value = order_price * order_quantity * 100
                        _message_ = f"Sold {order_quantity} {ticker_symbol} contracts for ${total_value:.2f}, Fill: {order_price}"
                        
                        if unique_order_key in message_ids_dict:
                            original_msg_id = message_ids_dict[unique_order_key]
                            try:
                                original_content = await get_message_content(original_msg_id)
                                if original_content:
                                    updated_content = original_content + "\n" + _message_
                                    #update discord order message
                                    await edit_discord_message(original_msg_id, updated_content, True)
                                else:
                                    print(f"Could not retrieve original message content for ID {original_msg_id}")
                            except Exception as e:  # Catch any exception to avoid stopping the loop
                                await error_log_and_discord_message(e, "submit_order", "get_order_status", "An error occurred while getting or edditing message")
                        else:
                            print(f"Message ID for order {unique_order_key} not found in dictionary. Dictionary contents:\n{message_ids_dict}")
                    return unique_order_key, order_price, order_quantity
                elif status == 'canceled':
                    print("")
                    await print_discord(f"{ticker_symbol} Order Canceled", delete_last_message=True)
                    return status
                elif status == 'rejected':
                    print("")
                    await print_discord(f"{ticker_symbol} Order Rejected", delete_last_message=True)
                    return status
            i += 1

def get_expiration(expiration_date):
    current_datetime = datetime.now()
    if expiration_date == "not specified":  # default expiration is whenever the script is run
        expiration_date = current_datetime.strftime("%Y%m%d")  # 20230326 for example
        return expiration_date
    elif expiration_date[:-3].isdigit() and expiration_date[-3:] == "dte": #if 1dte, 2dte... is true
        number_of_days = int(expiration_date[:-3])
        expiration_date_str = current_datetime + timedelta(days=number_of_days)
        expiration_date = expiration_date_str.strftime("%Y%m%d")
        expiration_day_of_week = expiration_date_str.weekday()  # Monday is 0 and Sunday is 6
        # Check if the expiration date is a Saturday (5) or Sunday (6)
        if expiration_day_of_week in [5, 6]:
            print(f"Canceled the buy, Invalid expiration date (weekend): {expiration_date}")
            return
        return expiration_date
    else:
        print(f"Canceled the buy, Invalid expiration date: {expiration_date}")
        return
        
def calculate_quantity(cost_per_contract, order_size_for_account, quant_limit=30):
    # 'order_size_for_account' represents the percentage of the account you want to spend on each order.
    order_threshold = ACCOUNT_BALANCE * order_size_for_account
    order_cost = cost_per_contract * 100

    order_quantity = order_threshold / order_cost
    #print(f"Order quantity before processing: {order_quantity}")

    if order_quantity > 1.0:
        # Round down to the nearest whole number
        order_quantity = int(order_quantity)
        # Check if the rounded down quantity exceeds the order threshold
        if (order_quantity * order_cost) > order_threshold:
            # If it does, reduce the quantity by one
            order_quantity -= 1
        quantity = order_quantity

    elif order_quantity < 1.0:
        # One contract exceeds the order threshold, so use one contract
        quantity = 1

    if quantity > quant_limit:
        # Limit to a maximum of 30 contracts
        quantity = quant_limit

    new_order_cost = quantity * (order_cost)
    #print(f"Order Cost: ${new_order_cost:.2f}")

    return quantity