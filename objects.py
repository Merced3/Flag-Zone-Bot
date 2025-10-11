# objects.py
from typing import Optional
import pandas as pd
from shared_state import print_log
from data_acquisition import get_certain_candle_data
import cred
import asyncio
from datetime import datetime
from utils.data_utils import get_dates
from utils.log_utils import read_log_to_df
from utils.json_utils import read_config
from paths import pretty_path, TIMELINE_OBJECTS_DIR, SPY_15_MINUTE_CANDLES_PATH, DATA_DIR
from storage.objects.io import (      # Parquet-backed storage helpers
    append_timeline_events,
    upsert_current_objects,
    query_current_by_y_range,         # if you want to call from here/UI
    query_current_by_y_and_x,         # idem
    build_asof_snapshot_from_timeline,# idem
    load_current_objects
)
import pytz
from tools.compact_parquet import _last_global_index

# What zones mean:
# 🔁 Support = “Too few sellers to push lower”
# 🔁 Resistance = “Too few buyers to push higher”

_display_cache = {"current": 0, "objects": []}  # Global cache to track current step & objects

# ───🔸 CORE DAY PROCESSING ───────────────────────────────────────────────

def _process_one_day(day_df: pd.DataFrame,
                     day_ts: pd.Timestamp,
                     global_offset: int,
                     all_zone_objects: list,
                     all_lvl_objects: list) -> tuple[list, list]:
    """
    Process ONE trading day and update timeline/snapshot via add_timeline_step()
    using your existing primitives. Returns updated (all_zone_objects, all_lvl_objects).
    """
    if day_df.empty:
        return all_zone_objects, all_lvl_objects

    current_day = day_df.index[0].normalize()
    day_range = day_df["high"].max() - day_df["low"].min()

    info = read_day_candles_and_distribute(day_df, current_day, global_offset)
    new_levels = get_levels(info["high_pos"], info["low_pos"], ts=day_ts)
    print_log(f"\n[{current_day.date()} (id, lvl)] "
              f"{new_levels[0]['type']}: ({new_levels[0]['id']}, {new_levels[0]['y']}) | "
              f"{new_levels[1]['type']}: ({new_levels[1]['id']}, {new_levels[1]['y']})")

    # Structures -> timeline only (snapshot disabled in add_timeline_step call)
    get_structures(info['structures'], save_to_steps=False, ts=day_ts)

    # Validate previous objects against today's new levels
    zone_to_remove, lvl_to_remove = validate_intraday_zones_lvls(all_zone_objects, all_lvl_objects, new_levels, ts=day_ts)
    if zone_to_remove:
        keep = {z['id'] for z in zone_to_remove}
        all_zone_objects = [z for z in all_zone_objects if z['id'] not in keep]
    if lvl_to_remove:
        keep = {l['id'] for l in lvl_to_remove}
        all_lvl_objects = [l for l in all_lvl_objects if l['id'] not in keep]

    # Build today’s zones and append to global sets
    today_zones = build_zones(new_levels, info['structures'], day_range, info['starter_zone_data'], ts=day_ts)
    all_zone_objects.extend(today_zones)
    all_lvl_objects.extend(new_levels)

    return all_zone_objects, all_lvl_objects

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
        "raw_day_data": day_data.reset_index(drop=False),  # This is a 'just in case' thing.
    }

# ───🔸 TOP-LEVEL WORKFLOWS ───────────────────────────────────────────────

