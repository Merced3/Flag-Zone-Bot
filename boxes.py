#boxes.py
import pandas as pd
from pathlib import Path
import json

config_path = Path(__file__).resolve().parent / 'config.json'
def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config

config = read_config()
BOX_SIZE_THRESHOLDS = config["BOX_SIZE_THRESHOLDS"]
BOX_SPACING = config["BOX_SPACING"]



def get_v2(boxes_that_already_exist, tpls_that_already_exist, candle_data, current_date, day_length, is_get_PDHL=False, print_statements=False):
    # Ensure the 'timestamp' column is in datetime format and set as index
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)

    if boxes_that_already_exist is None:
        if is_get_PDHL:
            PDHL_box = get_PDHL(candle_data, current_date)
            return PDHL_box
        else:
            new_zones = get_support_resistance(candle_data, current_date, boxes_that_already_exist, print_statements)
            return new_zones

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
    
    return new_zones

def correct_too_big_small_boxes(candle_data, boxes, print_statements=False):
    if print_statements:    
        print(f"\n---------------------\nResizing Boxes that are too Small or Big:")

    if print_statements:    
        print(f"Boxes Before Processing: {boxes}\n")
    
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
            print(f"Processing box: {box_name} at position {box_candle_pos}")
            print(f"candle_data length: {len(candle_data)}")
            print(f"candle_data.index: {candle_data.index}")

        # Check if box_candle_pos is within bounds
        if box_candle_pos >= len(candle_data):
            print(f"Skipping {box_name} because box_candle_pos {box_candle_pos} is out of bounds for candle_data length {len(candle_data)}")
            continue
        
        box_date = candle_data.index[box_candle_pos].date()
        day_data = candle_data[candle_data.index.date == box_date]
        day_before_data = candle_data[candle_data.index.date == box_date - pd.Timedelta(days=1)]
        day_after_data = candle_data[candle_data.index.date == box_date + pd.Timedelta(days=1)]

        height = abs(keep_value - change_value)
        if BOX_SIZE_THRESHOLDS[0] <= height <= BOX_SIZE_THRESHOLDS[1]:
            corrected_boxes[box_name] = boxes[box_name]
            continue

        min_value, max_value = sorted([keep_value - BOX_SIZE_THRESHOLDS[1], keep_value - BOX_SIZE_THRESHOLDS[0]]) if box_type == 'resistance' else sorted([keep_value + BOX_SIZE_THRESHOLDS[0], keep_value + BOX_SIZE_THRESHOLDS[1]])
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
                print(f"{box_name} Has No Suitable Candle Within Threshold, adjusted to closest value")

        corrected_pos = min(corrected_pos, box_candle_pos)
        corrected_boxes[box_name] = (corrected_pos, keep_value, corrected_value)

    if print_statements:    
        print(f"Correctly Sized Boxes: {corrected_boxes}\n---------------------\n")
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

            # Check if box1 has any boxes inside of it
            if top_1 >= top_2 >= bottom_2 >= bottom_1:
                keys_to_delete.append(name2)
            elif top_2 >= top_1 >= bottom_1 >= bottom_2:
                keys_to_delete.append(name1)

    if print_statements:    
        print(f"    [CZIOZ] KEYS TO DELETE: {keys_to_delete}")

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

