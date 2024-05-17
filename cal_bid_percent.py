


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
    
percentage = calculate_bid_percentage(0.43, 0.76)
print(f"percentage: {percentage}%")