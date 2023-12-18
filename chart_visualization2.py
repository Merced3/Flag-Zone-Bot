# chart_visualization.py
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Rectangle
from pathlib import Path
import json
import threading
import time

df_15_min = None
df_2_min = None
boxes = None
LOGS_DIR = Path(__file__).resolve().parent / 'logs'

def update_chart_periodically(root, canvas, boxes, symbol, log_file_path):
    global df_2_min
    last_timestamp = None  # Initialize with None
    is_waiting_for_data = True # Flag to check if waiting for initial data

    while True:
        # Read the latest data from the log file
        new_df = read_log_to_df(log_file_path)

        # Check if DataFrame is empty (no data)
        if new_df.empty:
            if is_waiting_for_data:
                print("[chart_visualization.py] Waiting for live candles...")
                is_waiting_for_data = False  # Reset flag after first announcement
        else:
            # Reset flag as data is now available
            is_waiting_for_data = True

            # Check if there is new data based on the timestamp
            if last_timestamp is None or new_df.index[-1] > last_timestamp:
                df_2_min = new_df
                last_timestamp = new_df.index[-1]
                # Schedule the update_plot function to run on the main thread
                root.after(0, lambda: update_plot(canvas, df_2_min, boxes, symbol, "2-min"))

        # Short sleep to prevent excessive CPU usage
        time.sleep(0.5)  # Sleep for half a second, adjust as needed



def read_log_to_df(log_file_path):
    # Read the log file and return a DataFrame
    try:
        with open(log_file_path, 'r') as file:
            lines = file.readlines()
            if not lines:  # Check if the file is empty
                return pd.DataFrame()

            data = []
            for line in lines:
                try:
                    json_data = json.loads(line)
                    if 'timestamp' in json_data:
                        data.append(json_data)
                    else:
                        print("Line in log file missing 'timestamp':", line)
                except json.JSONDecodeError as e:
                    print("Error decoding line in log file:", line, "\nError:", e)

            if not data:  # Check if no valid data was found
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            return df
    except Exception as e:
        print(f"Error reading log file: {e}") #this is what im talking about, in question
        return pd.DataFrame()  # Return an empty DataFrame in case of an error

def update_plot(canvas, df, boxes, symbol, timescale_type):
    # Ensure the DataFrame index is a DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    # Clear the existing figure and create new axes
    canvas.figure.clf()
    ax = canvas.figure.add_subplot(111)

    # Generate the mplfinance plot
    mpf.plot(df, ax=ax, type='candle', style='charles', datetime_format='%Y-%m-%d', volume=False)
        
    # Add boxes to the plot using the previous working method
    for box_name, box_details in boxes.items():
        left_idx, top, bottom = box_details
        box_color = 'green' if 'support' in box_name else 'red'
        if timescale_type == "15-min":
            # Calculate the x position of the right edge of the box
            last_index_position = df.index.get_loc(df.index[-1])  # Get the index position of the last timestamp
            width = last_index_position - left_idx + 1 
            rect = Rectangle((left_idx, bottom), width, top - bottom, edgecolor=box_color, facecolor=box_color, alpha=0.5, fill=True)
        elif timescale_type == "2-min":
            # Full width for 2-min data
            width = len(df.index)
            rect = Rectangle((0, bottom), width, top - bottom, edgecolor=box_color, facecolor=box_color, alpha=0.5, fill=True)
        ax.add_patch(rect)
    # Redraw the canvas
    canvas.draw()

def plot_candles_and_boxes(df_15, df_2, box_data, symbol):
    global df_15_min, df_2_min, boxes
    df_15_min, df_2_min, boxes = df_15, df_2, box_data

    # Create the main Tkinter window
    root = tk.Tk()
    root.wm_title(f"Candlestick chart for {symbol}")

    # Create a Figure for Matplotlib
    fig = Figure(figsize=(12, 6), dpi=100)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    # Initial plot with 15-minute data
    update_plot(canvas, df_15_min, boxes, symbol, "15-min")

    # Button to switch to 15-min data
    button_15_min = tk.Button(root, text="15 min", 
                              command=lambda: update_plot(canvas, df_15_min, boxes, symbol, "15-min"))
    button_15_min.pack(side=tk.LEFT)

    # Button to switch to 2-min data
    button_2_min = tk.Button(root, text="2 min", 
                             command=lambda: update_plot(canvas, df_2_min, boxes, symbol, "2-min"))
    button_2_min.pack(side=tk.LEFT)

    # Start the background task for updating the chart
    log_file_path = LOGS_DIR / f"{symbol}_2M.log"  # Replace with your actual log file path
    #how do we say wait until this file exists if it doesn't exists?
    update_thread = threading.Thread(target=update_chart_periodically, args=(root, canvas, boxes, symbol, log_file_path), daemon=True)
    update_thread.start()

    # Start the Tkinter event loop
    tk.mainloop()