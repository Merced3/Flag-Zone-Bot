# sentiment_engine.py; use specific indicators in a ranking/weighted system to...
from data_acquisition import load_json_df
from shared_state import price_lock, indent, print_log, safe_read_json, safe_write_json

# ----------------------
# 🎯 Sentiment Ranking System (OFFLINE REFERENCE)
# ----------------------
# Structure (HH/HL/LH/LL):       +2 / -2
# EMA Crosses:
#    13 > 48 EMA                = +1
#    13 < 48 EMA                = -1
#    13 > 200 EMA               = +2
#    13 < 200 EMA               = -2
#    48 > 200 EMA               = +3
#    48 < 200 EMA               = -3
#
# Candle close above/below EMA:
#    > 13 EMA                  = +1
#    > 48 EMA                  = +2
#    > 200 EMA                 = +3
#    < 13 EMA                  = -1
#    < 48 EMA                  = -2
#    < 200 EMA                 = -3
#
# Zone interactions:
#    Breakout above zone       = +3
#    Breakdown below zone      = -3
#    Inside zone               = 0 or Neutral (slight decay)
#
# TPL interactions:
#    Close above TPL           = +2
#    Close below TPL           = -2
#    Tap from below (no close) = -1
#    Tap from above (no close) = +1
# ----------------------

# ----------------------
# Understanding the Sentiment Score Scale
# ----------------------
# +5 or more  |  Strong bullish alignment — trend likely to continue
# +4 to +1    |  Mild bullish — possibly early trend or healthy pullback
# 0           |  Neutral / Unclear — no strong bias in either direction
# -1 to -4    |  Mild bearish — warning zone, potential reversal forming
# -5 or lower | Strong bearish alignment — likely that bullish thesis is invalidated
# ----------------------
# Rule becomes: Exit only if sentiment shifts
# Example: exit CALL if score <= -3, exit PUT is score >= +3.
# This confirms a full sentiment reversal (not just a pullback)

def get_current_sentiment(candle, zones, tp_lines, log_indent, print_statements=True):
    total_score = 0
    if print_statements:
        print_log(f"\n{indent(log_indent)}[SENTIMENT] Evaluating candle sentiment...\n")

    # 1️⃣ --- EMA-Based Sentiment
    ema_values = get_last_emas(log_indent+1, print_statements)
    if ema_values:
        total_score += evaluate_ema_crosses(ema_values, log_indent+1, print_statements)
        total_score += evaluate_candle_vs_emas(candle, ema_values, log_indent+1, print_statements)

    # 2️⃣ --- Zone-Based Sentiment
    total_score += evaluate_zone_interaction(candle, zones, log_indent+1, print_statements)

    # 3️⃣ --- TPL-Based Sentiment
    total_score += evaluate_tpl_interaction(candle, tp_lines, log_indent+1, print_statements)

    # 🔁 Add trend structure (HH/HL/LH/LL) in the future here.

    if print_statements:
        print_log(f"{indent(log_indent)}[SENTIMENT] Total Score: {total_score}\n")

    return total_score

# ----------------------
# 🛠️ Utility & Helper Functions
# ----------------------

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

def evaluate_ema_crosses(emas, indent_lvl, print_statements=True):
    score = 0
    if emas['13'] > emas['48']:
        score += 1
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 13 > 48 → +1")
    elif emas['13'] < emas['48']:
        score -= 1
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 13 < 48 → -1")

    if emas['13'] > emas['200']:
        score += 2
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 13 > 200 → +2")
    elif emas['13'] < emas['200']:
        score -= 2
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 13 < 200 → -2")

    if emas['48'] > emas['200']:
        score += 3
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 48 > 200 → +3")
    elif emas['48'] < emas['200']:
        score -= 3
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA] 48 < 200 → -3")

    return score

def evaluate_candle_vs_emas(candle, emas, indent_lvl, print_statements=True):
    score = 0
    close = candle['close']
    if close > emas['13']:
        score += 1
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close > 13 EMA → +1")
    else:
        score -= 1
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close < 13 EMA → -1")

    if close > emas['48']:
        score += 2
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close > 48 EMA → +2")
    else:
        score -= 2
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close < 48 EMA → -2")

    if close > emas['200']:
        score += 3
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close > 200 EMA → +3")
    else:
        score -= 3
        if print_statements:
            print_log(f"{indent(indent_lvl)}[EMA-CANDLE] Close < 200 EMA → -3")

    return score

def evaluate_zone_interaction(candle, zones, indent_lvl, print_statements=True):
    score = 0
    c_open, c_close, c_high, c_low = candle['open'], candle['close'], candle['high'], candle['low']

    for name, (_, zone_IV, zone_buffer) in zones.items():
        zone_top = zone_IV if zone_IV > zone_buffer else zone_buffer
        zone_bottom = zone_IV if zone_IV < zone_buffer else zone_buffer
        in_zone = zone_top >= c_close >= zone_bottom

        if in_zone:
            if print_statements:
                print_log(f"{indent(indent_lvl)}[ZONE] Inside zone '{name}' → 0")
            return 0  # Neutral (only check one zone for now)

        if c_open < zone_top and c_close > zone_top:
            score += 3
            if print_statements:
                print_log(f"{indent(indent_lvl)}[ZONE] Breakout above '{name}' → +3")
            return score

        if c_open > zone_bottom and c_close < zone_bottom:
            score -= 3
            if print_statements:
                print_log(f"{indent(indent_lvl)}[ZONE] Breakdown below '{name}' → -3")
            return score

    return score

def evaluate_tpl_interaction(candle, tp_lines, indent_lvl, print_statements=True):
    score = 0
    open, close, high, low = candle['open'], candle['close'], candle['high'], candle['low']

    for _, (_, tpl_value) in tp_lines.items():
        if open < tpl_value < close:
            score += 2
            if print_statements:
                print_log(f"{indent(indent_lvl)}[TPL] Closed above TPL ({tpl_value}) → +2")
        elif open > tpl_value > close:
            score -= 2
            if print_statements:
                print_log(f"{indent(indent_lvl)}[TPL] Closed below TPL ({tpl_value}) → -2")
        elif high >= tpl_value > close:
            score -= 1
            if print_statements:
                print_log(f"{indent(indent_lvl)}[TPL] Tapped from below and rejected ({tpl_value}) → -1")
        elif low <= tpl_value < close:
            score += 1
            if print_statements:
                print_log(f"{indent(indent_lvl)}[TPL] Tapped from above and held ({tpl_value}) → +1")

    return score

