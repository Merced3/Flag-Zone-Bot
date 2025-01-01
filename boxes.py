#boxes.py
import pandas as pd
from pathlib import Path
import json
from error_handler import error_log_and_discord_message, print_log

config_path = Path(__file__).resolve().parent / 'config.json'

def read_config(key=None):
    """Reads the configuration file and optionally returns a specific key."""
    with config_path.open("r") as f:
        config = json.load(f)
    if key is None:
        return config  # Return the whole config if no key is provided
    return config.get(key)  # Return the specific key's value or None if key doesn't exist

config = read_config()
#BOX_SIZE_THRESHOLDS = config["BOX_SIZE_THRESHOLDS"]
#BOX_SPACING = config["BOX_SPACING"]



def get_v2(boxes_that_already_exist, tpls_that_already_exist, candle_data, current_date, day_length, is_get_PDHL=False, print_statements=False):
    # Ensure the 'timestamp' column is in datetime format and set as index
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)

    if boxes_that_already_exist is None:
        if is_get_PDHL:
            PDHL_box = get_PDHL(candle_data, current_date)
            return PDHL_box, None
        else:
            new_zones = get_support_resistance(candle_data, current_date, boxes_that_already_exist, print_statements)
            return new_zones, None

    # If boxes exist, update their positions
    for box_name in boxes_that_already_exist:
        x_pos, highest_val, lowest_val = boxes_that_already_exist[box_name]
        #print(f"    [BEFORE ADDITION] Box: {box_name}, x_pos: {x_pos}")
        x_pos = day_length + x_pos # Adjust
        #print(f"    [AFTER ADDITION] Box: {box_name}, x_pos: {x_pos}\n")
        boxes_that_already_exist[box_name] = (x_pos, highest_val, lowest_val)
    # If TPLs exist, update their positions
    for tpl_name in tpls_that_already_exist:
        x_pos, y_pos = tpls_that_already_exist[tpl_name]
        #print(f"    [BEFORE ADDITION] tpl: {box_name}, x_pos: {x_pos}")
        x_pos = day_length + x_pos
        #print(f"    [AFTER ADDITION] tpl: {box_name}, x_pos: {x_pos}")
        tpls_that_already_exist[tpl_name] = (x_pos, y_pos)
    
    # Get support and resistnace zone for 'current_date'
    new_zones = get_support_resistance(candle_data, current_date, boxes_that_already_exist, print_statements)
    
    return new_zones, tpls_that_already_exist

def correct_too_big_small_boxes(candle_data, boxes, print_statements=False):
    if print_statements:    
        print_log(f"\n---------------------\nResizing Boxes that are too Small or Big:")

    if print_statements:    
        print_log(f"Boxes Before Processing: {boxes}\n")
    
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)

    corrected_boxes = {}
    for box_name, (box_candle_pos, keep_value, change_value) in boxes.items():
        # Skip processing for PDHL box and 'b_' boxes because 'b' means BOTH lines are important
        if 'PDHL' in box_name or 'b_' in box_name:
            corrected_boxes[box_name] = boxes[box_name]
            continue

        box_type = 'resistance' if 'resistance' in box_name else 'support'
        
        # Debug info
        if print_statements:
            print_log(f"Processing box: {box_name} at position {box_candle_pos}")
            print_log(f"candle_data length: {len(candle_data)}")
            print_log(f"candle_data.index: {candle_data.index}")

        # Check if box_candle_pos is within bounds
        if box_candle_pos >= len(candle_data):
            print_log(f"Skipping {box_name} because box_candle_pos {box_candle_pos} is out of bounds for candle_data length {len(candle_data)}")
            continue
        
        box_date = candle_data.index[box_candle_pos].date()
        day_data = candle_data[candle_data.index.date == box_date]
        day_before_data = candle_data[candle_data.index.date == box_date - pd.Timedelta(days=1)]
        day_after_data = candle_data[candle_data.index.date == box_date + pd.Timedelta(days=1)]

        height = abs(keep_value - change_value)
        if read_config('BOX_SIZE_THRESHOLDS')[0] <= height <= read_config('BOX_SIZE_THRESHOLDS')[1]:
            corrected_boxes[box_name] = boxes[box_name]
            continue

        min_value, max_value = sorted([keep_value - read_config('BOX_SIZE_THRESHOLDS')[1], keep_value - read_config('BOX_SIZE_THRESHOLDS')[0]]) if box_type == 'resistance' else sorted([keep_value + read_config('BOX_SIZE_THRESHOLDS')[0], keep_value + read_config('BOX_SIZE_THRESHOLDS')[1]])
        closest_distance = float('inf')
        corrected_value = change_value
        corrected_pos = box_candle_pos
        
        dataframes_to_check = [day_data, day_after_data, day_before_data]
        for df in dataframes_to_check:
            for _, candle in df.iterrows():
                possible_values = [candle['open'], candle['close'], candle['high'], candle['low']]
                for value in possible_values:
                    if min_value <= value <= max_value:
                        corrected_value = value
                        corrected_pos = candle_data.index.get_loc(candle.name)
                        break
                else:
                    # Find the value closest to min_value or max_value
                    closest_value = min(possible_values, key=lambda x: min(abs(x - min_value), abs(x - max_value)))
                    closest_diff = min(abs(closest_value - min_value), abs(closest_value - max_value))
                    if closest_diff < closest_distance:
                        corrected_value = closest_value
                        closest_distance = closest_diff
                        corrected_pos = candle_data.index.get_loc(candle.name)
                    continue
                break
            else:
                continue
            break
        else:
            if print_statements:    
                print_log(f"{box_name} Has No Suitable Candle Within Threshold, adjusted to closest value")

        corrected_pos = min(corrected_pos, box_candle_pos)
        corrected_boxes[box_name] = (corrected_pos, keep_value, corrected_value)

    if print_statements:    
        print_log(f"Correctly Sized Boxes: {corrected_boxes}\n---------------------\n")
    return corrected_boxes