def update_timeline_with_objects(limit_days: Optional[int] = None,
                                 newest_first: bool = True):
    """
    Backfill objects by scanning 15m day parquet files.
    limit_days: if set, only process that many days.
      - newest_first=True  -> take the N most recent days
      - newest_first=False -> take the earliest N days
    """
    tf_dir = DATA_DIR / "15m"
    day_files = sorted(tf_dir.glob("*.parquet"), key=lambda p: p.stem)
    if not day_files:
        print_log("[ERROR] No 15m day Parquet files found.")
        return
    
    # limit which days we run
    if limit_days is not None and limit_days > 0:
        day_files = (day_files[-limit_days:] if newest_first else day_files[:limit_days])

    all_lvl_objects, all_zone_objects = [], []
    global_offset = 0

    for p in day_files:
        df_day = pd.read_parquet(
            p, columns=["ts","open","close","high","low","global_x"]
        ).sort_values("ts")

        # 🔧 Normalize ts (epoch ms OR ISO-with-tz → UTC pandas Timestamp)
        ts_col = df_day["ts"]
        if pd.api.types.is_integer_dtype(ts_col) or pd.api.types.is_float_dtype(ts_col):
            # epoch ms → UTC
            df_day["ts"] = pd.to_datetime(ts_col, unit="ms", utc=True)
        else:
            # strings / datetime-like → UTC
            df_day["ts"] = pd.to_datetime(ts_col, utc=True)

        # 🔧 The file name is the most robust source of the trading day
        day_str = p.stem                               # e.g. "2020-05-26"
        day_ts  = pd.to_datetime(day_str).tz_localize("UTC")

        # (optional) sanity if you like:
        # assert df_day["ts"].dt.normalize().nunique() == 1, "dayfile spans multiple days?"
        # Maybe, will keep it here just incase.
        
        # Make an index like your CSV path expects
        day_df = df_day.rename(columns={"ts": "timestamp"}).copy()
        day_df["timestamp"] = pd.to_datetime(day_df["timestamp"])
        day_df.set_index("timestamp", inplace=True)

        # Use the day’s real global start (fast, accurate)
        if "global_x" in df_day.columns and not df_day.empty:
            global_offset = int(df_day["global_x"].min())

        all_zone_objects, all_lvl_objects = _process_one_day(
            day_df, day_ts, global_offset, all_zone_objects, all_lvl_objects
        )

def process_end_of_day_15m_candles_for_objects() -> None:
    """
    Runs after end_of_day_compaction().
    Loads the latest 15m day Parquet, derives day_ts + global_offset,
    and processes exactly one trading day into timeline + current snapshot.
    """
    try:
        tf_dir = DATA_DIR / "15m"
        day_files = sorted(tf_dir.glob("*.parquet"), key=lambda p: p.stem)
        if not day_files:
            print_log("[EOD] No 15m day Parquet files found.")
            return

        latest_path = day_files[-1]                  # e.g. .../15m/2025-09-23.parquet
        day_str = latest_path.stem                   # "2025-09-23"
        day_ts  = pd.to_datetime(day_str).tz_localize("UTC")

        # Read only what we need; `global_x` gives us the exact global offset
        cols = ["ts", "open", "high", "low", "close", "global_x"]
        df_day = pd.read_parquet(latest_path, columns=cols).sort_values("ts")

        # Normalize ts → UTC pandas datetime (handles int64 ms or string ISO)
        ts_col = df_day["ts"]
        if pd.api.types.is_integer_dtype(ts_col) or pd.api.types.is_float_dtype(ts_col):
            df_day["ts"] = pd.to_datetime(ts_col, unit="ms", utc=True)
        else:
            df_day["ts"] = pd.to_datetime(ts_col, utc=True)

        # Index + shape expected by your downstream pipeline
        day_df = df_day.rename(columns={"ts": "timestamp"}).copy()
        day_df.set_index("timestamp", inplace=True)

        if day_df.empty:
            print_log("[EOD] Latest 15m dayfile is empty — skipping.")
            return

        # Use true global offset from the Parquet (added during compaction)
        if "global_x" in df_day.columns and not df_day.empty:
            global_offset = int(df_day["global_x"].min())
        else:
            # Fallback (shouldn’t normally happen after compaction)
            global_offset = 0
    
        # Load current snapshot → pass into one-day processor
        prev_zones, prev_lvls = get_objects()
        _process_one_day(day_df, day_ts, global_offset, prev_zones, prev_lvls)
        
        print_log(f"[EOD] Objects processed for {day_str} (offset={global_offset}).")
    except Exception as e:
        print_log(f"[EOD] Error: {e}")

