# calculate_avg_trim_distance.py, this is specifically used for the strat simulator AKA `flag_simulator.py`
import os
import json
import numpy as np  # For easy calculation of average, min, max

# Define the path to the test_data directory
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
TEST_DATA_DIR = os.path.join(LOGS_DIR, 'test_data')

def get_avg_trim_from_folder(folder_name, show_print_statements=False):
    """
    Calculate the average trim size from a specific folder inside the test_data directory.

    Args:
        folder_name (str): The name of the folder containing the markers.json file.

    Returns:
        dict: A dictionary containing the average, minimum, and maximum trim sizes, or a message if no trims are found.
    """
    # Construct the path to the markers.json file inside the specified folder
    markers_file_path = os.path.join(TEST_DATA_DIR, folder_name, 'markers.json')
    
    # Check if the folder exists and the markers.json file exists
    if not os.path.exists(markers_file_path):
        if show_print_statements:
            print(f"[GATFF] Folder '{folder_name}' or markers.json file does not exist.")
        return
    
    # Load the markers.json file
    with open(markers_file_path, 'r') as file:
        markers = json.load(file)

    # Initialize variables to track order states and trim sizes
    current_order = None
    trim_sizes = []

    # Iterate through markers to find buy and corresponding trims
    for marker in markers:
        event_type = marker.get('event_type')
        y_value = marker.get('y')
        percentage = marker.get('percentage')

        if event_type == 'buy':
            # Start tracking a new order
            current_order = {'buy_y': y_value, 'is_positive': False}

        elif event_type == 'trim' and current_order and not current_order['is_positive']:
            # If the next event after buy is a trim, consider the order as positive
            current_order['is_positive'] = True
            trim_size = abs(current_order['buy_y'] - y_value)
            trim_sizes.append(trim_size)

        elif event_type == 'sell' and current_order:
            # Finish tracking the order
            current_order = None

    # Calculate average, minimum, and maximum of trim sizes
    if trim_sizes:
        avg_trim_size = np.mean(trim_sizes)
        min_trim_size = np.min(trim_sizes)
        max_trim_size = np.max(trim_sizes)

        if show_print_statements:
            print(f"\nAnalyzed {len(trim_sizes)} trim sizes in folder '{folder_name}':")
            print(f"Average Trim Size for 20%: {avg_trim_size:.4f}")
            print(f"Minimum Trim Size for 20%: {min_trim_size:.4f}")
            print(f"Maximum Trim Size for 20%: {max_trim_size:.4f}")
        
        return {
            'average': avg_trim_size,
            'minimum': min_trim_size,
            'maximum': max_trim_size
        }
    else:
        if show_print_statements:
            print(f"No valid trim sizes found in folder '{folder_name}'.")
        return {
            'average': None,
            'minimum': None,
            'maximum': None
        }

def list_test_data_folders():
    # Check if the directory exists
    if not os.path.exists(TEST_DATA_DIR):
        print(f"Directory {TEST_DATA_DIR} does not exist.")
        return
    
    # Initialize lists to store trim sizes
    trim_sizes = []
    all_orders = []
    
    # List all subdirectories inside the test_data folder
    folders = [folder for folder in os.listdir(TEST_DATA_DIR) if os.path.isdir(os.path.join(TEST_DATA_DIR, folder))]
    
    # Print each folder name
    print("Folders inside test_data:")
    for folder in folders:
        print(f" - {folder}")
    
    # Print the total number of folders
    print(f"\nTotal number of folders: {len(folders)}\n")


    for folder in folders:
        markers_file_path = os.path.join(TEST_DATA_DIR, folder, 'markers.json')
        # Check if markers.json file exists
        if not os.path.exists(markers_file_path):
            continue

        # Load the markers.json file
        with open(markers_file_path, 'r') as file:
            markers = json.load(file)

        # Initialize variables to track order states
        current_order = None

        # Iterate through markers to find buy and corresponding trims
        for marker in markers:
            event_type = marker.get('event_type')
            y_value = marker.get('y')
            percentage = marker.get('percentage')

            if event_type == 'buy':
                # Start tracking a new order
                current_order = {'buy_y': y_value, 'is_positive': False}

            elif event_type == 'trim' and current_order and not current_order['is_positive']:
                # If the next event after buy is a trim, consider the order as positive
                current_order['is_positive'] = True
                trim_size = abs(current_order['buy_y'] - y_value)
                trim_percentage = percentage
                trim_sizes.append(trim_size)
                current_order['trim_size'] = trim_size
                current_order['trim_percentage'] = trim_percentage  # Store the percentage with the trim
                
                # Print the trim size and its percentage
                print(f"Trim size: {trim_size:.4f}, Trim percentage: {trim_percentage:.2f}%")

            elif event_type == 'sell' and current_order:
                # Finish tracking the order
                if not current_order['is_positive']:
                    # Order is negative if no trim was found before sell
                    current_order['status'] = 'negative'
                else:
                    current_order['status'] = 'positive'
                
                all_orders.append(current_order)
                current_order = None

    # Calculate average, minimum, and maximum of trim sizes
    if trim_sizes:
        avg_trim_size = np.mean(trim_sizes)
        min_trim_size = np.min(trim_sizes)
        max_trim_size = np.max(trim_sizes)

        print(f"\nAnalyzed {len(trim_sizes)} trim sizes:")
        print(f"Average Trim Size for 20%: {avg_trim_size:.4f}")
        print(f"Minimum Trim Size for 20%: {min_trim_size:.4f}")
        print(f"Maximum Trim Size for 20%: {max_trim_size:.4f}")
    else:
        print("No valid trim sizes found.")

if __name__ == "__main__":
    get_avg_trim_from_folder("8_2_2024")
    #list_test_data_folders()