def correct_zones_inside_other_zones(boxes, print_statements=False):
    keys_to_delete = []
    
    # Get the sorted list of box items
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0])
    
    # Iterate over the sorted boxes to find overlaps
    for i in range(len(sorted_boxes)):
        for j in range(i + 1, len(sorted_boxes)):
            name1, (index1, hl1, buf1) = sorted_boxes[i]
            name2, (index2, hl2, buf2) = sorted_boxes[j]

            #setting easy set values for mental visual
            top_1 = None
            bottom_1 = None
            top_2 = None
            bottom_2 = None
            if "resistance" in name1 or "PDHL" in name1:
                top_1 = hl1
                bottom_1 = buf1
            if "resistance" in name2 or "PDHL" in name2:
                top_2 = hl2
                bottom_2 = buf2
            if "support" in name1:
                top_1 = buf1
                bottom_1 = hl1
            if "support" in name2:
                top_2 = buf2
                bottom_2 = hl2

            if top_1 and bottom_1 and top_2 and bottom_2:
                corrected_name = None
                corrected_index = index1 if index1 < index2 else index2
                # Check if box1 has any boxes inside of it
                if (top_1 >= top_2 >= bottom_2 >= bottom_1) or (top_2 >= top_1 >= bottom_1 >= bottom_2):
                    # Box 1 has a box inside of it.
                    if "PDHL" in name1 or "PDHL" in name2:
                        # Anything Dealing with PDHL Senarios
                        if (("resistance" in name1) and ("PDHL" in name2) and (top_1>=top_2>=bottom_2>=bottom_1)) or (("support" in name1) and ("PDHL" in name2) and (top_1>=top_2>=bottom_2>=bottom_1)):
                            #if a PDHL is inside of a resistance or support zone.
                            if print_statements:
                                print_log(f"    [CZIOZ] name1: {name1}; {index1}\n    [CZIOZ] name2: {name2}; {index2}")
                            
                            corrected_name = name1 if "PDHL" in name1 else name2
                            corrected_index = index1 if index1 < index2 else index2

                            if "resistance" in name1:
                                # Change top, keep Bottom
                                top_value = hl1 if "resistance" in name1 else hl2
                                bottom_value = buf1 if "PDHL" in name1 else buf2
                            elif "support" in name1:
                                # Change Bottom, keep Top
                                top_value = hl1 if "PDHL" in name1 else hl2
                                bottom_value = hl1 if "support" in name1 else hl2
                            else:
                                if print_statements:
                                    print_log(f"    [CZIOZ] No Support for '{name1}' and '{name2}'")
                            # Corrected box
                            boxes[corrected_name] = (corrected_index, top_value, bottom_value)
                            keys_to_delete.append(name2 if "PDHL" in name1 else name1)
                        else:
                            # if PDHL is inside another Zone, whatever it maybe.
                            keys_to_delete.append(name2 if "PDHL" in name1 else name1)
                    elif (("resistance" in name1) and ("support" in name2)) or (("support" in name1) and ("resistance" in name2)):
                        # Make a new PDHL
                        corrected_name = f"PDHL_{len([name for name, _ in sorted_boxes if name.startswith('PDHL')]) + 1}"
                        if print_statements:
                            print_log(f"    [CZIOZ] Corrected name1: {corrected_name}")
                        keys_to_delete.append(name1)
                        keys_to_delete.append(name2)

                        # Now Resize
                        #top_value = hl1 if "resistance" in name1 else hl2
                        #bottom_value = hl1 if "support" in name1 else hl2
                        top_value = hl1 if hl1>=hl2 else hl2
                        bottom_value = hl1 if hl1<=hl2 else hl2
                        
                        
                        # Corrected box
                        boxes[corrected_name] = (corrected_index, top_value, bottom_value) # 2 opposite zones have combined/widened
                        if print_statements:
                            print_log(f"    [CZIOZ, OPPOSITE ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{top_value},{bottom_value})")
                    elif (("resistance" in name1) and ("resistance" in name2)) or (("support" in name1) and ("support" in name2)):
                        # Identical Zones are inside eachother
                        # Make a new PDHL
                        if print_statements:     
                            print_log(f"    [CZIOZ] name1: {name1}, {index1}, {hl1}, {buf1}")
                            print_log(f"    [CZIOZ] name2: {name2}, {index2}, {hl2}, {buf2}")
                        corrected_name = name1 if index1 < index2 else name2
                        keys_to_delete.append(name2 if index1 < index2 else name1)

                        # Now Resize
                        if "resistance" in name1 and "resistance" in name2:
                            Important_value= hl1 if hl1>=hl2 else hl2 
                            buffer_value= buf1 if buf1>=buf2 else buf2
                        elif "support" in name1 and "support" in name2:
                            Important_value= hl1 if hl1<=hl2 else hl2 
                            buffer_value= buf1 if buf1<=buf2 else buf2

                        # Corrected box
                        boxes[corrected_name] = (corrected_index, Important_value, buffer_value) # 2 identical zones have combined
                        if print_statements: 
                            print_log(f"    [CZIOZ] new Box: {corrected_name}, {corrected_index}, {Important_value}, {buffer_value}")
    if print_statements:    
        print_log(f"    [CZIOZ] KEYS TO DELETE: {keys_to_delete}")

    # Remove the boxes that are inside others
    for key in keys_to_delete:
        if key in boxes:
            del boxes[key]
    
    return boxes