# ───🔸 OBJECT GENERATION ─────────────────────────────────────────────────

def get_structures(structures, save_to_steps=False, ts=None):
    
    if save_to_steps:
        serial = _next_object_serial_from_parquet()

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

        add_timeline_step(structure_objects, "create", "Extracted basic structure (swings, trend)", ts=ts)

def get_levels(high_pos, low_pos, ts=None):
    # Create two level objects
    levels = [
        {"type": "resistance", "left": high_pos[0], "y": high_pos[1]},
        {"type": "support", "left": low_pos[0], "y": low_pos[1]}
    ]
    levels = create_level_objects(levels)

    add_timeline_step(levels, "create", "Logged raw daily high/low levels", ts=ts)
    return levels

def create_level_objects(levels):
    """Returns a object list (2) with appended levels. The levels are the highest high and lowest low of the day."""
    serial = _next_object_serial_from_parquet()

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

def build_zones(new_levels, structures, day_range, starter_zone_data, ts=None):
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
    percent_threshold = [0.06, 0.30] # aka 6% and 30%, possible overfitting but its fine.
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
    add_timeline_step(zone_objects, "create", "Created zone from wick ranges + daily high/low", ts=ts)

    return zone_objects

def create_zone_objects(zones):
    """Returns a object list with appended zones, works weather you have one zone or muliple"""
    
    serial = _next_object_serial_from_parquet()

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

def validate_intraday_zones_lvls(all_zones, all_lvls, new_levels, ts=None):
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
        log_object_removal(delete_ids, reason="Removed from `validate_intraday_zones()`", ts=ts)

    zones_to_remove = [z for z in all_zones if z['id'] in delete_id_set]
    lvls_to_remove = [l for l in all_lvls if l['id'] in delete_id_set]
    return zones_to_remove, lvls_to_remove  # ✅ Only the bad ones

# ───🔸 STORAGE BRIDGE (PARQUET) ──────────────────────────────────────────

def add_timeline_step(objects, action, reason, *, ts=None, write_snapshot=True):
    ts = pd.to_datetime(ts) if ts is not None else datetime.utcnow()

    # derive the trading day (UTC date or use market tz if you want)
    day_str = ts.strftime("%Y-%m-%d")

    # compute next day_step from that day's parquet only
    day_file = (TIMELINE_OBJECTS_DIR / day_str[:7] / f"{day_str}.parquet")
    if day_file.exists():
        try:
            last = pd.read_parquet(day_file, columns=["day_step"])["day_step"].max()
            day_step = int(last) + 1 if pd.notna(last) else 1
        except Exception:
            day_step = 1
    else:
        day_step = 1
        
    symbol = read_config('SYMBOL') # So that we don't have to read config a bunch of times.
    rows = []
    for obj in (objects if isinstance(objects, list) else [objects]):
        status = obj.get("status") or "active" if action == "create" else obj.get("status")
        rows.append({
            "day_step": day_step,
            "ts": ts,
            "action": action,
            "reason": reason,
            "object_id": obj.get("id"),
            "type": obj.get("type"),
            # Use your object’s x as global_x (or pass explicit global_x if you prefer)
            "global_x": obj.get("global_x", obj.get("left")),
            "left": obj.get("left"),
            "y": obj.get("y"),
            "top": obj.get("top"),
            "bottom": obj.get("bottom"),
            "status": status,
            "individual_reason": obj.get("individual_reason"),
            "symbol": symbol,
            "timeframe": "15m",
        })
    
    if rows:
        append_timeline_events(pd.DataFrame(rows))              # writes to timeline/YYYY-MM/DD.parquet
        if write_snapshot:
            upsert_current_objects(pd.DataFrame(rows).rename(columns={"object_id": "id"}))

