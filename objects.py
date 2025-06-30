# objects.py
import pandas as pd
from shared_state import print_log, safe_read_json, safe_write_json
from data_acquisition import get_dates, get_certain_candle_data
import cred
import asyncio
from utils.log_utils import read_log_to_df
from utils.json_utils import read_config
from paths import OBJECTS_PATH, TIMELINE_PATH, CANDLE_LOGS, SPY_15_MINUTE_CANDLES_PATH

# What zones mean:
# 🔁 Support = “Too few sellers to push lower”
# 🔁 Resistance = “Too few buyers to push higher”

_display_cache = {"current": 0, "objects": []}  # Global cache to track current step & objects

# ───🔹 CORE UPDATE LOOP ───────────────────────────────────────────────────

def update_timeline_with_objects(display=False):
    """
    Backend-driven level generation that replaces old levels within a new day's range.
    """
    try:
        df = pd.read_csv(SPY_15_MINUTE_CANDLES_PATH, parse_dates=["timestamp"], index_col="timestamp")
        df.sort_index(inplace=True)
    except Exception as e:
        print_log(f"[ERROR] Failed to load CSV: {e}")
        return

    unique_days = sorted(df.index.normalize().unique())
    global_offset = 0
    all_lvl_objects = []
    all_zone_objects = []

    recent_ranges = []
    #limit_days = 20
    #for i, current_day in enumerate(unique_days[:limit_days]):#for current_day in unique_days:
    for current_day in unique_days:
        day_data = df[df.index.normalize() == current_day]
        if day_data.empty:
            continue

        # Making list of day ranges, to see if were the day were dealing with is bigger than avg.
        day_range = day_data["high"].max() - day_data["low"].min()
        recent_ranges.append(day_range)

        # Getting day HIGH and LOW levels
        info = read_day_candles_and_distribute(day_data, current_day, global_offset)
        new_levels = get_levels(info['high_pos'], info['low_pos'])
        print_log(f"\n[{current_day.date()} (id, lvl)] {new_levels[0]['type']}: ({new_levels[0]['id']}, {new_levels[0]['y']}) | {new_levels[1]['type']}: ({new_levels[1]['id']}, {new_levels[1]['y']})")
        get_structures(info['structures'], False) # Set to false to save num of objects to display
        zone_objects_to_remove, lvl_objects_to_remove = validate_intraday_zones_lvls(all_zone_objects, all_lvl_objects, new_levels)
        today_zone_objects = build_zones(new_levels, info['structures'], day_range, info['starter_zone_data'])
        
        # Remove invalid zones and levels
        if zone_objects_to_remove:
            all_zone_objects = [obj for obj in all_zone_objects if obj['id'] not in {z['id'] for z in zone_objects_to_remove}]
        if lvl_objects_to_remove:
            all_lvl_objects = [obj for obj in all_lvl_objects if obj['id'] not in {l['id'] for l in lvl_objects_to_remove}]

        # Adding objects to global lists
        all_zone_objects.extend(today_zone_objects)
        all_lvl_objects.extend(new_levels)

        # Daily Range size comparison
        avg_range = sum(recent_ranges[-3:]) / min(len(recent_ranges), 3)  # 3-day rolling avg
        if day_range > avg_range * 1.15:  # Arbitrary threshold
            print_log(f"[{current_day.date()}] Large range detected: {day_range:.2f} vs avg {avg_range:.2f}")

        # Add offset for next days run
        global_offset += len(day_data)
    print_log(f"\n")

    # Final output
    if display:
        final_objects = all_lvl_objects + all_zone_objects
        write_to_display(final_objects, mode='replace')

