# chart_visualization.py
import tkinter as tk
from PIL import ImageGrab
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Rectangle
import json
import threading
import time
from utils.json_utils import read_config
from utils.data_utils import load_from_csv
from shared_state import indent, print_log, safe_read_json
from paths import CANDLE_LOGS, MARKERS_PATH, EMAS_PATH, LINE_DATA_PATH, OBJECTS_PATH, STORAGE_DIR, SPY_15_MINUTE_CANDLES_PATH

should_close = False # Signal for closing window, `root.quit()` and `root.destroy()`
root = None
canvas = None
df_15_min = None
df_2_min = None
button_2_min = None

def load_recent_15m_candles():
    df = load_from_csv(SPY_15_MINUTE_CANDLES_PATH)
    if df is None or df.empty:
        print_log("[load_recent_15m_candles] No 15M data found.")
        return pd.DataFrame()
    
    df = df.sort_values('timestamp')
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    last_day = df['timestamp'].dt.normalize().max()
    five_days_ago = last_day - pd.Timedelta(days=5)
    mask = df['timestamp'] >= five_days_ago
    df = df.loc[mask]
    df.set_index('timestamp', inplace=True)
    return df

def setup_global_chart(tk_root, tk_canvas, indent_lvl=0):
    global root, canvas
    root = tk_root
    canvas = tk_canvas
    print_log(f"{indent(indent_lvl)}[setup_global_chart] setting global root and canvas")

def update_chart_periodically(root, canvas, symbol, log_file_path, indent_lvl=0):
    global df_2_min, should_close, button_2_min
    last_timestamp = None  # Initialize with None
    is_waiting_for_data = True # Flag to check if waiting for initial data

    while True:
        if should_close:
            root.quit()  # This will stop the mainloop
            root.destroy()  # This will destroy all widgets, effectively closing the window
            break
        # Read the latest data from the log file
        new_df = read_log_to_df(log_file_path, indent_lvl)

        # Check if DataFrame is empty (no data)
        if new_df.empty:
            if is_waiting_for_data:
                print_log(f"{indent(indent_lvl)}[chart_visualization.py, UCP] Waiting for live candles...")
                is_waiting_for_data = False  # Reset flag after first announcement

            if button_2_min:
                button_2_min.config(state=tk.DISABLED)
        else:
            # Reset flag as data is now available
            is_waiting_for_data = True

            if button_2_min:
                button_2_min.config(state=tk.NORMAL)

            # Check if there is new data based on the timestamp
            if last_timestamp is None or new_df.index[-1] > last_timestamp:
                df_2_min = new_df
                last_timestamp = new_df.index[-1]
                # Schedule the update_plot function to run on the main thread
                root.after(0, lambda: update_plot(canvas, df_2_min, symbol, "2-min", indent_lvl))

        if should_close:
            print_log(f"{indent(indent_lvl)}[chart_visualization.py, UCP] Closing the GUI...")
            root.quit()
            break
        # Short sleep to prevent excessive CPU usage
        time.sleep(0.5)  # Sleep for half a second, adjust as needed

def read_log_to_df(log_file_path, indent_lvl=0):
    # Convert string path to Path object for easy handling
    #log_file_path = Path(log_file_path)

    # Ensure the directory exists
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    # If the file does not exist, create an empty file
    if not log_file_path.exists():
        log_file_path.touch()
        print_log(f"{indent(indent_lvl)}[RLTD] Created new log file: {log_file_path}")
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
                        print_log(f"{indent(indent_lvl)}[RLTD] Line in log file missing 'timestamp': {line}")
                except json.JSONDecodeError as e:
                    print_log(f"{indent(indent_lvl)}[RLTD] Error decoding line in log file: {line}\nError:\n{e}")

            if not data:  # Check if no valid data was found
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            return df
    except Exception as e:
        print_log(f"{indent(indent_lvl)}[RLTD] Error reading log file: {e}")
        return pd.DataFrame()

