# rule_manager.py; when we are notified of a entry it handles checks and balances before getting into an order
from data_acquisition import indent, read_config, add_candle_type_to_json, log_order_details, load_json_df
from shared_state import indent, print_log
from economic_calender_scraper import check_order_time_to_event_time
from sim_order_handler import start_sim_order, order_active
from datetime import datetime
from buy_option import buy_option_cp
from order_utils import get_tp_value

STRATEGY_NAME = "FLAG/ZONE STRAT"

async def handle_rules_and_order(indent_lvl, candle, candle_zone_type, zones, completed_flags, sim_env_active=False, session=None, headers=None, print_statements=True):
    if print_statements:
        print_log(f"{indent(indent_lvl)}[HRAO] Handle Rules And Order: {completed_flags}")

    # Above 200 ema, calls; below, puts
    last_emas = get_last_emas(indent_lvl+1, print_statements)
    action = "call" if candle['close'] > last_emas['200'] else "put"
    
    # Check if trade time is aligned with economic events
    time_result = check_order_time_to_event_time(read_config('MINS_BEFORE_MAJOR_NEWS_ORDER_CANCELATION'), sim_active=sim_env_active)
    if print_statements:
        print_log(f"{indent(indent_lvl)}[HRAO] ECOM NEWS CONDITION: {time_result}")
    if not time_result:
        return [False, "Ecom News Event Soon."]
    
    # Check flag types: if only bear flags completed, only puts are valid; if only bull flags, only calls
    if completed_flags:
        bull_flags = [f for f in completed_flags if "_flag_bull_" in f.lower()]
        bear_flags = [f for f in completed_flags if "_flag_bear_" in f.lower()]

        if action == "call" and bear_flags and not bull_flags:
            if print_statements:
                print_log(f"{indent(indent_lvl)}[HRAO BLOCKED] Bear flags completed → Blocking CALL signal.")
            return [False, "Bear flags completed → Blocking CALL signal."]
        elif action == "put" and bull_flags and not bear_flags:
            if print_statements:
                print_log(f"{indent(indent_lvl)}[HRAO BLOCKED] Bull flags completed → Blocking PUT signal.")
            return [False, "Bull flags completed → Blocking PUT signal."]

    if print_statements:
        print_log(f"{indent(indent_lvl)}[HRAO ORDER CONFIRMED] Buy Signal ({action.upper()})")
    
    TP_value = get_tp_value(indent_lvl+1, candle_zone_type, action, zones)
    
    if sim_env_active:
        quantity, entry_bid_price, strike_price = None, None, None # mainly meant for paper/real trading, not trying to raise error
        if not order_active(indent_lvl):
            await start_sim_order(candle, candle['close'], candle_zone_type, TP_value, action)    
        else:
            if print_statements:
                print_log(f"{indent(indent_lvl)}[HRAO ORDER] Canceled, active order already in play...")
            return [False, "Active order already in play..."]
    else: # Real/paper, not-sim order...
        success, strike_price, quantity, entry_bid_price, order_cost, error_message = await buy_option_cp(read_config('REAL_MONEY_ACTIVATED'), read_config('SYMBOL'), action, TP_value, session, headers, STRATEGY_NAME)
        if success: 
            # Log order details
            add_candle_type_to_json(candle_zone_type)
            time_entered_into_trade = datetime.now().strftime("%m/%d/%Y-%I:%M %p") # Convert to ISO format string
            line_degree_angle_NONE = None
            log_order_details('order_log.csv', candle_zone_type, time_entered_into_trade, None, None, line_degree_angle_NONE, read_config('SYMBOL'), strike_price, action, quantity, entry_bid_price, order_cost)
        else: #incase order was canceled because of another active
            if print_statements:
                print_log(f"{indent(indent_lvl)}[HRAO ORDER FAIL] Buy Signal ({action.upper()}), ZONE = {candle_zone_type}")
            return [False, error_message]
    return [True, action, quantity, entry_bid_price, strike_price]

def get_last_emas(indent_lvl, print_statements=True):
    EMAs = load_json_df('EMAs.json')
    if EMAs.empty:
        if print_statements:
            print_log(f"{indent(indent_lvl)}[GET-EMAs] ERROR: data is unavailable.")
        return None
    last_EMA = EMAs.iloc[-1]
    emas = last_EMA.to_dict()
    if print_statements:
        print_log(f"{indent(indent_lvl)}[GET-EMAs] x: {emas['x']}, 13: {emas['13']:.2f}, 48: {emas['48']:.2f}, 200: {emas['200']:.2f}")
    return emas