def read_day_candles_and_distribute(candle_data, current_date, global_offset=0, rolling_window=3):
    """
    Reads all candles ONCE and distributes data to all downstream functions 
    like get_levels(), get_structures(), etc. This optimizes performance and 
    ensures consistent offset-adjusted indexing.
    """

    # === Filter for Current Day ===
    day_data = candle_data[candle_data.index.normalize() == current_date]
    if day_data.empty:
        return []
    
    # === High & Low of Day (Levels) ===
    high_y = day_data["high"].max()
    low_y = day_data["low"].min()
    high_idx = day_data["high"].idxmax()
    low_idx = day_data["low"].idxmin()
    high_x = candle_data.index.get_loc(high_idx) + global_offset
    low_x = candle_data.index.get_loc(low_idx) + global_offset

    # === Body Tops & Bottoms (for swing detection) ===
    bodies_top = day_data[['open', 'close']].max(axis=1).tolist()
    bodies_bot = day_data[['open', 'close']].min(axis=1).tolist()

    swing_highs = []
    swing_lows = []

    for i in range(rolling_window, len(day_data) - rolling_window):
        is_swing_high = all(
            bodies_top[i] > bodies_top[i - j] and bodies_top[i] > bodies_top[i + j]
            for j in range(1, rolling_window + 1)
        )
        is_swing_low = all(
            bodies_bot[i] < bodies_bot[i - j] and bodies_bot[i] < bodies_bot[i + j]
            for j in range(1, rolling_window + 1)
        )
        if is_swing_high:
            swing_highs.append((i + global_offset, bodies_top[i]))
        if is_swing_low:
            swing_lows.append((i + global_offset, bodies_bot[i]))

    # === Close Trend Line ===
    closes = day_data["close"].tolist()
    trend_line = [
        (global_offset, closes[0]),
        (global_offset + len(closes) - 1, closes[-1])
    ]

    # === Candle Body Tops/Bottoms for Starter Zone Logic ===
    wick_ranges = []
    body_positions = []
    hbc = [None, None]  # Highest Bottom Candle (X, Y)
    ltc = [None, None]  # Lowest Top Candle (X, Y)

    for local_index, (_, candle) in enumerate(day_data.iterrows()):
        c_global_index = local_index + global_offset
        body_top = max(candle.open, candle.close)
        body_bot = min(candle.open, candle.close)

        # Save all body pairs
        body_positions.append((c_global_index, body_top, body_bot))

        # Save for wick-based structure detection
        wick_ranges.append({
            "top": body_top,
            "bottom": body_bot,
            "high": candle.high,
            "low": candle.low,
        })
        
        # Update HBC
        if hbc[1] is None or body_bot > hbc[1]:
            hbc = [c_global_index, body_bot]

        # Update LTC
        if ltc[1] is None or body_top < ltc[1]:
            ltc = [c_global_index, body_top]
    
    return {
        "high_pos": [high_x, high_y],
        "low_pos": [low_x, low_y],
        "structures": {
            "swings_high": swing_highs,
            "swings_low": swing_lows,
            "trendline": trend_line,
        },
        "wick_ranges": wick_ranges,
        "starter_zone_data": {
            "body_candle_positions": body_positions,
            "hbc": hbc,
            "ltc": ltc
        },
        "raw_day_data": day_data.reset_index(drop=False),  # IDK what the purpose of this is.
    }

# ───🔹 STRUCTURE + LEVEL GENERATION ──────────────────────────────────────

def get_structures(structures, save_to_steps=False):
    
    if save_to_steps:
        # Obtaining and ID for this object
        timeline = safe_read_json(TIMELINE_PATH, default={})
        serial = 1
        if timeline:
            last_objects = [obj for step in timeline.values() for obj in step.get("objects",[])]
            if last_objects:
                serial = max(int(obj["id"]) for obj in last_objects) + 1

        # Save to timeline as "structure" action
        structure_objects = []
        for s_type, points in structures.items():
            if not points:
                continue
            structure_objects.append({
                "id": f"{serial:05d}",
                "type": "structure",
                "subtype": s_type,
                "points": points  # list of (x, y)
            })
            serial+=1

        add_timeline_step(structure_objects, action="create", reason="Extracted basic structure (swings, trend)")