def update_plot(canvas, df, symbol, timescale_type, indent_lvl=0):
    # Ensure the DataFrame index is a DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    # Determine the number of data points
    num_data_points = len(df)

    # Clear the existing figure and create new axes
    canvas.figure.clf()
    ax = canvas.figure.add_subplot(111)

    # Generate the mplfinance plot
    dt_format = '%Y-%m-%d' if timescale_type == '15-min' else '%H:%M'
    mpf.plot(df, ax=ax, type='candle', style='charles', datetime_format=dt_format, volume=False, warn_too_much_data=num_data_points + 1)

    # After plotting the candlesticks, set y-axis limits to match the candlestick range 
    y_min = df[['low']].min().min() - 0.10
    y_max = df[['high']].max().max() + 0.10
    ax.set_ylim(y_min, y_max)  # Set the y-axis limits

    # <<<<<<<<< ZONES/LEVELS >>>>>>>>>>
    # Calculate visible X range for 15-min chart
    if timescale_type == "15-min":
        df = df.copy()
        df = df.sort_index()
        df_window_start = df.index[0]
        df_window_end = df.index[-1]
        visible_start_idx = df.index.get_loc(df_window_start)
        visible_end_idx = df.index.get_loc(df_window_end)
    
    all_objects = safe_read_json(OBJECTS_PATH, default=[])
    for obj in all_objects:
        color = {
            'support': 'green',
            'support floor': 'green',
            'resistance': 'red',
            'resistance ceiling': 'red',
            'PDHL': 'blue'
        }.get(obj.get('type'), 'gray')

        # ZONES
        if 'top' in obj and 'bottom' in obj:
            height = obj['top'] - obj['bottom']
            zone_left = obj.get("left", 0)

            if timescale_type == "2-min":
                rect = Rectangle(
                    (0, obj['bottom']), len(df), height,
                    edgecolor=color, facecolor=color, alpha=0.15, zorder=2
                )
                ax.add_patch(rect)

            elif timescale_type == "15-min":
                # Only show zones within view window
                if visible_start_idx <= zone_left <= visible_end_idx:
                    local_left = zone_left - visible_start_idx
                    rect = Rectangle(
                        (local_left, obj['bottom']), 
                        visible_end_idx - visible_start_idx,
                        height,
                        edgecolor=color, facecolor=color, alpha=0.15, zorder=2
                    )
                    ax.add_patch(rect)

        # LEVELS
        elif 'y' in obj:
            level_x_start = 0
            level_x_end = len(df) if timescale_type == "2-min" else visible_end_idx - visible_start_idx
            ax.hlines(obj['y'], xmin=level_x_start, xmax=level_x_end, colors=color, linestyles='dashed', linewidth=1, zorder=1)

    if timescale_type == "2-min":
        # <<<<<<<<< MARKERS >>>>>>>>>>
        try:
            if MARKERS_PATH.stat().st_size > 0:  # Check that the file is not empty
                with open(MARKERS_PATH, 'r') as f:
                    markers = json.load(f)
                for marker in markers:
                    ax.scatter(marker['x'], marker['y'], **marker['style'])
            else:
                print_log(f"{indent(indent_lvl)}[UP] {MARKERS_PATH} file is empty.")
        except FileNotFoundError:
            print_log(f"{indent(indent_lvl)}[UP] No {MARKERS_PATH} file found.")

        # <<<<<<<<< EMAs >>>>>>>>>>
        ema_plotted = False
        emas = safe_read_json(EMAS_PATH, default=[], indent_lvl=indent_lvl+1, location="update_plot()")
        if emas:
            x_values = [entry['x'] for entry in emas]
            for ema_config in read_config("EMAS"):
                window, color = ema_config
                ema_values = [entry[str(window)] for entry in emas if str(window) in entry]
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
        else:
            print_log(f"{indent(indent_lvl)}[UP] EMA data file is empty or invalid. Skipping EMA plot.")
            # Optionally, plot a dummy line to show a waiting message
            ax.plot([], [], ' ', label="Waiting for EMAs...")
            ax.legend(loc='upper left')

        # <<<<<<<<< Bull/Bear Flags >>>>>>>>>>
        lines_data = safe_read_json(LINE_DATA_PATH, default={"active_flags": [], "completed_flags": []}, indent_lvl=indent_lvl+1, location="update_plot()")

        if lines_data:
            for group, linestyle in [('active_flags', ':'), ('completed_flags', '-')]:
                flags = lines_data.get(group, [])
                for flag in flags:
                    if not all(k in flag for k in ('type', 'point_1', 'point_2')):
                        continue
                    p1, p2 = flag['point_1'], flag['point_2']
                    if None in (p1['x'], p1['y'], p2['x'], p2['y']):
                        continue

                    color = 'blue' if flag['type'] == 'bull' else 'black'
                    ax.plot([p1['x'], p2['x']], [p1['y'], p2['y']], color=color, linewidth=1, linestyle=linestyle)
        else:
            print_log(f"{indent(indent_lvl)}[UP] {LINE_DATA_PATH} file is empty or invalid.")

    # Redraw the canvas
    canvas.draw()
    file_path = STORAGE_DIR / f"{symbol}_{timescale_type}_chart.png"
    canvas.figure.savefig(file_path)