def get_support_resistance(candle_data, current_date, boxes_that_already_exist, print_statements=False):
    # Ensure the index is a DatetimeIndex
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)
    
    # Find resistance and support zones in the new day's data
    day_data = candle_data[candle_data.index.date == current_date]
    
    # Initialize lists for resistances and supports
    resistances, supports = [], []
    
    # Add current resistances and supports to the lists
    if boxes_that_already_exist: 
        for box_name, (index, high_low_of_day, buffer) in boxes_that_already_exist.items():
            if 'resistance' in box_name:
                resistances.append((index, high_low_of_day, buffer))
            elif 'support' in box_name:
                supports.append((index, high_low_of_day, buffer))
    else:
        boxes_that_already_exist = {}
    
    # Find resistances (highs)
    daily_high = day_data['high'].max()
    high_idx = day_data['high'].idxmax()
    high_pos = candle_data.index.get_loc(high_idx)

    if len(day_data.loc[high_idx:]) > 1:
        next_candle = day_data.loc[high_idx:].iloc[1]
        next_close_after_high = next_candle['open'] if next_candle['open'] > next_candle['close'] else next_candle['close']
    else:
        current_candle = day_data.loc[high_idx]
        next_close_after_high = current_candle['open'] if current_candle['open'] > current_candle['close'] else current_candle['close']

    resistances.append((high_pos, daily_high, next_close_after_high))

    # Find supports (lows)
    daily_low = day_data['low'].min()
    low_idx = day_data['low'].idxmin()
    low_pos = candle_data.index.get_loc(low_idx)

    if len(day_data.loc[low_idx:]) > 1:
        next_candle = day_data.loc[low_idx:].iloc[1]
        next_close_after_low = next_candle['close'] if next_candle['open'] > next_candle['close'] else next_candle['open']
    else:
        current_candle = day_data.loc[low_idx]
        next_close_after_low = current_candle['open'] if current_candle['open'] < current_candle['close'] else current_candle['close']

    supports.append((low_pos, daily_low, next_close_after_low))
    
    # Combine new resistances and supports with existing ones
    new_boxes = {f'resistance_{i+1}': box for i, box in enumerate(resistances)}
    new_boxes.update({f'support_{i+1}': box for i, box in enumerate(supports)})
    boxes_that_already_exist.update(new_boxes)

    boxes_that_already_exist = correct_too_big_small_boxes(candle_data, boxes_that_already_exist, print_statements)
    #print(f"    [BOX DETIALS] {boxes_that_already_exist}\n")
    return boxes_that_already_exist

