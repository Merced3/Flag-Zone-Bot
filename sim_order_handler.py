# sim_order_handler.py, this is responsible for order's while the simulator is running to see if its performance is as expected.
import os
from shared_state import indent, print_log
from calculate_avg_trim_distance import get_avg_trim_from_folder
from data_acquisition import read_config, add_markers, add_candle_type_to_json, is_ema_broke, get_current_candle_index

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
LOG_FILE_PATH = os.path.join(LOGS_DIR, f"{read_config('SYMBOL')}_{read_config('TIMEFRAMES')[0]}.log")

global sim_order_details
sim_order_details = {
    "call_or_put": None,
    "buy_entry_price": None,
    "current_order_active": False,
    "TP_value": None,
    "trim_flag_1": False,
    "trim_flag_2": False,
    "trim_flag_3": False
}

global global_trims
global_trims = {
    'average': None, 
    'minimum': None, 
    'maximum': None
}

async def reset_sim_order_state():
    global sim_order_details
    sim_order_details = {
        "call_or_put": None,
        "buy_entry_price": None,
        "current_order_active": False,
        "TP_value": None,
        "trim_flag_1": False,
        "trim_flag_2": False,
        "trim_flag_3": False
    }

async def start_sim_order(candle, entry_price, candle_zone_type, TP_values, action):
    global sim_order_details
    #print_log(f"[SIM_ORDER] New sim order started: {sim_order_details}")

    sim_order_details["current_order_active"] = True
    sim_order_details["buy_entry_price"] = entry_price
    sim_order_details["call_or_put"] = action
    sim_order_details["TP_value"] = TP_values # When we get into order we set where we think price will go

    add_candle_type_to_json(candle_zone_type)
    await add_markers("buy", y=candle['close'], percentage=0)

def order_active(indent_lvl):
    global sim_order_details
    return sim_order_details["current_order_active"]

def set_trims(folder_name):
    global_trims = get_avg_trim_from_folder(folder_name)
    print_log(f"global_trims:\n{global_trims}")

async def manage_sim_order(indent_lvl, candle, sentiment_score, print_statements=True):
    global sim_order_details
    global global_trims

    if global_trims['average'] and global_trims['minimum'] and global_trims['maximum']:
        lowest_trim_possibility = global_trims['minimum']
        avg_trim_possibility = global_trims['average']
        guaranteed_trim_win = global_trims['maximum']
        if print_statements:
            print_log(f"{indent(indent_lvl)}[SIM_ORDER] Using same days trims")
    else:
        lowest_trim_possibility = 0.02
        avg_trim_possibility = 0.4429
        guaranteed_trim_win = 0.94
        if print_statements:
            print_log(f"{indent(indent_lvl)}[SIM_ORDER] Using AVG trims from cumalitive Days")

    # Extract order details from the dictionary
    current_candle_price = candle['high'] if sim_order_details["call_or_put"] == "call" else candle['low']
    #price_difference = abs(current_candle_price - sim_order_details["buy_entry_price"])
    
    if print_statements:
        print_log(f"{indent(indent_lvl)}[SIM_ORDER] current price: {current_candle_price}")
    
    trim_level1 = sim_order_details["buy_entry_price"] + lowest_trim_possibility if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - lowest_trim_possibility
    trim_level2 = sim_order_details["buy_entry_price"] + avg_trim_possibility if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - avg_trim_possibility
    trim_level3 = sim_order_details["buy_entry_price"] + guaranteed_trim_win if sim_order_details["call_or_put"] == "call" else sim_order_details["buy_entry_price"] - guaranteed_trim_win
    if print_statements:
        print_log(f"{indent(indent_lvl)}[SIM_ORDER] Trim Levels: {trim_level1}, {trim_level2}, {trim_level3}")
    x =  get_current_candle_index(LOG_FILE_PATH) -1
    
    # **Check trim and sell conditions**
    #if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level1) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level1)) and not sim_order_details["trim_flag_1"]:
        #y = trim_level1
        #await add_markers("sim_trim_lwst", x=x, y=y, percentage=20)
        #sim_order_details["trim_flag_1"] = True

    if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level2) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level2)) and not sim_order_details["trim_flag_2"]:
        y = trim_level2
        await add_markers("sim_trim_avg", x=x, y=y, percentage=20)
        sim_order_details["trim_flag_2"] = True
    
    if ((sim_order_details["call_or_put"] == "call" and current_candle_price >= trim_level3) or (sim_order_details["call_or_put"] == "put" and current_candle_price <= trim_level3)) and not sim_order_details["trim_flag_3"]:
        y = trim_level3
        await add_markers("sim_trim_win", x=x, y=y, percentage=20)
        sim_order_details["trim_flag_3"] = True
    
    # Stop Loss hander
    y = candle['close']
    await SL_sentiment(indent_lvl+1, x, y, sim_order_details["call_or_put"], sentiment_score, 2, print_statements)

    # Take profit Hander
    await TP_zone(indent_lvl+1, x, candle, sim_order_details["TP_value"], print_statements)


async def TP_zone(indent_lvl, x, candle, TP_value, print_statements):
    if TP_value is None:
        return  # Nothing to do
    # Check if candle interacted with a zone. Both call and put
    hit_TP = candle["high"] >= TP_value >= candle["low"]
    if hit_TP:
        await sell_sim_order(x, TP_value) # Add marker at zone line
        if print_statements:
            print_log(f"{indent(indent_lvl)}[SIM_ORDER Take Profit] RESET Sim-Order")

# sentiment stoploss handler
async def SL_sentiment(indent_lvl, x, y, position_type, sentiment_score, sentiment_score_threshold, print_statements):
    if (position_type == "call" and sentiment_score <= -sentiment_score_threshold) or (position_type == "put" and sentiment_score >= sentiment_score_threshold):
        await sell_sim_order(x, y)
        if print_statements:
            print_log(f"{indent(indent_lvl)}[SIM_ORDER Sentiment SL] RESET Sim-Order")

# 13 ema stoploss handler
#sim_order_details = await SL_13ema(indent_lvl+1, x, y, sim_order_details["call_or_put"], print_statements)
async def SL_13ema(indent_lvl, x, y, cp, print_statements):
    # Check if EMA is broken to determine if the order should be sold
    if is_ema_broke("13", read_config('SYMBOL'), "2M", cp):
        await sell_sim_order(x, y)
        if print_statements:
            print_log(f"{indent(indent_lvl)}[SIM_ORDER 13ema SL] RESET Sim-Order")

async def sell_sim_order(x, y):
    # When we don't include X it has a contingincy in the function to grab/find it it's self
    await add_markers("sell", x=x, y=y, percentage=20)
    # Reset order state
    await reset_sim_order_state()