def get_levels(high_pos, low_pos):
    # Create two level objects
    levels = [
        {"type": "resistance", "left": high_pos[0], "y": high_pos[1]},
        {"type": "support", "left": low_pos[0], "y": low_pos[1]}
    ]
    levels = create_level_objects(levels)

    add_timeline_step(levels, "create", "Logged raw daily high/low levels")
    return levels

def create_level_objects(levels):
    timeline = safe_read_json(TIMELINE_PATH, default={})
    serial = 1
    if timeline:
        last_objects = [obj for step in timeline.values() for obj in step.get("objects", [])]
        if last_objects:
            serial = max(int(obj["id"]) for obj in last_objects if obj["id"].isdigit()) + 1

    # Handle single dictionary
    if isinstance(levels, dict):
        levels = [levels]

    # Defensive: not a list of dicts = crash early
    if not isinstance(levels, list) or not all(isinstance(lvl, dict) for lvl in levels):
        raise ValueError("`levels` must be a dict or a list of dicts")

    lvl_list = []
    for lvl in levels:
        lvl_obj = {
            "id": f"{serial:05d}",
            "type": lvl["type"],
            "left": lvl["left"],
            "y": lvl["y"],
        }
        serial += 1
        lvl_list.append(lvl_obj)

    # Return single object if input was a dict
    return lvl_list[0] if len(lvl_list) == 1 else lvl_list

# ───🔹 ZONE GENERATION & VALIDATION ──────────────────────────────────────

def build_zones(new_levels, structures, day_range, starter_zone_data):
    zones = []

    resistance_level_y = next((lvl['y'] for lvl in new_levels if 'resistance' in lvl['type']), None)
    support_level_y = next((lvl['y'] for lvl in new_levels if 'support' in lvl['type']), None)

    hbc = starter_zone_data["hbc"] # Highest Bottom Candle, either min('open' or 'close'), but its the highest out of them all, formated (X, Y)
    ltc = starter_zone_data["ltc"] # Lowest Top Candle, either max('open' or 'close'), but its the lowest one out of them all, formated (X, Y)
    body_top_bottom_pairs = starter_zone_data["body_candle_positions"]

    # Fill top/bottom arrays
    all_c_body_tops = [(x, top) for x, top, _ in body_top_bottom_pairs]
    all_c_body_bottoms = [(x, bot) for x, _, bot in body_top_bottom_pairs]

    # NOW filter
    filtered_top_bodies = [(x, y) for x, y in all_c_body_tops if y > hbc[1]] # if candle in list isn't above the highest bottom body candle value, remove it.
    filtered_top_bodies.append(hbc) # Optional
    filtered_bottom_bodies = [(x, y) for x, y in all_c_body_bottoms if y < ltc[1]] # if candle in list isn't below the lowest top body candle value, remove it.
    filtered_bottom_bodies.append(ltc) # Optional

    RB_XY = None # Resistance Bottom (X, Y)
    ST_XY = None # Support Top (X, Y)
    percent_threshold = [0.06, 0.30] # aka 6% and 30%
    r_message = None
    s_message = None

    # RESISTANCE
    if structures["swings_high"]: # 'structural' mode
        RB_XY = max(structures['swings_high'], key=lambda x: x[1]) # current highest anchor
        anchor_level_dist_ratio = abs(RB_XY[1] - resistance_level_y) / day_range
        
        if not (percent_threshold[0] <= anchor_level_dist_ratio <= percent_threshold[1]): # 'body based' mode, Just incase: or highest_body_top[1] > RB_XY[1]
            RB_XY = min(filtered_top_bodies, key=lambda x: x[1]) if filtered_top_bodies else hbc
            r_message = f"Body-Based Mode: {RB_XY} (SVF) Size: {anchor_level_dist_ratio:.3f}" # SVF = Switched, Validation Failed
        else:
            r_message = f"Structural Mode: {RB_XY} | Size: {anchor_level_dist_ratio:.3f}"
    elif not structures["swings_high"]: # 'body based' mode
        RB_XY = min(filtered_top_bodies, key=lambda x: x[1]) if filtered_top_bodies else hbc
        r_message = f"Body Based Mode: {RB_XY}"
    print_log(f"[RESISTANCE ZONE BOTTOM] {r_message}")
    
    # SUPPORT
    if structures["swings_low"]: # 'structural' mode
        ST_XY = min(structures["swings_low"], key=lambda x: x[1])
        anchor_level_dist_ratio = abs(ST_XY[1] - support_level_y) / day_range
        
        if not (percent_threshold[0] <= anchor_level_dist_ratio <= percent_threshold[1]): # 'body based' mode, Just incase:  or lowest_body_bot[1] < ST_XY[1]
            ST_XY = max(filtered_bottom_bodies, key=lambda x: x[1]) if filtered_bottom_bodies else ltc
            s_message = f"Body-Based Mode: {ST_XY} (SVF) Size: {anchor_level_dist_ratio:.3f}" # SVF = Switched, Validation Failed
        else:
            s_message = f"Structural Mode: {ST_XY} | Size: {anchor_level_dist_ratio:.3f}"
    elif not structures["swings_low"]: # 'body based' mode
        ST_XY = max(filtered_bottom_bodies, key=lambda x: x[1]) if filtered_bottom_bodies else ltc
        s_message = f"Body Based Mode: {ST_XY}"
    print_log(f"[   SUPPORT ZONE TOP   ] {s_message}") # spaces are to match up with the '[RESISTANCE ZONE BOTTOM]' looks better in terminal
        
    # Create Zones
    for lvl in new_levels:
        candle_zone_index = ST_XY[0] if "support" in lvl['type'] else RB_XY[0]
        candle_top_or_bottom = ST_XY[1] if "support" in lvl['type'] else RB_XY[1]
        zones.append({
            "type": lvl['type'],
            "left": min(lvl["left"], candle_zone_index),
            "top": lvl["y"] if "resistance" in lvl['type'] else candle_top_or_bottom,
            "bottom": lvl["y"] if "support" in lvl['type'] else candle_top_or_bottom,
        })

    zone_objects = create_zone_objects(zones)
    add_timeline_step(zone_objects, "create", "Created zone from wick ranges + daily high/low")

    return zone_objects

