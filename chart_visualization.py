# chart_visualization.py
import tkinter as tk
from PIL import ImageGrab
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
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
should_close = False

config_path = Path(__file__).resolve().parent / 'config.json'#
def read_config():
    with config_path.open('r') as f:
        config = json.load(f)
    return config
config = read_config()
SYMBOL = config["SYMBOL"]
IS_REAL_MONEY = config["REAL_MONEY_ACTIVATED"]
BOX_SIZE_THRESHOLDS = config["BOX_SIZE_THRESHOLDS"]
EMA = config["EMAS"]

def update_chart_periodically(root, canvas, boxes, symbol, log_file_path):
    global df_2_min, should_close
    last_timestamp = None  # Initialize with None
    is_waiting_for_data = True # Flag to check if waiting for initial data

    while True:
        if should_close:
            root.quit()  # This will stop the mainloop
            root.destroy()  # This will destroy all widgets, effectively closing the window
            break
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

        if should_close:
            print("Closing the GUI...")
            root.quit()
            break
        # Short sleep to prevent excessive CPU usage
        time.sleep(0.5)  # Sleep for half a second, adjust as needed

def read_log_to_df(log_file_path):
    # Convert string path to Path object for easy handling
    log_file_path = Path(log_file_path)

    # Ensure the directory exists
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # If the file does not exist, create an empty file
    if not log_file_path.exists():
        log_file_path.touch()
        print(f"Created new log file: {log_file_path}")
        return pd.DataFrame()
    # Read the log file and return a DataFrame
    try:
        with log_file_path.open('r') as file:
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
        print(f"Error reading log file: {e}")
        return pd.DataFrame()

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

    # After plotting the candlesticks, set y-axis limits to match the candlestick range 
    y_min = df[['low']].min().min() - BOX_SIZE_THRESHOLDS[0] # Find the minimum low price in the DataFrame
    y_max = df[['high']].max().max() + BOX_SIZE_THRESHOLDS[0] # Find the maximum high price in the DataFrame
    ax.set_ylim(y_min, y_max)  # Set the y-axis limits

    # Add boxes to the plot using the previous working method
    for box_name, box_details in boxes.items():
        left_idx, top, bottom = box_details
         
        if 'support' in box_name:
            box_color = 'green'
        elif 'resistance' in box_name:
            box_color = 'red'
        else:
            box_color = 'blue'
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

    if timescale_type == "2-min":
        # Check and plot markers
        markers_file_path = Path(__file__).resolve().parent / 'markers.json'
        try:
            with open(markers_file_path, 'r') as f:
                markers = json.load(f)

            for marker in markers:
                ax.scatter(marker['x'], marker['y'], **marker['style'])
        except FileNotFoundError:
            print("No markers.json file found.")

        lines_file_path = Path(__file__).resolve().parent / 'line_data.json'
    
        # <<<<<<<<<Check and plot EMAs HERE>>>>>>>>>>
        ema_plotted = False
        ema_file_path = Path(__file__).resolve().parent / 'EMAs.json'
        try:
            with open(ema_file_path, 'r') as f:
                emas = json.load(f)
            x_values = [entry['x'] for entry in emas]
            for ema_config in EMA:
                window, color = ema_config
                ema_values = [entry[str(window)] for entry in emas if str(window) in entry]
                
                # Check if there are EMA values to plot to avoid errors
                if ema_values:
                    ax.plot(x_values, ema_values, label=f'EMA {window}', color=color, linewidth=1)
                    ema_plotted = True

            # Conditionally add legend
            if ema_plotted:
                ax.legend(loc='upper left')
            else:
                # Plot a dummy line with no data but with a placeholder label
                ax.plot([], [], ' ', label="Waiting for EMAs...")
                ax.legend(loc='upper left')

        except FileNotFoundError:
            print("EMA data file not found.")

        try:
            with open(lines_file_path, 'r') as f:
                lines = json.load(f)

            for line in lines:
                # Determine the color based on the type of flag
                color = 'blue' if line['type'] == 'Bull' else 'black'

                # Extract the start and end points
                start_x = line['point_1']['x']
                start_y = line['point_1']['y']
                end_x = line['point_2']['x']
                end_y = line['point_2']['y']

                # Draw the line on the chart
                ax.plot([start_x, end_x], [start_y, end_y], color=color, linewidth=1)

        except FileNotFoundError:
            print("No line_data.json file found.")
    # Redraw the canvas
    canvas.draw()
    canvas.figure.savefig(f"{symbol}_{timescale_type}_chart.png")

def plot_candles_and_boxes(df_15, df_2, box_data, symbol):
    global df_15_min, df_2_min, should_close
    df_15_min, df_2_min, boxes = df_15, df_2, box_data

    # Create the main Tkinter window
    root = tk.Tk()
    root.wm_title(f"Candlestick chart for {symbol}")
    should_close = False

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

def initiate_shutdown():
    global should_close
    should_close = True