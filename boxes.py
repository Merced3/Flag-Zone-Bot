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

def get(candle_data, num_boxes=5):
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'], unit='ms')
        candle_data.set_index('timestamp', inplace=True)

    candle_data.sort_index(inplace=True)
    unique_dates = sorted(set(candle_data.index.date), reverse=True)

    if unique_dates[0] == pd.Timestamp('today').date():
        unique_dates = unique_dates[1:]

    resistances = []
    supports = []
    DAYS = config["PAST_DAYS"]

    for current_date in unique_dates:
        day_data = candle_data[candle_data.index.date == current_date]

        # Find resistances (highs)
        if len(resistances) < num_boxes:
            daily_high = day_data['high'].max()
            high_idx = day_data['high'].idxmax()
            high_pos = candle_data.index.get_loc(high_idx)

            if len(day_data.loc[high_idx:]) > 1:
                next_candle = day_data.loc[high_idx:].iloc[1]
                # Use open for red candle and close for green candle
                next_close_after_high = next_candle['open'] if next_candle['open'] > next_candle['close'] else next_candle['close']
            else:
                current_candle = day_data.loc[high_idx]
                # Use open for red candle and close for green candle
                next_close_after_high = current_candle['open'] if current_candle['open'] > current_candle['close'] else current_candle['close']

            resistances.append((high_pos, daily_high, next_close_after_high))

        # Find supports (lows)
        if len(supports) < num_boxes:
            daily_low = day_data['low'].min()
            low_idx = day_data['low'].idxmin()
            low_pos = candle_data.index.get_loc(low_idx)

            if len(day_data.loc[low_idx:]) > 1:
                next_candle = day_data.loc[low_idx:].iloc[1]
                # Use close for red candle and open for green candle
                next_close_after_low = next_candle['close'] if next_candle['open'] > next_candle['close'] else next_candle['open']
            else:
                current_candle = day_data.loc[low_idx]
                # Use close for red candle and open for green candle
                next_close_after_low = current_candle['open'] if current_candle['open'] < current_candle['close'] else current_candle['close']

            supports.append((low_pos, daily_low, next_close_after_low))

        if len(resistances) >= num_boxes and len(supports) >= num_boxes:
            break
    #boxes made
    boxes = {f'resistance_{i+1}': box for i, box in enumerate(resistances)}
    boxes.update({f'support_{i+1}': box for i, box in enumerate(supports)})
    print(f"\nBasic Boxes: {boxes}")
    #for _ in range(2):
    boxes = correct_too_big_small_boxes(candle_data, boxes)
    boxes = remove_zones_that_are_too_close(boxes)
    
    boxes = correct_bleeding_boxes(boxes)
    #boxes = old_resistance_becomes_new_support(boxes)
    return boxes

def remove_zones_that_are_too_close(boxes):
    print(f"\n---------------------\nRemoving Boxes that are too close to each other:")
    corrected_boxes = boxes.copy()
    keys_to_delete = []

    # Sorting from newer to older, for 'boxes' the way we can tell that is by the larger the 'index', the newer it is.
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0], reverse=True)
    print(f"sorted_boxes: {sorted_boxes}")

    # if any box is too close to other boxes, remove it
    for i in range(len(sorted_boxes)):
        box_name1, (index1, high_low_1, buffer1) = sorted_boxes[i]
        for j in range(i + 1, len(sorted_boxes)):
            box_name2, (index2, high_low_2, buffer2) = sorted_boxes[j]

            buffers_range = abs(buffer1 - buffer2)
            high_low_range = abs(high_low_1 - high_low_2)
            high_low_buffer_range = abs(high_low_1 - buffer2)
            high_low_buffer_range_2 = abs(high_low_2 - buffer1)

            if (buffers_range <= BOX_SIZE_THRESHOLDS[1]) or (high_low_range<= BOX_SIZE_THRESHOLDS[1]) or (high_low_buffer_range<= BOX_SIZE_THRESHOLDS[1]) or (high_low_buffer_range_2 <= BOX_SIZE_THRESHOLDS[1]):
                print(f"\nbox = {box_name2}\nBuffers: {buffer1}, {buffer2}\nDifference: {abs(buffer1 - buffer2)}")
                keys_to_delete.append(box_name2 if index1 > index2 else box_name1)

    for key in keys_to_delete:
        if key in corrected_boxes:
            del corrected_boxes[key]

    print(f"\nCorrectly Sized after processing: {corrected_boxes}\n---------------------\n")  
    return corrected_boxes