def create_zone_objects(zones):
    """Returns a object list with appended zones, works weather you have one zone or muliple"""
    timeline = safe_read_json(TIMELINE_PATH, default={})
    serial = 1
    if timeline:
        last_objects = [obj for step in timeline.values() for obj in step.get("objects",[])]
        if last_objects:
            serial = max(int(obj["id"]) for obj in last_objects) + 1
    
    object_list = []
    for zone in zones:
        entry = {
            "id": f"{serial:05d}",
            "type": zone["type"],
            "left": zone["left"],
            "top": zone["top"],
            "bottom": zone["bottom"]
        }
        serial += 1
        object_list.append(entry)
    return object_list

def validate_intraday_zones_lvls(all_zones, all_lvls, new_levels):
    delete_ids = []
    delete_id_set = set()
    log_origin = "VIZL" # Validate Intraday Zones Levels
    
    print_log(f"[{log_origin}] Starting with {len(all_zones)} zones and {len(all_lvls)} levels")

    if not new_levels:
        print_log(f"[{log_origin}] No new levels provided — skipping validation.")
        return [], []

    level_high = max(lvl['y'] for lvl in new_levels if lvl['type'] == 'resistance')
    level_low = min(lvl['y'] for lvl in new_levels if lvl['type'] == 'support')
    
    # === ZONE VALIDATION ===
    for zone in all_zones:
        if zone['id'] in delete_id_set:
            continue
        z_top = float(zone.get('top', float('-inf')))
        z_bot = float(zone.get('bottom', float('inf')))

        # Entire day range inside zone
        if level_high <= z_top and level_low >= z_bot:
            delete_ids.append((zone['id'], "Zone Encompasses Day Range"))
            delete_id_set.add(zone['id'])

        # Zone fully inside new intraday range
        elif z_top <= level_high and z_bot >= level_low:
            delete_ids.append((zone['id'], "Zone Inbetween IntraDay"))
            delete_id_set.add(zone['id'])

        # Partial overlap
        elif (level_high >= z_top >= level_low) or (level_high >= z_bot >= level_low):
            delete_ids.append((zone['id'], "Zone Overlap's IntraDay"))
            delete_id_set.add(zone['id'])

    # === LEVEL VALIDATION ===
    for lvl in all_lvls:
        if lvl['id'] in delete_id_set:
            continue
        y = lvl["y"]
        if level_low <= y <= level_high:
            delete_ids.append((lvl["id"], "Level Inbetween IntraDay"))
            delete_id_set.add(lvl["id"])
    
    if delete_ids:
        log_object_removal(delete_ids, reason="Removed from `validate_intraday_zones()`")

    zones_to_remove = [z for z in all_zones if z['id'] in delete_id_set]
    lvls_to_remove = [l for l in all_lvls if l['id'] in delete_id_set]
    return zones_to_remove, lvls_to_remove  # ✅ Only the bad ones