def log_object_removal(object_ids_with_reason, reason="removal", ts=None):
    objects = [{"id": oid, "status": "removed", "individual_reason": why} for oid, why in object_ids_with_reason]
    add_timeline_step(objects, "remove", reason, ts=ts) # Will i get any errors here?

def _next_object_serial_from_parquet() -> int:
    """Read current snapshot and return next numeric id (max + 1)."""
    try:
        df = load_current_objects(columns=["id"])
        if not df.empty:
            as_int = pd.to_numeric(df["id"], errors="coerce")
            mx = int(as_int.dropna().max()) if not as_int.isna().all() else 0
            return mx + 1
    except Exception:
        pass
    return 1

# ───🔸 EXTERNAL HELPERS / UI HOOKS ───────────────────────────────────────

def get_objects():
    """
    Returns (zones, levels) from the *Parquet snapshot* if present,
    otherwise falls back to objects.json (legacy).
    """
    symbol = read_config('SYMBOL')

    try:
        cols = ["id","type","left","y","top","bottom","status","symbol","timeframe"]
        df = load_current_objects(columns=cols)
        if not df.empty:
            # normalize / filter
            df = df[(df["symbol"] == symbol) & (df["timeframe"] == "15m")]
            df = df[df["status"].fillna("active") != "removed"]

            zones, levels = [], []
            for r in df.itertuples(index=False):
                row = dict(zip(cols, r))
                if pd.notna(row.get("y")):
                    levels.append({
                        "id": row["id"], "type": row["type"],
                        "left": int(row["left"]), "y": float(row["y"]),
                    })
                elif pd.notna(row.get("top")) and pd.notna(row.get("bottom")):
                    zones.append({
                        "id": row["id"], "type": row["type"],
                        "left": int(row["left"]),
                        "top": float(row["top"]), "bottom": float(row["bottom"]),
                    })
            return zones, levels
    except Exception:
        pass
    return [], []   # <- ensure callers always get two lists

async def pull_and_replace_15m(days_back: int = 1):
    """
    RUN 15 after market closed, because of current polygon subscription plan.

    The purpose of this is to run after 15 mins of market close so that, you the manual user
    can fix whatever days data incase, wifi or power goes out, websocket/candle data collection 
    was interupted or corrupted, its for when the live 15 min data might be incorrect and we
    need some better accuracy. this is so that you remember.
    """

    # TODO: **CLEAR DATA** before pulling new data, so we dont have duplicates.
    # - Delete the 15m parquet file for today
    # - Delete the 15m csv file entry for today
    # - Delete the steps generated in both timelines, parquet and json, for today
    # - Delete everything in both objects.json and current parquet snapshot. Since timeline will be "re-created" from scratch.

    start, end = get_dates(days_back, True) #  go back to this (1, True) after were done finishing the timeline/object upload
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
    print_log(f"[pull_and_replace_15m] Main CSV `{pretty_path(SPY_15_MINUTE_CANDLES_PATH)}` updated with Polygon fallback.")

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
    # TODO: display_json_update("all") Change this to something... later on, when your at that point.
    print_log(f"[pull_and_replace_15m] Timeline + objects updated.")