def remove_obsolete_zones(boxes):
    print(f"\n---------------------\nRemoving Boxes that are obsolete:")
    newest_resistance = (None, -1)  # Store box name and index
    newest_support = (None, -1)  # Store box name and index
    found_obsolete_zones = [False, False]  # Flag to track if any obsolete zones were found, the 2 falses mean resistance and support are found or not
    obsolete_keys = []

    # Identify the newest resistance and support zones
    for box_name, (index, high_low_of_day, buffer) in boxes.items():
        if 'resistance' in box_name and index > newest_resistance[1]:
            newest_resistance = (box_name, index, high_low_of_day, buffer)
            #print(f"Primary/Newest Resistance Zone: {newest_resistance}")
        elif 'support' in box_name and index > newest_support[1]:
            newest_support = (box_name, index, high_low_of_day, buffer)
            #print(f"Primary/Newest Support Zone: {newest_support}")

    # Remove old support zones that are above the newest one
    for box_name, (index, low_of_day, higher_buffer) in boxes.items():
        if 'support' in box_name and box_name != newest_support[0]:
            #print(f"{boxes[newest_support[0]][1]},    {box_name}: {low_of_day}, {higher_buffer}")
            if boxes[newest_support[0]][1] < low_of_day:
                found_obsolete_zones[1] = True
                #print(f"    {boxes[newest_support[0]][1]} < {low_of_day}, {box_name} removed")
                obsolete_keys.append(box_name)

    # Flags to track if obsolete resistance and support boxes were found
    found_obsolete_resistance = any('resistance' in key for key in obsolete_keys)
    found_obsolete_support = any('support' in key for key in obsolete_keys)

    # Delete obsolete zones
    for key in obsolete_keys:
        if key in boxes:
            del boxes[key]

    # Print messages based on the found obsolete boxes
    if found_obsolete_resistance and found_obsolete_support:
        print(f"Found obsolete boxes in both resistance and support...\nDeleted Boxes: {obsolete_keys}\nFiltered Obsolete Boxes: {boxes}\n---------------------")
    elif found_obsolete_resistance:
        print(f"Obsolete boxes are found for resistance but none for support...\nDeleted Boxes: {obsolete_keys}\nFiltered Obsolete Boxes: {boxes}\n---------------------")
    elif found_obsolete_support:
        print(f"Obsolete boxes are found for support but none for resistance...\nDeleted Boxes: {obsolete_keys}\nFiltered Obsolete Boxes: {boxes}\n---------------------")
    else:
        print("No obsolete boxes are found...\nPassing Boxes to next filter.\n---------------------")

    print(f"")
    return boxes

def correct_bleeding_boxes(boxes):
    print(f"\n---------------------\nResizing Boxes that are Bleeding into each other:")
    corrected_boxes = boxes.copy()
    
    #sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0], reverse=True)
    #for run in range(2):  # Run the entire process twice
        #print(f"Check Run {run + 1}") #i want it to [print 'check run 1', 'check run 2']
    keys_to_delete = []
        
    sorted_boxes = sorted(corrected_boxes.items(), key=lambda x: x[1][0], reverse=True)
        
    for i, (box_name1, box1) in enumerate(sorted_boxes):
        box1_high, box1_low = max(box1[1], box1[2]), min(box1[1], box1[2])
            
        for box_name2, box2 in sorted_boxes[i + 1:]:
            box2_high, box2_low = max(box2[1], box2[2]), min(box2[1], box2[2])

            # Check for any crossover between the high and low values of both boxes
            if (box1_low <= box2_high <= box1_high) or (box1_low <= box2_low <= box1_high) or \
            (box2_low <= box1_high <= box2_high) or (box2_low <= box1_low <= box2_high):
                box_to_delete = box_name1 if box1[0] < box2[0] else box_name2
                keys_to_delete.append(box_to_delete)
                print(f"Deleting {box_to_delete} due to bleeding with {box_name1 if box_to_delete != box_name1 else box_name2}")

    # Remove boxes identified for deletion
    for key in keys_to_delete:
        if key in corrected_boxes:
            del corrected_boxes[key]

    print(f"Corrected Boxes after processing: {corrected_boxes}\n---------------------\n")
    return corrected_boxes

