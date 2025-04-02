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
from shared_state import indent, print_log, safe_read_json

df_15_min = None
df_2_min = None
boxes = None
tp_lines = None
LOGS_DIR = Path(__file__).resolve().parent / 'logs'
should_close = False # Signal for closing window, `root.quit()` and `root.destroy()`

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

root = None
canvas = None

# Global control flags
pause_event = threading.Event()
pause_event.set()
next_candle_event = threading.Event()

def setup_global_chart(tk_root, tk_canvas, indent_lvl=0):
    global root, canvas, boxes, tp_lines
    root = tk_root
    canvas = tk_canvas
    print_log(f"{indent(indent_lvl)}[setup_global_chart] setting global root and canvas")
   
def setup_global_boxes(_boxes, _tp_lines, indent_lvl=0):
    global boxes, tp_lines
    boxes = _boxes
    tp_lines = _tp_lines
    print_log(f"{indent(indent_lvl)}[setup_global_boxes] setting global boxes and tp_lines")

def update_chart_periodically(root, canvas, boxes, tp_lines, symbol, log_file_path, indent_lvl=0):
    global df_2_min, should_close
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
        else:
            # Reset flag as data is now available
            is_waiting_for_data = True

            # Check if there is new data based on the timestamp
            if last_timestamp is None or new_df.index[-1] > last_timestamp:
                df_2_min = new_df
                last_timestamp = new_df.index[-1]
                # Schedule the update_plot function to run on the main thread
                root.after(0, lambda: update_plot(canvas, df_2_min, boxes, tp_lines, symbol, "2-min", indent_lvl))

        if should_close:
            print_log(f"{indent(indent_lvl)}[chart_visualization.py, UCP] Closing the GUI...")
            root.quit()
            break
        # Short sleep to prevent excessive CPU usage
        time.sleep(0.5)  # Sleep for half a second, adjust as needed

def read_log_to_df(log_file_path, indent_lvl=0):
    # Convert string path to Path object for easy handling
    log_file_path = Path(log_file_path)

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

def update_plot(canvas, df, boxes, tp_lines, symbol, timescale_type, indent_lvl=0):
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
    y_min = df[['low']].min().min() - BOX_SIZE_THRESHOLDS[0]  # Find the minimum low price in the DataFrame
    y_max = df[['high']].max().max() + BOX_SIZE_THRESHOLDS[0]  # Find the maximum high price in the DataFrame
    ax.set_ylim(y_min, y_max)  # Set the y-axis limits

    if boxes:
        for box_name, box_details in boxes.items():
            left_idx, top, bottom = box_details
            
            if 'support' in box_name:
                box_color = 'green'
            elif 'resistance' in box_name:
                box_color = 'red'
            else: # PDHL
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
            if markers_file_path.stat().st_size > 0:  # Check that the file is not empty
                with open(markers_file_path, 'r') as f:
                    markers = json.load(f)

                for marker in markers:
                    ax.scatter(marker['x'], marker['y'], **marker['style'])
            else:
                print_log(f"{indent(indent_lvl)}[UP] markers.json file is empty.")
        except FileNotFoundError:
            print_log(f"{indent(indent_lvl)}[UP] No markers.json file found.")

        # <<<<<<<<<Check and plot EMAs HERE>>>>>>>>>>
        ema_plotted = False
        ema_file_path = Path(__file__).resolve().parent / 'EMAs.json'
        
        emas = safe_read_json(ema_file_path, default=[], indent_lvl=indent_lvl+1, location="update_plot()")  # Safely read the JSON file
        
        if emas:
            x_values = [entry['x'] for entry in emas]
            for ema_config in EMA:
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

        # <<<<<<<<<Check and plot Bull/Bear Flags HERE>>>>>>>>>>
        lines_file_path = Path(__file__).resolve().parent / 'line_data.json'
        lines_data = safe_read_json(lines_file_path, default={"active_flags": [], "completed_flags": []}, indent_lvl=indent_lvl+1, location="update_plot()")

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
            print_log(f"{indent(indent_lvl)}[UP] line_data.json file is empty or invalid.")

    # <<<<<<<<<Check and plot 'Take Profit dotted lines' HERE>>>>>>>>>>
    if tp_lines:
        try: 
            for tpl_name, tpl_details in tp_lines.items():
                line_color = None
                if 'support' in tpl_name:
                    line_color = 'green'
                elif 'resistance' in tpl_name:
                    line_color = 'red'
                else: # PDHL or whatever else I add
                    line_color = 'blue'
                
                # Get X and Y positions
                _x, y = tpl_details
                x = 0 if timescale_type == "2-min" else _x
                x_end = len(df.index)
                #the line should be straight Horizontal accross the screen
                ax.plot([x, x_end], [y, y], color=line_color, linewidth=1, linestyle=':') # ':' makes the line dotted
        except FileNotFoundError:
            print_log(f"{indent(indent_lvl)}[UP] No TAKE PROFITS line data found.")

    # Redraw the canvas
    canvas.draw()
    canvas.figure.savefig(f"{symbol}_{timescale_type}_chart.png")