def get_PDHL(candle_data, current_date):
    # Ensure the index is a DatetimeIndex
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)
    
    # Filter data for the given day
    one_day_of_candle_data = candle_data[candle_data.index.date == current_date]

    # Find the highest and lowest point of the day
    highest_val = one_day_of_candle_data['high'].max()
    lowest_val = one_day_of_candle_data['low'].min()

    # Find the x positions (indexes) of the highest and lowest points
    h_x_pos = candle_data.index.get_loc(one_day_of_candle_data['high'].idxmax())
    l_x_pos = candle_data.index.get_loc(one_day_of_candle_data['low'].idxmin())

    # Choose the earlier x-position as the box position
    x_pos = min(h_x_pos, l_x_pos)

    # Create the PDHL box
    PDHL = {'PDHL_1': (x_pos, highest_val, lowest_val)}
    return PDHL

def correct_bleeding_zones(boxes, _tp_lines, print_statements=False):
    keys_to_delete_boxes = []
    tp_lines = {} if _tp_lines is None else _tp_lines

    # Get the sorted list of box items
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0])
    
    # Iterate over the sorted boxes to find overlaps
    for i in range(len(sorted_boxes)):
        for j in range(i + 1, len(sorted_boxes)):
            name1, (index1, hl1, buf1) = sorted_boxes[i] # hl means high or low, buf means buffer
            name2, (index2, hl2, buf2) = sorted_boxes[j]
            
            #setting easy set values for mental visual
            top_1 = None
            bottom_1 = None
            top_2 = None
            bottom_2 = None
            if "resistance" in name1 or "PDHL" in name1:
                top_1 = hl1
                bottom_1 = buf1
            if "resistance" in name2 or "PDHL" in name2:
                top_2 = hl2
                bottom_2 = buf2
            if "support" in name1:
                top_1 = buf1
                bottom_1 = hl1
            if "support" in name2:
                top_2 = buf2
                bottom_2 = hl2
            
            if print_statements:
                print_log(f"{name1}: ({index1}, {top_1}, {bottom_1}) | {name2}: ({index1}, {top_2}, {bottom_2})")
            
            if top_1 and bottom_1 and top_2 and bottom_2:
                corrected_name = None
                corrected_index = index1 if index1 < index2 else index2
                    
                if (top_1 >= top_2 >= bottom_1 >= bottom_2) or (top_2 >= top_1 >= bottom_2 >= bottom_1):
                    if print_statements:    
                        print_log(f"    [CBZ, Meshed zones detected] {name1}, ({index1},{hl1},{buf1}) ; {name2}, ({index2},{hl2},{buf2})")
                        
                    # Stating values that other if-statements can use
                    top_value = top_1 if top_1 >= top_2 else top_2
                    other_top = top_1 if top_1 <= top_2 else top_2
                    bottom_value = bottom_1 if bottom_1 <= bottom_2 else bottom_2
                    other_bottom = bottom_1 if bottom_1 >= bottom_2 else bottom_2
                        
                        #figure out what name we need to correct so we can delete the others
                    if ("resistance" in name1 and "resistance" in name2) or ("support" in name1 and "support" in name2) or ("PDHL" in name1 and "PDHL" in name2):
                        # Make a whole new zone then forget both name 1 and 2 zones
                        corrected_name = f"PDHL_{len([name for name, _ in sorted_boxes if name.startswith('PDHL')]) + 1}"
                        if print_statements:    
                            print_log(f"    [CBZ] Corrected name2: {corrected_name}")
                        keys_to_delete_boxes.append(name1)
                        keys_to_delete_boxes.append(name2)
                        
                        # Now resize
                        hl_1 = top_value if "resistance" in name1 and "resistance" in name2 else bottom_value
                        hl_2 = other_top if "resistance" in name1 and "resistance" in name2 else other_bottom
                        top_value = hl_1 if hl_1>hl_2 else hl_2
                        bottom_value = hl_1 if hl_1<hl_2 else hl_2
                        boxes[corrected_name] = (corrected_index, top_value, bottom_value) # the reason for 'hl_1' and 'hl_2' (high low 1st or 2nd) first is the most important meaning if this is a resistance then 1st is the top of the box and if support then bottom
                        if print_statements:
                            print_log(f"    [CBZ, IDENTICLE ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{hl_1},{hl_2})")
                    elif ("resistance" in name1 and "PDHL" in name2) or ("PDHL" in name1 and "resistance" in name2) or ("support" in name1 and "PDHL" in name2) or ("PDHL" in name1 and "support" in name2):
                    # Keep one zone, forget the other
                        corrected_name = name1 if "PDHL" in name1 else name2 # Keep key that is PDHL
                        delete_key = name2 if "PDHL" in name1 else name1 # Delete key that is not PDHL
                        keys_to_delete_boxes.append(delete_key)

                        # Now resize
                        (_index_, important_val, _buffer_) = boxes[delete_key] # Either resistance or support
                        (base_index, base_top, base_bottom) = boxes[corrected_name] # PDHL
                        corrected_index = base_index if base_top >= important_val >= base_bottom else corrected_index # if important_val is inbetween PDHL, we don't need to edit PDHL. corrected index will equal back to normal state
                        top_side = top_value if "resistance" in delete_key else base_top
                        bottom_side = bottom_value if "support" in delete_key else base_bottom
                        boxes[corrected_name] = (corrected_index, top_side, bottom_side) # PDHL has been edited/widened
                        if print_statements:
                            print_log(f"    [CBZ, SIMILAR ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{top_side},{bottom_side})")
                    elif ("resistance" in name1 and "support" in name2) or ("support" in name1 and "resistance" in name2): # support on resistance ; resistance on support
                        corrected_name = f"PDHL_{len([name for name, _ in sorted_boxes if name.startswith('PDHL')]) + 1}"
                        if print_statements:
                            print_log(f"    [CBZ] Corrected name3: {corrected_name}")
                        keys_to_delete_boxes.append(name1)
                        keys_to_delete_boxes.append(name2)

                        # Now Resize
                        top_value = hl1 if hl1>hl2 else hl2
                        bottom_value = hl1 if hl1<hl2 else hl2
                        height = top_value - bottom_value
                        
                        if height<=0.25:
                            # Too Small, Make into TP_Lines
                            if print_statements:
                                print_log(f"    [CBZ] Box too small: {corrected_name}; {height}")
                            new_name_1="TP_resistance_1"
                            new_name_2="TP_support_1"
                            new_name_1 = generate_unique_name(new_name_1, tp_lines)
                            new_name_2 = generate_unique_name(new_name_2, tp_lines)
                            TPL_x1 = index1 if "resistance" in name1 else index2
                            TPL_x2 = index1 if "support" in name1 else index2
                            tp_lines[new_name_1] = (TPL_x1, top_value) # resistance
                            tp_lines[new_name_2] = (TPL_x2, bottom_value) # support
                            if print_statements:
                                print_log(f"    [CBZ] Created new Lines: {new_name_1}, ({tp_lines[new_name_1]}) | {new_name_2}, ({tp_lines[new_name_2]})")
                        else:
                            #continue with box creation
                            boxes[corrected_name] = (corrected_index, top_value, bottom_value) # 2 opposite zones have combined/widened
                            if print_statements:
                                print_log(f"    [CBZ, OPPOSITE ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{top_value},{bottom_value})")
                        
            else:
                if print_statements:
                    print_log(f"    [CBZ] missing value: {name1}, {top_1}, {bottom_1} | {name2}, {top_2}, {bottom_2}")
    # Remove the boxes that are inside others
    for key in keys_to_delete_boxes:
        if key in boxes:
            del boxes[key]
    if print_statements:
        print_log(f"    [CBZ] KEYS TO DELETE: {keys_to_delete_boxes}")

    return boxes, tp_lines

