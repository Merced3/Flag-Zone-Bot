# chart_visualization.py
import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Rectangle

df_15_min = None
df_2_min = None
boxes = None

def update_plot(canvas, df, boxes, symbol, timescale_type):
    # Ensure the DataFrame index is a DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

    # Clear the existing figure and create new axes
    canvas.figure.clf()
    ax = canvas.figure.add_subplot(111)

    # Define the style for mplfinance
    s = mpf.make_mpf_style(base_mpf_style='charles', rc={'figure.facecolor': 'lightgray'})

    # Prepare the 13-EMA plot if it's a 2-minute chart
    apds = []
    #if timescale_type == "2-min":
        #df['13_ema'] = df['close'].ewm(span=13, adjust=False).mean()
        #ema_plot = mpf.make_addplot(df['13_ema'], color='yellow', width=1)
        #apds.append(ema_plot)

    # Generate the mplfinance plot
    mpf.plot(df, ax=ax, type='candle', style=s, datetime_format='%Y-%m-%d', addplot=apds, volume=False)

    # Add boxes to the plot using the previous working method
    for box_name, box_details in boxes.items():
        left_idx, top, bottom = box_details
        box_color = 'green' if 'support' in box_name else 'red'
        if timescale_type == "15-min":
            # Calculate the x position of the right edge of the box
            last_index_position = df.index.get_loc(df.index[-1])  # Get the index position of the last timestamp
            width = last_index_position - left_idx + 1 
            rect = Rectangle((left_idx, bottom), width, top - bottom, edgecolor=box_color, facecolor=box_color, alpha=0.5, fill=True)
        else:  # 2-min
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

    # Start the Tkinter event loop
    tk.mainloop()