def refresh_15_min_candle_stick_data(df, indent_lvl=0):
    """Updates global df_15_min and triggers a plot update."""
    global df_15_min
    df_15_min = df
    update_15_min(indent_lvl=indent_lvl)

def update_15_min(print_statements=False, indent_lvl=0):
    global canvas, root, df_15_min, boxes, tp_lines
    if print_statements:
        print_log(f"{indent(indent_lvl)}[update_15_min] function called")
    if root and df_15_min is not None:
        try:
            # Post the update task to the Tkinter main loop
            root.after(0, lambda: update_plot(canvas, df_15_min, boxes, tp_lines, SYMBOL, "15-min", indent_lvl))
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[update_15_min] Error updating 15-min chart: {e}")
    else:
        print_log(f"{indent(indent_lvl)}[update_15_min] GUI or data not initialized.")

def update_2_min(print_statements=False, indent_lvl=0):
    global root, df_2_min, boxes, tp_lines
    if print_statements:
        print_log(f"{indent(indent_lvl)}[update_2_min] function called")
    if root and df_2_min is not None:
        try:
            # Post the update task to the Tkinter main loop
            root.after(0, lambda: update_plot(canvas, df_2_min, boxes, tp_lines, SYMBOL, "2-min", indent_lvl))
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[update_2_min] Error updating 2-min chart: {e}")
    else:
        print_log(f"{indent(indent_lvl)}[update_2_min] GUI or data not initialized.")

def plot_candles_and_boxes(df_15, symbol, df_2=None, indent_lvl=0):
    global df_15_min, df_2_min, should_close
    df_15_min, df_2_min = df_15, df_2

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
    update_plot(canvas, df_15_min, boxes, tp_lines, symbol, "15-min", indent_lvl+1)

    # Button to switch to 15-min data
    button_15_min = tk.Button(root, text="15 min", 
                              command=lambda: update_plot(canvas, df_15_min, boxes, tp_lines, symbol, "15-min", indent_lvl+1))
    button_15_min.pack(side=tk.LEFT)

    # Button to switch to 2-min data
    button_2_min = tk.Button(root, text="2 min", 
                             command=lambda: update_plot(canvas, df_2_min, boxes, tp_lines, symbol, "2-min", indent_lvl+1))
    button_2_min.pack(side=tk.LEFT)

    # Start the background task for updating the chart
    log_file_path = LOGS_DIR / f"{symbol}_2M.log"  # Replace with your actual log file path
    #how do we say wait until this file exists if it doesn't exists?
    update_thread = threading.Thread(target=update_chart_periodically, args=(root, canvas, boxes, tp_lines, symbol, log_file_path, indent_lvl+1), daemon=True)
    update_thread.start()

    # Start the Tkinter event loop
    tk.mainloop()

def initiate_shutdown():
    global should_close, boxes, df_15_min, df_2_min, tp_lines
    should_close = True
    boxes = None
    df_2_min = None
    df_15_min = None
    tp_lines = None