def correct_zones_that_are_too_close(boxes, _tp_lines, print_statements=False, remove_TPs_too_close=False):
    if print_statements:
        print_log(f"Starting CZTATC")
    keys_to_delete_boxes = []
    keys_to_delete_lines = []
    tp_lines = {} if _tp_lines is None else _tp_lines
    # Sorting from newer to older, for 'boxes' the way we can tell that is by the larger the 'index', the newer it is.
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0], reverse=True)
    #if print_statements:
        #print(f"    [CZTATC] sorted_boxes: {sorted_boxes}")

    # if any box is too close to other boxes, remove it
    for i in range(len(sorted_boxes)):
        for j in range(i + 1, len(sorted_boxes)):
            name1, (index1, hl1, buf1) = sorted_boxes[i]
            name2, (index2, hl2, buf2) = sorted_boxes[j]
            TPL_name = f"TP_{name1 if index1 < index2 else name2}"
            TPL_x = index1 if index1 < index2 else index2
            TPL_y = hl1 if index1 < index2 else hl2
            buffers_range = abs(buf1 - buf2)
            high_low_range = abs(hl1 - hl2)
            high_low_buffer_range = abs(hl1 - buf2)
            high_low_buffer_range_2 = abs(hl2 - buf1)

            if (buffers_range <= read_config('BOX_SPACING')) or (high_low_range <= read_config('BOX_SPACING')) or (high_low_buffer_range <= read_config('BOX_SPACING')) or (high_low_buffer_range_2 <= read_config('BOX_SPACING')):
                #these are made incase of zone were trying to remove has 2 important lines
                if "b_" in TPL_name:
                    new_name_1 = f"{TPL_name}_1"
                    new_name_2 = f"{TPL_name}_2"
                    # 'b' means both lines (hl and buf) are important
                    if index1 < index2:
                        TPL_y1 = hl1
                        TPL_y2 = buf1
                    else:
                        TPL_y1 = hl2
                        TPL_y2 = buf2
                    # Create 2 new tp_lines, remove box
                    tp_lines[new_name_1] = (TPL_x, TPL_y1)
                    tp_lines[new_name_2] = (TPL_x, TPL_y2)
                    keys_to_delete_boxes.append(name2 if index1 > index2 else name1)
                    if print_statements:
                        print_log(f"    [CZTATC] Deleting1: {name2 if index1 > index2 else name1}; and NOT deleting: {name2 if index1 < index2 else name1}")
                elif "PDHL" in name1 and "PDHL" in name2:
                    name_to_delete, name_to_keep = (name2,name1) if index1 > index2 else (name1,name2)
                    # if 'name_to_delete' is 'PDHL_1' DO NOT DELETE IT. make the other one a TP Line
                    if 'PDHL_1' not in name_to_delete:
                        new_name_1="TP_resistance_1"
                        new_name_2="TP_support_1"
                        new_name_1 = generate_unique_name(new_name_1, tp_lines)
                        new_name_2 = generate_unique_name(new_name_2, tp_lines)
                        if print_statements:
                            print_log(f"    [CZTATC] New Name1: {new_name_1}")
                            print_log(f"    [CZTATC] New Name2: {new_name_2}")
                        TPL_x1 = index1 if index1 < index2 else index2
                        TPL_x2 = TPL_x1
                        if index1 < index2:
                            TPL_y1 = hl1
                            TPL_y2 = buf1
                        else:
                            TPL_y1 = hl2
                            TPL_y2 = buf2

                        # Create a new "tp_line" and add it to "tp_lines"
                        tp_lines[new_name_1] = (TPL_x1, TPL_y1)
                        tp_lines[new_name_2] = (TPL_x2, TPL_y2)
                        keys_to_delete_boxes.append(name_to_delete)
                    else:
                        #PDHL_1 is the perfer'd one to delete purely based off of index but we don't want to do that. since PDHL_1 is the most important Zone out of them all.
                        name_to_keep = name1 if "PDHL_1" in name1 else name2
                        name_to_delete = name2 if "PDHL_1" in name1 else name1
                        new_name_1="TP_resistance_1"
                        new_name_2="TP_support_1"
                        new_name_1 = generate_unique_name(new_name_1, tp_lines)
                        new_name_2 = generate_unique_name(new_name_2, tp_lines)
                        if print_statements:
                            print_log(f"    [CZTATC] New Name1: {new_name_1}")
                            print_log(f"    [CZTATC] New Name2: {new_name_2}")
                        TPL_x1 = index2 if "PDHL_1" in name1 else index1
                        TPL_x2 = TPL_x1
                        if "PDHL_1" in name1:
                            TPL_y1 = hl2
                            TPL_y2 = buf2
                        else:
                            TPL_y1 = hl1
                            TPL_y2 = buf1
                        # Create a new "tp_line" and add it to "tp_lines"
                        tp_lines[new_name_1] = (TPL_x1, TPL_y1)
                        tp_lines[new_name_2] = (TPL_x2, TPL_y2)
                        keys_to_delete_boxes.append(name_to_delete)

                    if print_statements:
                        print_log(f"    [CZTATC] Deleting2: {name_to_delete}; and NOT deleting: {name_to_keep}")

                else:
                    name_to_delete, name_to_keep = (name2,name1) if index1 > index2 else (name1,name2)
                    # if the name we want to keep is in 'keys_to_delete_boxes' then were near nothing and don't need to delete anything.
                    if name_to_keep not in keys_to_delete_boxes:
                        if print_statements:
                            print_log(f"    [CZTATC] name1: {name1}; {index1}\n    [CZTATC] name2: {name2}; {index2}")
                        # Create a new "tp_line" and add it to "tp_lines"
                        tp_lines[generate_unique_name(TPL_name, tp_lines)] = (TPL_x, TPL_y)
                        
                        keys_to_delete_boxes.append(name_to_delete)
                    
                        if print_statements:
                            print_log(f"    [CZTATC] Deleting3: {name_to_delete}; and NOT deleting: {name_to_keep}")
    if print_statements:
        print_log(f"\n TPLs: {tp_lines}\n")
    
    for key in keys_to_delete_boxes:
        if key in boxes:
            del boxes[key]
    if print_statements:
        print_log(f"    [CZTATC] KEY BOXES TO DELETE: {keys_to_delete_boxes}")
    
    # find if lines are too close to any zone
    for tpl_name, tpl_detials in tp_lines.items():
        for box_name, box_details in boxes.items():
            tp_x, tp_y = tpl_detials 
            index, hl, buf = box_details
            threshold_size = read_config('BOX_SPACING')
            range_hl = abs(hl - tp_y)
            range_buf = abs(buf - tp_y) # if in range and line x is less that box x, meaning line less important
            if (range_hl <= threshold_size) or (range_buf <= threshold_size):
                if tp_x <= index:
                    if remove_TPs_too_close:
                        # Remove line
                        keys_to_delete_lines.append(tpl_name)
                    else:
                        if print_statements:
                            print_log(f"NOT REMOVING '{tpl_name}' Because 'remove_TPs_too_close' is set too '{remove_TPs_too_close}'.")
                    if print_statements:
                        if range_hl <= threshold_size:
                            print_log(f"LINE: '{tpl_name}' to close to '{box_name}'\nRange hl: {range_hl}\n")
                        if range_buf <= threshold_size:
                            print_log(f"LINE: '{tpl_name}' to close to '{box_name}'\nRange buf: {range_buf}\n")
    for key in keys_to_delete_lines:
        if key in tp_lines:
            del tp_lines[key]

    if print_statements:
        print_log(f"Altered boxes: {boxes}\n\nTP Lines: {tp_lines}\n---------------")

    return boxes, tp_lines

def generate_unique_name(base_name, tp_lines):
    # Split the base name by underscore and check if the last part is numeric
    parts = base_name.split('_')
    
    # Try to extract the last part as an integer, if it's not a number, start with 1
    if parts[-1].isdigit():
        counter = int(parts[-1])
        base_name = '_'.join(parts[:-1])  # Reconstruct the base name without the number
    else:
        counter = 1

    # Generate a new unique name by incrementing the counter
    new_name = f"{base_name}_{counter}"
    while new_name in tp_lines:
        counter += 1
        new_name = f"{base_name}_{counter}"

    return new_name