# ───🔹 DISPLAY & TIMELINE MANAGEMENT ─────────────────────────────────────

def add_timeline_step(objects, action, reason, path=TIMELINE_PATH):
    timeline = safe_read_json(path, default={})
    step_key = str(max(map(int, timeline.keys()), default=0) + 1)

    timeline[step_key] = {
        "objects": objects,
        "action": action,
        "reason": reason
    }

    safe_write_json(path, timeline)

def write_to_display(objects, mode='append'):
    display_data = safe_read_json(OBJECTS_PATH, default=[])

    if mode == 'replace':
        display_data = objects
    else:  # append
        display_data.extend(objects)

    safe_write_json(OBJECTS_PATH, display_data)

def log_object_removal(object_ids_with_reason, reason="removal"):
    objects = [{"id": oid, "status": "removed", "individual_reason": why} for oid, why in object_ids_with_reason]
    add_timeline_step(objects, "remove", reason)

def display_json_update(step):
    timeline = safe_read_json(TIMELINE_PATH, default={})
    if not timeline:
        print_log("[display_update] Timeline is empty.")
        return

    if isinstance(step, str):
        if step == "all":
            step = max(map(int, timeline.keys()))
        else:
            print_log(f"[display_update] Unknown string step: '{step}'")
            return

    try:
        step = int(step)
    except ValueError:
        print_log(f"[display_update] Invalid step input: {step}")
        return

    # Use global cache to avoid full recomputation
    global _display_cache
    current_step = _display_cache["current"]
    display_objects = _display_cache["objects"]

    if step < current_step:
        # Rewind from scratch
        display_objects = []
        start_step = 1
    else:
        # Continue forward
        start_step = current_step + 1

    for i in range(start_step, step + 1):
        s = timeline.get(str(i), {})
        objs = s.get("objects", [])
        action = s.get("action", "create")

        if action == "create":
            for obj in objs:
                if "status" not in obj:
                    display_objects.append(obj)
        elif action == "remove":
            remove_ids = {obj["id"] for obj in objs if obj.get("status") == "removed"}
            display_objects = [o for o in display_objects if o.get("id") not in remove_ids]

    # Update cache and write
    _display_cache["current"] = step
    _display_cache["objects"] = display_objects
    safe_write_json(OBJECTS_PATH, display_objects)
    print_log(f"[display_update] Step set to {step}. {len(display_objects)} objects displayed.")

def get_final_timeline_step():
    timeline = safe_read_json(TIMELINE_PATH, default={})
    steps = sorted(map(int, timeline.keys()))
    return steps[-1] if steps else 0