# EVERYTHING BELOW IS FOR FRONTEND USE
def setup_global_chart_frontend(tk_canvas):
    """Link the canvas from the frontend to chart_visualization."""
    global canvas
    canvas = tk_canvas

def update_plot_frontend(df, symbol, timescale_type, indent_lvl=0):
    """Update the chart using the provided data and timeframe."""
    global canvas, boxes, tp_lines

    if canvas is None:
        print_log(f"{indent(indent_lvl)}[ERROR] Canvas is not set up. Call setup_global_chart() first.")
        return

    # Ensure DataFrame index is DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    canvas.figure.clf()  # Clear previous plots
    ax = canvas.figure.add_subplot(111)

    # Generate candlestick plot
    mpf.plot(df, ax=ax, type='candle', style='charles', datetime_format='%Y-%m-%d', volume=False)

    # Plot additional features like boxes, EMAs, and markers
    if boxes:
        for box_name, box_details in boxes.items():
            left_idx, top, bottom = box_details
            rect = Rectangle((left_idx, bottom), len(df.index) - left_idx, top - bottom, edgecolor='green', alpha=0.3)
            ax.add_patch(rect)

    # Draw take profit lines
    if tp_lines:
        for tpl_name, tpl_details in tp_lines.items():
            x, y = tpl_details
            ax.axhline(y, color='blue', linestyle='--')

    # Refresh canvas
    canvas.draw()

def update_2_min_frontend():
    """Update the chart for the 2-minute timeframe."""
    global df_2_min
    if df_2_min is not None:
        update_plot(df_2_min, SYMBOL, "2-min")

def update_15_min_frontend():
    """Update the chart for the 15-minute timeframe."""
    global df_15_min
    if df_15_min is not None:
        update_plot(df_15_min, SYMBOL, "15-min")




# EVERYTHING BELOW IS FOR THE SIMULATOR FOR TESTING
def update_15_min_test_box_enviroment(df_15m=None, Boxes=None, tp_lines=None, print_statements=False, indent_lvl=0):
    global canvas, root  # Removed df_15_min, boxes, and tp_lines from globals

    if print_statements:
        print_log(f"{indent(indent_lvl)}[update_15_min] function called")
    
    # Check if root is initialized
    if root:
        try:
            # Post the update task to the Tkinter main loop
            root.after(0, lambda: update_plot(canvas, df_15m, Boxes, tp_lines, SYMBOL, "15-min", indent_lvl+1))
        except Exception as e:
            print_log(f"{indent(indent_lvl)}[update_15_min] Error updating 15-min chart: {e}")
    else:
        print_log(f"{indent(indent_lvl)}[update_15_min] GUI or root not initialized.")

def simulate_candles_one_by_one(indent_lvl, candle_log_source, candle_log_destination, ema_log_source, ema_log_destination, update_interval=1):
    global should_close, pause_event, next_candle_event, df_2_min
    
    # Read the candles from the source file
    with open(candle_log_source, 'r') as source_file:
        candles = source_file.readlines()

    # Read the EMAs from the EMA source file
    with open(ema_log_source, 'r') as ema_source_file:
        ema_data = json.load(ema_source_file)

    # Initialize the EMA destination file with an empty list if it doesn't exist
    if not Path(ema_log_destination).exists():
        with open(ema_log_destination, 'w') as ema_dest_file:
            json.dump([], ema_dest_file)

    # Read the existing EMAs from the destination file (if any)
    with open(ema_log_destination, 'r') as ema_dest_file:
        try:
            current_ema_data = json.load(ema_dest_file)
        except json.JSONDecodeError:
            current_ema_data = []  # Initialize with an empty list if the file is empty or has invalid JSON
    print_log(f"{indent(indent_lvl)}[Simulating Candle's One-By-One Starting]")
    candle_index = 0
    while candle_index < len(candles):
        if should_close:
            print_log(f"{indent(indent_lvl)}[chart_visualization.py, UCP] Closing the GUI...")
            root.quit()
            break
        
        pause_event.wait()  # Wait here if the simulation is paused
        if next_candle_event.is_set():
            next_candle_event.clear()  # Clear after processing one candle if set

        # Write the current candle to the destination file
        candle = candles[candle_index]
        with open(candle_log_destination, 'a') as dest_file:
            dest_file.write(candle)
            dest_file.flush()

        # Write the corresponding EMA entry to the EMA destination file
        if candle_index < len(ema_data):
            ema_entry = ema_data[candle_index]
            current_ema_data.append(ema_entry)  # Append the new EMA entry to the existing data

            # Write the entire list back to the EMA destination file in correct JSON array format
            with open(ema_log_destination, 'w') as ema_dest_file:
                json.dump(current_ema_data, ema_dest_file, indent=4)  # Write the entire list with indentation for readability

        # Update the plot with the new candle data
        df_2_min = read_log_to_df(candle_log_destination, indent_lvl+1)
        root.after(0, lambda: update_plot(canvas, df_2_min, boxes, tp_lines, SYMBOL, "2-min", indent_lvl+1))

        # Increment to the next candle and EMA entry
        candle_index += 1
        if not next_candle_event.is_set():  # Only sleep if not stepping through one candle
            time.sleep(update_interval)
    print_log(f"{indent(indent_lvl)}[chart_visualization.py, SCOBO] Closing the GUI Because end of candle list, check PNG image...")
    root.quit()

