def correct_bleeding_boxes(boxes):
    corrected_boxes = boxes.copy()
    keys_to_delete = []
    # Sort the boxes by their index (assumes lower index means newer)
    sorted_boxes = sorted(boxes.items(), key=lambda x: x[1][0])
    #print(f"-----\nSorted boxes: {sorted_boxes}\n")
    #num=1
    for i, (box_name1, box1) in enumerate(sorted_boxes):
        for box_name2, box2 in sorted_boxes[i + 1:]:
            # Skip if same type of box
            if ('resistance' in box_name1) == ('resistance' in box_name2):
                continue
            # Check for bleeding
            if (box1[1] <= box2[2] <= box1[2]) or (box2[1] <= box1[2] <= box2[2]):
                priority_zone = box1 if box1[0] > box2[0] else box2
                secondary_zone = box2 if priority_zone is box1 else box1
                #print(f"{num}) Bleeding detected between {box_name1} and {box_name2}")
                #print(f"{box1[1]} <= {box2[2]} <= {box1[2]}\nbox1[1] <= box2[2] <= box1[2]" if box1[1] <= box2[2] <= box1[2] else f"{box2[1]} <= {box1[2]} <= {box2[2]}\nbox2[1] <= box1[2] <= box2[2]")
                #print(f"box_name1 = {box_name1}: {box1}\nbox_name2 = {box_name2}: {box2}")
                #print(f"priority_zone: {priority_zone}")
                #print(f"secondary_zone: {secondary_zone}")
                if priority_zone is box1:
                    priority_zone_name = box_name1
                else:
                    priority_zone_name = box_name2
                if 'support' in priority_zone_name:
                    # Priority zone is support, secondary is resistance
                    new_top = min(secondary_zone[1], secondary_zone[2])
                    edited_name = 'e_' + priority_zone_name
                    corrected_boxes[edited_name] = (priority_zone[0], priority_zone[1], new_top)
                    del corrected_boxes[priority_zone_name]
                    #print(f"Updated priority box (support): {corrected_boxes[box_name1 if priority_zone is box1 else box_name2]}\n")
                else:
                    # Priority zone is resistance, secondary is support
                    new_bottom = max(secondary_zone[1], secondary_zone[2])
                    edited_name = 'e_' + priority_zone_name
                    corrected_boxes[edited_name] = (priority_zone[0], priority_zone[1], new_bottom)
                    del corrected_boxes[priority_zone_name]
                    #print(f"Updated priority box (resistance): {corrected_boxes[box_name1 if priority_zone is box1 else box_name2]}\n")

                keys_to_delete.append(box_name2 if priority_zone is box1 else box_name1)
                #print(f"Marked for deletion: {box_name2 if priority_zone is box1 else box_name1}")
            #num=num+1

    # Remove secondary zones that bled into priority zones
    for key in keys_to_delete:
        if key in corrected_boxes:
            del corrected_boxes[key]
    #print(f"Corrected boxes after processing: {corrected_boxes}\n-----")
    return corrected_boxes