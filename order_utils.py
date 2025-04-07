# order_utils.py, 
from data_acquisition import read_config
from datetime import datetime, timedelta
from shared_state import indent, print_log

def build_active_order(order_id, retrieval_id, entry_price, quantity, TP_value=None, order_adjustments=None):
    return {
        "order_id": order_id,
        "order_retrieval": retrieval_id,
        "entry_price": entry_price,
        "quantity": quantity,
        "TP_value": TP_value,
        "order_adjustments": order_adjustments if order_adjustments else []
    }

def calculate_quantity(cost_per_contract, order_size_for_account):
    # 'order_size_for_account' represents the percentage of the account you want to spend on each order.
    order_threshold = read_config('ACCOUNT_BALANCES')[0] * order_size_for_account
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

    return quantity

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
            print_log(f"Canceled the buy, Invalid expiration date (weekend): {expiration_date}")
            return
        return expiration_date
    else:
        print_log(f"Canceled the buy, Invalid expiration date: {expiration_date}")
        return

def get_tp_value(indent_lvl, candle_zone_type, action, zones):
    try:
        if '---' in candle_zone_type:
            above_zone_raw, below_zone_raw = candle_zone_type.split('---')
            above_zone_raw = above_zone_raw.strip()
            below_zone_raw = below_zone_raw.strip()

            # Select the correct side based on trade direction
            target_zone_raw = above_zone_raw if action == "call" else below_zone_raw

            # Extract zone name and extension
            target_parts = target_zone_raw.split()  # e.g., ['support_3', 'PDL']
            if len(target_parts) < 2:
                raise ValueError("Missing zone extension (e.g., 'PDL', 'PDH', 'Buffer')")

            zone_name = target_parts[0]
            extension = target_parts[1].lower()  # 'pdl', 'pdh', 'buffer'

            if zone_name not in zones:
                raise ValueError(f"Zone '{zone_name}' not found in zones dictionary.")

            x_pos, high_low_of_day, buffer = zones[zone_name]

            # Logic for determining which value to use as TP
            if (
                (("support" in zone_name.lower() and extension == "pdl") or
                (("resistance" in zone_name.lower() or "pdhl" in zone_name.lower()) and extension == "pdh"))
            ):
                return high_low_of_day
            elif (
                (("support" in zone_name.lower() and extension == "buffer") or
                (("resistance" in zone_name.lower() or "pdhl" in zone_name.lower()) and extension == "buffer"))
            ):
                return buffer
            else:
                return None  # Unknown case
        else:
            # We're either below all zones or above all zones
            # Expected format: "below ZONE_NAME EXT" or "above ZONE_NAME EXT"
            parts = candle_zone_type.strip().split()

            if len(parts) != 3:
                raise ValueError(f"Invalid format for candle_zone_type: {candle_zone_type}")
            
            # zones = {'PDHL_1': (702, 525.87, 505.06), 'support_1': (701, 536.9, 537.64), 'PDHL_2': (624, 554.81, 553.68), 'PDHL_3': (598, 547.97, 546.87), 'PDHL_5': (27, 598.2, 597.34), 'resistance_1': (494, 576.41, 575.805), 'resistance_2': (364, 565.02, 564.19), 'support_2': (301, 549.68, 551.16), 'resistance_3': (166, 580.1736, 579.35), 'support_3': (98, 585.97, 587.48), 'support_4': (22, 591.8556, 592.54)}
            
            direction, zone_name, extension = parts

            if zone_name not in zones:
                raise ValueError(f"Zone '{zone_name}' not found in zones dictionary.")
            
            x_pos, high_low_of_day, buffer = zones[zone_name]
            
            if (direction == "below" and action == "call") or (direction == "above" and action == "put"):
                # If we are below all zones and want to go long (call), use zone above as TP (high/low of day)
                # If we are above all zones and want to go short (put), use zone below as TP (high/low of day)

                if 'resistance' in zone_name or 'PDHL' in zone_name:
                    if "Buffer" in extension or "PDL" in extension: 
                        return buffer
                    if 'PDH' in extension:
                        return  high_low_of_day
                elif 'support' in zone_name:
                    if "PDL" in extension: 
                        return high_low_of_day
                    if 'Buffer' in extension:
                        return  buffer
            
            # All other combos (e.g., put below, call above) = no TP
            return None

    except Exception as e:
        print_log(f"{indent(indent_lvl)}[HRAO TP ZONE ERROR] Failed to determine TP_value → {e}")
        return None

def get_strikes_to_consider(cp, current_price, num_out_of_the_money, options):
    strikes_to_consider = {}
    for option in options:
        strike = option['strike']
        ask = option['ask']

        # Only include if ask is valid
        if ask is None:
            continue

        # Call = strike >= current price
        if cp == "call" and strike >= current_price:
            if strike <= current_price + num_out_of_the_money:
                strikes_to_consider[strike] = ask

        # Put = strike <= current price
        elif cp == "put" and strike <= current_price:
            if strike >= current_price - num_out_of_the_money:
                strikes_to_consider[strike] = ask

    return strikes_to_consider

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