def old_resistance_becomes_new_support(boxes):
    print(f"\n---------------------\nRenaming boxes:")
    # Separate resistance and support boxes
    resistance_boxes = {k: v for k, v in boxes.items() if 'resistance' in k}
    support_boxes = {k: v for k, v in boxes.items() if 'support' in k}
    print(f"Resistance Zones: {resistance_boxes}\nSupport Zones: {support_boxes}")
    # Prepare a list to hold the keys of resistances that will become supports
    resistances_to_convert = []

    # Check each resistance box to see if it should become a support box
    for r_key, (r_idx, r_top, r_next_close) in resistance_boxes.items():
        # Skip if r_top is None
        if r_top is None:
            continue

        # Check against every support box
        for s_key, (s_idx, s_top, s_bottom) in support_boxes.items():
            # Skip if s_top or s_bottom is None
            if s_top is None or s_bottom is None:
                continue

            # If the top of the resistance is below the top or bottom of a support, we convert it
            if r_top <= s_top or r_top <= s_bottom:
                resistances_to_convert.append(r_key)
                break  # Break the inner loop as we only need one instance to convert
    print(f"Zones to convert: {resistances_to_convert}")
    # Convert the identified resistances to supports
    for r_key in resistances_to_convert:
        # Determine the new support number
        new_support_num = len(support_boxes) + 1

        # Rename and renumber the resistance box as a support box
        new_key = f'support_{new_support_num}'
        support_boxes[new_key] = resistance_boxes[r_key]

        # Remove from resistance boxes
        del resistance_boxes[r_key]

    # Merge the updated resistance and support boxes
    updated_boxes = {**resistance_boxes, **support_boxes}
    print(f"Correctly named after processing: {updated_boxes}\n---------------------\n") 
    return updated_boxes

def correct_too_big_small_boxes(candle_data, boxes):
    print(f"\n---------------------\nResizing Boxes that are too Small or Big:")

    print(f"Boxes Before Processing: {boxes}\n")
    if not isinstance(candle_data.index, pd.DatetimeIndex):
        candle_data['timestamp'] = pd.to_datetime(candle_data['timestamp'])
        candle_data.set_index('timestamp', inplace=True)

    corrected_boxes = {}
    for box_name, (box_candle_pos, keep_value, change_value) in boxes.items():
        box_type = 'resistance' if 'resistance' in box_name else 'support'
        box_date = candle_data.index[box_candle_pos].date()
        day_data = candle_data[candle_data.index.date == box_date]
        day_before_data = candle_data[candle_data.index.date == box_date - pd.Timedelta(days=1)]
        day_after_data = candle_data[candle_data.index.date == box_date + pd.Timedelta(days=1)]

        height = abs(keep_value - change_value)
        if BOX_SIZE_THRESHOLDS[0] <= height <= BOX_SIZE_THRESHOLDS[1]:
            corrected_boxes[box_name] = boxes[box_name]
            continue

        min_value, max_value = sorted([keep_value - BOX_SIZE_THRESHOLDS[1], keep_value - BOX_SIZE_THRESHOLDS[0]]) if box_type == 'resistance' else sorted([keep_value + BOX_SIZE_THRESHOLDS[0], keep_value + BOX_SIZE_THRESHOLDS[1]])

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
                    continue
                break
            else:
                continue
            break
        else:
            print(f"{box_name} Has No Suitable Candle Within Threshold")
            corrected_value = change_value
            corrected_pos = box_candle_pos

        corrected_pos = min(corrected_pos, box_candle_pos)
        corrected_boxes[box_name] = (corrected_pos, keep_value, corrected_value)

    print(f"Correctly Sized Boxes: {corrected_boxes}\n---------------------\n")
    return corrected_boxes