async def create_daily_15m_parquet(file_day_name: str):
    """
    Pull 15M MARKET candles for the given day (NY time) from Polygon and write:
        storage/data/15m/<YYYY-MM-DD>.parquet
    Schema/Order:
        symbol, timeframe, ts, open, high, low, close, volume, global_x

    If `day` is None, uses today's NY trading day via get_dates(1, True).
    Returns the output file Path.
    """

    symbol = read_config("SYMBOL")
    tf_label = "15M"
    
    # 2) Pull 15M MARKET candles for that day(s)
    start_str, end_str = get_dates(1, True)
    df = await get_certain_candle_data(
        cred.POLYGON_API_KEY,
        symbol,
        15, "minute",
        start_str, end_str,
        None,
        market_type="MARKET",
        indent_lvl=0
    )
    if df is None or df.empty:
        print_log(f"[create_daily_15m_parquet] No data for {file_day_name}.")
        return None

    df.sort_values("timestamp", inplace=True)

    print_log(f"[create_daily_15m_parquet] Pulled '{len(df)}' rows for '{file_day_name}'.\n\n{df}\n")

    # 3) Ensure tz-aware NY timestamps -> ISO with offset for 'ts'
    #    (data_acquisition already converts to America/New_York tz)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(pytz.timezone("America/New_York"))
    ts_iso = df["timestamp"].apply(lambda ts: ts.isoformat())

    # 4) Build output DataFrame in required order
    volume_series = pd.Series(0, index=df.index, dtype="float64") # force all-zero volume as float64
    out_df = pd.DataFrame({
        "symbol":   symbol,
        "timeframe": tf_label,
        "ts":        ts_iso,
        "open":      df["open"].astype(float),
        "high":      df["high"].astype(float),
        "low":       df["low"].astype(float),
        "close":     df["close"].astype(float),
        "volume":    volume_series,
    })

    # 5) Stamp continuous global_x for 15m by peeking at last file
    out_dir = DATA_DIR / "15m"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{file_day_name}.parquet"

    last_global = _last_global_index(tf_label.lower(), file_day_name)
    start_gx = last_global + 1
    out_df["global_x"] = range(start_gx, start_gx + len(out_df))

    # 6) Atomic-ish write
    tmp = out_file.with_suffix(out_file.suffix + ".tmp")
    out_df.to_parquet(tmp, index=False)
    tmp.replace(out_file)

    # 7) Verify
    check = pd.read_parquet(out_file)
    ok = (
        len(check) == len(out_df)
        and check["ts"].min() == out_df["ts"].min()
        and check["ts"].max() == out_df["ts"].max()
        and check["global_x"].is_monotonic_increasing
        and int(check["global_x"].iloc[0]) == start_gx
        and int(check["global_x"].iloc[-1]) == start_gx + len(out_df) - 1
    )
    print_log(f"[create_daily_15m_parquet] → {'OK' if ok else 'WARN'} "
              f"{len(out_df)} rows → `{pretty_path(out_file)}`")
    return out_file

"""
# How to run

Process the *latest 3 days*: `python objects.py backfill --limit-days 3`
Process the *earliest 5 days* (useful for first-steps smoke test): `python objects.py backfill --limit-days 5 --oldest-first`
Process *only today’s dayfile* (your EOD path): `python objects.py eod`
Process *all days* (if you want to reprocess everything): `python objects.py`
Process *pull and replace 15m for 1 day* (current): `python objects.py pull-replace --days-back 1`
"""

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Objects backfill / EOD helpers")
    sub = parser.add_subparsers(dest="cmd")

    bf = sub.add_parser("backfill", help="Process multiple days of 15m parquet data")
    bf.add_argument("--limit-days", type=int, default=None, help="Only process this many days")
    bf.add_argument("--oldest-first", action="store_true", help="Process earliest N days instead of latest")

    eod = sub.add_parser("eod", help="Process only the most recent day")

    pr = sub.add_parser("pull-replace", help="Fetch 15m from Polygon and replace storage for that day")
    pr.add_argument("--days-back", type=int, default=1, help="How many days back to fetch (default 1)")

    args = parser.parse_args()

    if args.cmd == "backfill":
        update_timeline_with_objects(limit_days=args.limit_days, newest_first=not args.oldest_first)
    elif args.cmd == "eod":
        process_end_of_day_15m_candles_for_objects()
    elif args.cmd == "pull-replace":
        asyncio.run(pull_and_replace_15m(days_back=args.days_back))
    else:
        # default behavior (backfill everything)
        update_timeline_with_objects()