def setup_simulation_environment(boxes, tp_lines, interval, indent_lvl=0):
    global should_close, root, canvas, button_pause, button_resume, button_next_candle
    should_close = False
    root = tk.Tk()
    root.title("Candlestick Chart Simulation")
    print_log(f"{indent(indent_lvl)}[Simulator Tkinter Enviroment Starting]")
    # Create matplotlib figure and canvas
    fig = Figure(figsize=(12, 6), dpi=100)
    canvas = FigureCanvasTkAgg(fig, master=root)
    canvas_widget = canvas.get_tk_widget()
    canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

    setup_global_chart(root, canvas, indent_lvl)
    setup_global_boxes(boxes, tp_lines, indent_lvl)
    
    # Load the path configurations
    candle_log_source = LOGS_DIR / 'all_candles.log'
    candle_log_destination = LOGS_DIR / f"{SYMBOL}_2M.log"
    ema_log_source = LOGS_DIR / 'all_EMAs.json'
    ema_log_destination = 'EMAs.json'
    # Buttons
    button_pause = tk.Button(root, text="Pause", command=pause_simulation)
    button_pause.pack(side=tk.LEFT)

    button_resume = tk.Button(root, text="Resume", command=resume_simulation)
    button_resume.pack(side=tk.LEFT)
    button_resume.config(state="disabled")  # Start disabled

    button_next_candle = tk.Button(root, text="Next Candle", command=next_candle)
    button_next_candle.pack(side=tk.LEFT)
    button_next_candle.config(state="disabled")  # Start disabled

    simulate_thread = threading.Thread(target=simulate_candles_one_by_one, args=(indent_lvl+1, candle_log_source, candle_log_destination, ema_log_source, ema_log_destination, interval), name="simulate_candles_one_by_one()")
    simulate_thread.start()

    root.mainloop()

def pause_simulation():
    global button_pause, button_resume, button_next_candle
    pause_event.clear()  # Stop the simulation loop
    button_pause.config(state="disabled")
    button_resume.config(state="normal")
    button_next_candle.config(state="normal")

def resume_simulation():
    global button_pause, button_resume, button_next_candle
    pause_event.set()  # Allow the simulation to continue
    button_pause.config(state="normal")
    button_resume.config(state="disabled")
    button_next_candle.config(state="disabled")

def next_candle():
    global button_pause, button_resume, button_next_candle
    next_candle_event.set()  # Allow one candle to be processed
    pause_event.set()  # Temporarily resume the loop for one iteration
    root.after(100, lambda: pause_event.clear())  # Re-pause after a short delay to allow one cycle
    button_resume.config(state="normal")
    button_next_candle.config(state="normal")
    button_pause.config(state="disabled")