# ───🔹 OTHER FUNCTIONS FOR EXTERIOR SCRIPT USE ─────────────────────────────────────

def clean_csv_timestamps():
    """
    One-time fix: ensures all timestamps are trimmed to '%Y-%m-%d %H:%M:%S'
    by removing any decimal microseconds, without dropping any rows.
    """
    try:
        df = pd.read_csv(SPY_15_MINUTE_CANDLES_PATH)

        if "timestamp" not in df.columns:
            print_log("[ERROR] 'timestamp' column not found in CSV.")
            return

        # Force timestamp column to string and trim anything after the first 19 characters
        df["timestamp"] = df["timestamp"].astype(str).str.slice(0, 19)

        # Save the cleaned version
        df.to_csv(SPY_15_MINUTE_CANDLES_PATH, index=False)
        print_log("[CLEAN] Timestamp strings trimmed to HH:MM:SS precision.")
    except Exception as e:
        print_log(f"[ERROR] Failed to clean CSV timestamps: {e}")

def get_objects():
    """
    Returns a tuple of (zones, levels) from the current objects display file.
    If the file is empty or improperly structured, returns two empty lists.
    """
    data = safe_read_json(OBJECTS_PATH, default=[])
    
    zones = []
    levels = []

    for obj in data:
        if "top" in obj and "bottom" in obj:
            zones.append(obj)
        elif "y" in obj and "left" in obj:
            levels.append(obj)

    return zones, levels

def process_end_of_day_15m_candles():
    """
    Processes the 15M candle log, updates the CSV, recalculates new levels/zones,
    updates objects.json and timeline.json, then clears the log.
    """
    
    try:
        df_log = read_log_to_df(CANDLE_LOGS.get("15M"))
    except Exception as e:
        print_log(f"[ERROR] Couldn't load 15M log: {e}")
        return

    if df_log.empty:
        print_log("[INFO] 15M log was empty — skipping.")
        return

    # Clean & sort timestamps
    df_log["timestamp"] = pd.to_datetime(df_log["timestamp"].astype(str).str.slice(0, 19))
    df_log.sort_values("timestamp", inplace=True)
    df_log.set_index("timestamp", inplace=True)

    # Append today's data to the main CSV
    if SPY_15_MINUTE_CANDLES_PATH.exists():
        df_storage = pd.read_csv(SPY_15_MINUTE_CANDLES_PATH, parse_dates=["timestamp"])
        df_storage.set_index("timestamp", inplace=True)

        # ✅ Ensure index is datetime for both DataFrames before merging
        df_storage.index = pd.to_datetime(df_storage.index)
        combined_df = pd.concat([df_storage, df_log]).sort_index()
        combined_df.to_csv(SPY_15_MINUTE_CANDLES_PATH)
    else:
        df_log.to_csv(SPY_15_MINUTE_CANDLES_PATH)

    # Get today only
    current_day = df_log.index[0].normalize()
    day_data = df_log[df_log.index.normalize() == current_day]
    day_range = day_data["high"].max() - day_data["low"].min()
    global_offset = len(df_storage) if SPY_15_MINUTE_CANDLES_PATH.exists() else 0

    # Prep old objects
    all_zone_objects, all_lvl_objects = get_objects()

    # Run zone/level logic
    info = read_day_candles_and_distribute(day_data, current_day, global_offset)
    new_levels = get_levels(info["high_pos"], info["low_pos"])
    print_log(f"\n[{current_day.date()} (id, lvl)] {new_levels[0]['type']}: ({new_levels[0]['id']}, {new_levels[0]['y']}) | {new_levels[1]['type']}: ({new_levels[1]['id']}, {new_levels[1]['y']})")
    get_structures(info["structures"], False)

    # Validate and filter old objects
    zone_objs_to_remove, lvl_objs_to_remove = validate_intraday_zones_lvls(all_zone_objects, all_lvl_objects, new_levels)
    if zone_objs_to_remove:
        all_zone_objects = [z for z in all_zone_objects if z["id"] not in {r["id"] for r in zone_objs_to_remove}]
    if lvl_objs_to_remove:
        all_lvl_objects = [l for l in all_lvl_objects if l["id"] not in {r["id"] for r in lvl_objs_to_remove}]

    today_zone_objects = build_zones(new_levels, info["structures"], day_range, info["starter_zone_data"])

    # Display every from timeline file, too display file
    display_json_update("all")

    print_log(f"[NEW HISTORICAL DATA] objects saved timeline.json now sent to objects.json")