def refresh_15_min_candle_stick_data(indent_lvl=0):
    """Updates global df_15_min and triggers a plot update."""
    global df_15_min
    df_15_min = load_recent_15m_candles()
    update_15_min(indent_lvl=indent_lvl)

def update_15_min(print_statements=False, indent_lvl=0):
    global canvas, root
    if print_statements:
        print_log(f"{indent(indent_lvl)}[update_15_min] function called")
    if root and df_15_min is not None:
        try:
            # Post the update task to the Tkinter main loop
            root.after(0, lambda: update_plot(canvas, df_15_min, read_config("SYMBOL"), "15-min", indent_lvl))
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[update_15_min] Error updating 15-min chart: {e}")
    else:
        print_log(f"{indent(indent_lvl)}[update_15_min] GUI or data not initialized.")

def update_2_min(print_statements=False, indent_lvl=0):
    global root, df_2_min
    if print_statements:
        print_log(f"{indent(indent_lvl)}[update_2_min] function called")
    if root and df_2_min is not None:
        try:
            # Post the update task to the Tkinter main loop
            root.after(0, lambda: update_plot(canvas, df_2_min, read_config("SYMBOL"), "2-min", indent_lvl))
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[update_2_min] Error updating 2-min chart: {e}")
    else:
        print_log(f"{indent(indent_lvl)}[update_2_min] GUI or data not initialized.")

def plot_candles_and_boxes(symbol, indent_lvl=0):
    global df_15_min, should_close, button_2_min
    df_15_min = load_recent_15m_candles()

    # Create the main Tkinter window
    root = tk.Tk()
    root.wm_title(f"Candlestick chart for {symbol}")
    should_close = False

    # Create a Figure for Matplotlib
    fig = Figure(figsize=(12, 6), dpi=100)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
    #print(f"    [plot_candles_and_boxes] Setting Global Variables for 'chart_visualization.py'")
    setup_global_chart(root, canvas, indent_lvl)
    # Initial plot with 15-minute data
    update_plot(canvas, df_15_min, symbol, "15-min", indent_lvl+1)

    # Button to switch to 15-min data
    button_15_min = tk.Button(root, text="15 min", 
                              command=lambda: update_plot(canvas, df_15_min, symbol, "15-min", indent_lvl+1))
    button_15_min.pack(side=tk.LEFT)

    # Button to switch to 2-min data
    button_2_min = tk.Button(root, text="2 min", 
                             command=lambda: update_plot(canvas, df_2_min, symbol, "2-min", indent_lvl+1))
    button_2_min.pack(side=tk.LEFT)

    # Start the background task for updating the chart
    log_file_path = CANDLE_LOGS.get("2M")
    update_thread = threading.Thread(
        target=update_chart_periodically, 
        args=(root, canvas, symbol, log_file_path, indent_lvl+1),
        daemon=True
    )
    update_thread.start()

    # Start the Tkinter event loop
    tk.mainloop()

def initiate_shutdown():
    global should_close
    should_close = True

