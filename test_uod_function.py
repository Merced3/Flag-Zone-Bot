import os
import csv
from datetime import datetime
import pandas as pd
from data_acquisition import initialize_order_log, update_order_details, log_order_details

# Test script
def main():
    log_file = 'order_log_test.csv'
    
    # Initialize the log file
    initialize_order_log(log_file)

    # Log an initial order detail
    what_type_of_candle = "Bull Flag"
    time_entered = datetime.now().strftime("%m/%d/%Y-%I:%M %p")
    ema_distance = 0.15
    num_of_matches = 2
    line_degree_angle = 35.7
    ticker_symbol = "SPY"
    strike_price = 540.0
    option_type = "call"
    order_quantity = 10
    order_bid_price = 0.34
    total_investment = order_quantity * order_bid_price * 100

    log_order_details(log_file, what_type_of_candle, time_entered, ema_distance, num_of_matches, line_degree_angle,
                      ticker_symbol, strike_price, option_type, order_quantity, order_bid_price, total_investment)

    # Simulate unique_order_id (same format as your code)
    unique_order_id = f"{ticker_symbol}-{option_type}-{strike_price}-20240802-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Test updating the order with additional details
    additional_details = {
        'time_exited': datetime.now().strftime("%m/%d/%Y-%I:%M %p"),
        'lowest_bid': 0.30,
        'max_drawdown': 11.76,
        'highest_bid': 0.50,
        'max_gain': 47.06,
        'avg_sold_bid': 0.40,
        'total_profit': 60.0,
        'total_percentage': 17.65
    }

    #simulating function being called in calculate_max_drawdown_and_gain()
    update_order_details(log_file, unique_order_id, lowest_bid=additional_details['lowest_bid'], max_drawdown=additional_details['max_drawdown'], highest_bid=additional_details['highest_bid'], max_gain=additional_details['max_gain'])
    
    #simulating function being called in calculate_profit_percentage()
    update_order_details(log_file, unique_order_id, avg_sold_bid=additional_details['avg_sold_bid'], total_profit=additional_details['total_profit'], total_percentage=additional_details['total_percentage'])
    
    #simulating function being called in sell_rest_of_active_order()
    update_order_details(log_file, unique_order_id, time_exited=additional_details['time_exited'])

    #the point of there being 3 of the same function to see if it still works when being called in different places
if __name__ == "__main__":
    main()