def correct_bleeding_zones(boxes, print_statements=False):
    keys_to_delete = []
    
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
                print(f"{name1}: ({index1}, {top_1}, {bottom_1}) | {name2}: ({index1}, {top_2}, {bottom_2})")
            
            if top_1 and bottom_1 and top_2 and bottom_2:
                corrected_name = None
                corrected_index = index1 if index1 < index2 else index2
                    
                if (top_1 >= top_2 >= bottom_1 >= bottom_2) or (top_2 >= top_1 >= bottom_2 >= bottom_1):
                    if print_statements:    
                        print(f"    [Meshed zones detected] {name1}, ({index1},{hl1},{buf1}) ; {name2}, ({index2},{hl2},{buf2})")
                        
                    # Stating values that other if-statements can use
                    top_value = top_1 if top_1 >= top_2 else top_2
                    other_top = top_1 if top_1 <= top_2 else top_2
                    bottom_value = bottom_1 if bottom_1 <= bottom_2 else bottom_2
                    other_bottom = bottom_1 if bottom_1 >= bottom_2 else bottom_2
                        
                        #figure out what name we need to correct so we can delete the others
                    if ("resistance" in name1 and "resistance" in name2) or ("support" in name1 and "support" in name2) or ("PDHL" in name1 and "PDHL" in name2):
                        # Make a whole new zone then forget both name 1 and 2 zones
                        corrected_name = 'b_'+name1 if index1 > index2 else 'b_'+name2 # 'b' means double, meaning both lines are important.
                        keys_to_delete.append(name1)
                        keys_to_delete.append(name2)
                        
                        # Now resize
                        hl_1 = top_value if "resistance" in name1 and "resistance" in name2 else bottom_value
                        hl_2 = other_top if "resistance" in name1 and "resistance" in name2 else other_bottom
                        boxes[corrected_name] = (corrected_index, hl_1, hl_2) # the reason for 'hl_1' and 'hl_2' (high low 1st or 2nd) first is the most important meaning if this is a resistance then 1st is the top of the box and if support then bottom
                        if print_statements:
                            print(f"        [IDENTICLE ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{hl_1},{hl_2})")
                    elif ("resistance" in name1 and "PDHL" in name2) or ("PDHL" in name1 and "resistance" in name2) or ("support" in name1 and "PDHL" in name2) or ("PDHL" in name1 and "support" in name2):
                    # Keep one zone, forget the other
                        corrected_name = name1 if "PDHL" in name1 else name2 # Keep key that is PDHL
                        delete_key = name2 if "PDHL" in name1 else name1 # Delete key that is not PDHL
                        keys_to_delete.append(delete_key)

                        # Now resize
                        (_index_, important_val, _buffer_) = boxes[delete_key] # Either resistance or support
                        (base_index, base_top, base_bottom) = boxes[corrected_name] # PDHL
                        corrected_index = base_index if base_top >= important_val >= base_bottom else corrected_index # if important_val is inbetween PDHL, we don't need to edit PDHL. corrected index will equal back to normal state
                        top_side = top_value if "resistance" in delete_key else base_top
                        bottom_side = bottom_value if "support" in delete_key else base_bottom
                        boxes[corrected_name] = (corrected_index, top_side, bottom_side) # PDHL has been edited/widened
                        if print_statements:
                            print(f"        [SIMILAR ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{top_side},{bottom_side})")
                    elif ("resistance" in name1 and "support" in name2) or ("support" in name1 and "resistance" in name2): # support on resistance ; resistance on support
                        corrected_name = f"PDHL_{len([name for name, _ in sorted_boxes if name.startswith('PDHL')]) + 1}"
                        keys_to_delete.append(name1)
                        keys_to_delete.append(name2)

                        # Now Resize
                        if "resistance" in name1:
                            top_value = hl1
                        if "resistance" in name2:
                            top_value = hl2
                        if "support" in name1:
                            bottom_value = hl1
                        if "support" in name2:
                            bottom_value = hl2
                        boxes[corrected_name] = (corrected_index, top_value, bottom_value) # 2 opposite zones have combined/widened
                        if print_statements:
                            print(f"        [OPPOSITE ZONES COMBINED] Alteration: {corrected_name}, ({corrected_index},{top_value},{bottom_value})")
                        
            else:
                if print_statements:
                    print(f"    [CBZ] missing value: {name1}, {top_1}, {bottom_1} | {name2}, {top_2}, {bottom_2}")
    # Remove the boxes that are inside others
    for key in keys_to_delete:
        if key in boxes:
            del boxes[key]
    if print_statements:
        print(f"    [CBZ] KEYS TO DELETE: {keys_to_delete}")
    return boxes

def correct_zones_that_are_too_close(boxes, _tp_lines, print_statements=False):
    if print_statements:
        print(f"Starting CZTATC")
    keys_to_delete_boxes = []
    keys_to_delete_lines = []
    tp_lines = {} if _tp_lines is None else _tp_lines
    # Sorting from newer to older, for 'boxes' the way we can tell that is by the larger the 'index', the newer it is.
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0], reverse=True)
    if print_statements:
        print(f"sorted_boxes: {sorted_boxes}")

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

            if (buffers_range <= BOX_SPACING) or (high_low_range <= BOX_SPACING) or (high_low_buffer_range <= BOX_SPACING) or (high_low_buffer_range_2 <= BOX_SPACING):
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
                else:
                    # Create a new "tp_line" and add it to "tp_lines"
                    tp_lines[TPL_name] = (TPL_x, TPL_y)
                    keys_to_delete_boxes.append(name2 if index1 > index2 else name1)
    if print_statements:
        print(f"\n TPLs: {tp_lines}\n")
    
    for key in keys_to_delete_boxes:
        if key in boxes:
            del boxes[key]
    
    # find if lines are too close to any zone
    new_tpls = {}
    for tpl_name, tpl_detials in tp_lines.items():
        for box_name, box_details in boxes.items():
            tp_x, tp_y = tpl_detials 
            index, hl, buf = box_details
            threshold_size = BOX_SIZE_THRESHOLDS[1]
            range_hl = abs(hl - tp_y)
            range_buf = abs(buf - tp_y) # if in range and line x is less that box x, meaning line less important
            if (range_hl <= threshold_size) or (range_buf <= threshold_size):
                if tp_x <= index:
                    # Remove line
                    keys_to_delete_lines.append(tpl_name)
                    if print_statements:
                        if range_hl <= threshold_size:
                            print(f"LINE: '{tpl_name}' to close to '{box_name}'\nRange hl: {range_hl}\n")
                        if range_buf <= threshold_size:
                            print(f"LINE: '{tpl_name}' to close to '{box_name}'\nRange buf: {range_buf}\n")
    for key in keys_to_delete_lines:
        if key in tp_lines:
            del tp_lines[key]

    if print_statements:
        print(f"Altered boxes: {boxes}\n\nTP Lines: {tp_lines}\n---------------")

    return boxes, tp_lines