async def pull_and_replace_15m():
    """
    RUN 15 after market closed, because of current polygon subscription plan.

    The purpose of this is to run after 15 mins of market close so that, you the manual user
    can fix whatever days data incase, wifi or power goes out, its for when the live 15 min 
    data might be incorrect and we need some better accuracy. this is so that you remember.
    """
    start, end = get_dates(1, False, '2025-06-27') #  go back to this (1, True) after were done finishing the timeline/object upload
    df = await get_certain_candle_data(
        cred.POLYGON_API_KEY,
        read_config('SYMBOL'),
        15, "minute",
        start, end,
        None,  # Don't save to anything
        market_type="MARKET",
        indent_lvl=0
    )

    if df is None or df.empty:
        print_log("[pull_and_replace_15m] No data returned.")
        return

    # ✅ Only keep OCHL + the GOOD timestamp
    df['timestamp'] = df['timestamp'].dt.strftime("%Y-%m-%d %H:%M:%S")
    df = df[['timestamp', 'open', 'close', 'high', 'low']]
    df.sort_values("timestamp", inplace=True)
    df.set_index("timestamp", inplace=True)

    # ✅ Convert index BACK to datetime for proper merging
    df.index = pd.to_datetime(df.index)

    print_log(f"\n[Fallback] Cleaned Polygon 15M:\n{df}\n")
    
    # ✅ Load existing main CSV if it exists
    if SPY_15_MINUTE_CANDLES_PATH.exists():
        df_storage = pd.read_csv(SPY_15_MINUTE_CANDLES_PATH, parse_dates=["timestamp"])
        df_storage.set_index("timestamp", inplace=True)

        df_storage.index = pd.to_datetime(df_storage.index)
    else:
        df_storage = pd.DataFrame(columns=df.columns)

    # ✅ Remove any rows for this day from the old data (clean replacement!)
    current_day = df.index[0].normalize()
    #df_storage = df_storage[~df_storage.index.strftime('%Y-%m-%d').eq(current_day)] # Removed this b/c im not trying to filter out anymore, this is taking to long, im trying to just get WHOLE correct data, for now, i need to get this done so i can go to bed.
    
    # ✅ Merge clean replacement
    combined_df = pd.concat([df_storage, df]).sort_index()
    combined_df.to_csv(SPY_15_MINUTE_CANDLES_PATH)
    print_log(f"[pull_and_replace_15m] Main CSV updated with Polygon fallback.")

    # ✅ Now re-run the **zone/level logic**
    day_data = df
    day_range = day_data["high"].max() - day_data["low"].min()
    global_offset = len(df_storage)
    
    # Prep old objects
    all_zone_objects, all_lvl_objects = get_objects()

    # Run zone/level logic
    info = read_day_candles_and_distribute(day_data, current_day, global_offset)
    new_levels = get_levels(info["high_pos"], info["low_pos"])
    print_log(f"\n[{current_day.date()} (id, lvl)] {new_levels[0]['type']}: ({new_levels[0]['id']}, {new_levels[0]['y']}) | {new_levels[1]['type']}: ({new_levels[1]['id']}, {new_levels[1]['y']})")
    get_structures(info["structures"], False)

    # Validate and filter old objects
    zone_objs_to_remove, lvl_objs_to_remove = validate_intraday_zones_lvls(all_zone_objects, all_lvl_objects, new_levels)
    if zone_objs_to_remove:
        all_zone_objects = [z for z in all_zone_objects if z["id"] not in {r["id"] for r in zone_objs_to_remove}]
    if lvl_objs_to_remove:
        all_lvl_objects = [l for l in all_lvl_objects if l["id"] not in {r["id"] for r in lvl_objs_to_remove}]

    today_zone_objects = build_zones(new_levels, info["structures"], day_range, info["starter_zone_data"])

    # ✅ Finally: push it all to the display file
    display_json_update("all")
    print_log(f"[pull_and_replace_15m] Timeline + objects updated.")
    
def candle_zone_handler(candle, boxes):
    candle_zone_type = None
    is_in_zone = False
    close_price = candle['close']
    ext = ["PDH", "PDL", "Buffer"]# Extension for zones
    
    zone_ranges = []  # Store (box_name, box_bottom, box_top) tuples
    for box_name, (x_pos, high_low_of_day, buffer) in boxes.items(): 
        # Determine zone type
        zone_type = "support" if "support" in box_name else "resistance" if "resistance" in box_name else "PDHL"
        PDH_or_PDL = high_low_of_day  # PDH for resistance, PDL for support
        box_top = PDH_or_PDL if zone_type in ["resistance", "PDHL"] else buffer  # PDH or Buffer as top for resistance/PDHL
        box_bottom = buffer if zone_type in ["resistance", "PDHL"] else PDH_or_PDL  # Buffer as bottom for resistance/PDHL
        
        # Store the zone range for later analysis
        zone_ranges.append((box_name, box_top, box_bottom))

        # Check if the candle is outside of zone and which one's
        if box_bottom <= close_price <= box_top:
            candle_zone_type = f"inside {box_name}"
            is_in_zone = True
            break  # No need to check further if we found a zone containing the candle
        
    # If not inside a zone, check if it's between two zones, above all zones, or below all zones
    if not is_in_zone:
        # Sort zones from highest to lowest based on box_top
        #print_log(f"{indent(indent_lvl)}[CZH] BEFORE SORTING: {zone_ranges}")
        zone_ranges.sort(key=lambda x: x[1], reverse=True)
        #print_log(f"{indent(indent_lvl)}[CZH] AFTER SORTING: {zone_ranges}")

        # Identify zones the candle is between
        for i in range(len(zone_ranges) - 1):
            current_zone, current_top, current_bottom = zone_ranges[i]
            next_zone, next_top, next_bottom = zone_ranges[i + 1]
            
            if current_top > close_price > next_bottom:
                cz_ext = ext[1] if "support" in current_zone or "PDHL" in current_zone else ext[2]
                nz_ext = ext[0] if "resistance" in next_zone or "PDHL" in next_zone else ext[2]
                candle_zone_type = f"{current_zone} {cz_ext}---{next_zone} {nz_ext}"
                #break
            #else:
                #print_log(f"{indent(indent_lvl)} [CZH] Couldn't find 2 zones inbetween the candle close")

        # If no in-between zones were found, determine if it's above or below all zones
        if close_price < zone_ranges[-1][2]: # Below all zones
            lowest_zone_name = zone_ranges[-1][0]  # Get the name of the lowest zone
            extension = ext[1] if "support" in lowest_zone_name or "PDHL" in lowest_zone_name else ext[2]
            candle_zone_type = f"below {lowest_zone_name} {extension}"
        
        elif close_price > zone_ranges[0][1]: # Above all zones
            highest_zone_name = zone_ranges[0][0]  # Get the name of the highest zone
            extension = ext[0] if "resistance" in highest_zone_name or "PDHL" in highest_zone_name else ext[2]
            candle_zone_type = f"above {highest_zone_name} {extension}"

    return candle_zone_type, is_in_zone

if __name__ == "__main__":
    print("These functions below are just tests")
    #asyncio.run(pull_and_replace_15m())
    #clean_csv_timestamps()
    #update_timeline_with_objects(True)
    #process_end_of_day_15m_candles()