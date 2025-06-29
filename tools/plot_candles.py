# tools/plot_candles.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from matplotlib.patches import Rectangle
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import mplfinance as mpf
from shared_state import print_log, safe_read_json
import tkinter as tk
from tkinter import ttk
import pandas as pd
from objects import display_json_update, get_final_timeline_step

BASE_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = BASE_DIR / "storage"
CANDLES_CSV = STORAGE_DIR / "SPY_15_minute_candles.csv"
DISPLAY_PATH = STORAGE_DIR / "objects" / "objects.json"
WINDOW_DAYS = 5

color_map = {
    'resistance': 'red',
    'resistance ceiling': 'red',
    'support': 'green',
    'support floor': 'green',
    'PDHL': 'blue',
    'swings_high': 'orange',
    'swings_low': 'purple',
    'trendline': 'gold',
}


# --- Load data ---
df = pd.read_csv(CANDLES_CSV)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df.set_index('timestamp', inplace=True)

unique_days = sorted(df.index.normalize().unique())
total_days = len(unique_days)

# --- Tkinter window and navigation logic ---
class CandleWindow:
    def __init__(self, root, df, unique_days):
        self.root = root
        self.df = df
        self.unique_days = unique_days
        self.window_days = WINDOW_DAYS
        self.start_idx = 0
        self.end_idx = min(self.window_days, len(self.unique_days))
        self.show_objects = False
        self.timeline_step = 0
        display_json_update(self.timeline_step)
        self.timeline_step_limit = get_final_timeline_step()

        
        self.fig = Figure(figsize=(12, 6), dpi=100)
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        
        # Setting up window
        zones_frame = tk.Frame(root)
        zones_frame.pack(side=tk.BOTTOM)

        # *** ---- Zone handling buttons ---- ***

        self.overlays_on_off_btn = tk.Button(zones_frame, text="Overlays: OFF", command=self.overlay_switch, state=tk.NORMAL)
        self.overlays_on_off_btn.pack(side=tk.LEFT)

        self.step_fwd_btn = tk.Button(zones_frame, text="Step +1", command=self.step_object_forward, state=tk.DISABLED) # this button doesn't do exactly what i want it to do right now
        self.step_fwd_btn.pack(side=tk.LEFT)

        self.step_back_btn = tk.Button(zones_frame, text="Step -1", command=self.step_object_backward, state=tk.DISABLED) # same
        self.step_back_btn.pack(side=tk.LEFT)

        self.show_all_btn = tk.Button(zones_frame, text="Show All Steps", command=self.show_all_steps, state=tk.DISABLED)
        self.show_all_btn.pack(side=tk.LEFT)
        
        # *** --- Candle Stick View Controls --- ***
        nav_frame = tk.Frame(root)
        nav_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Left navigation buttons
        left_nav = tk.Frame(nav_frame)
        left_nav.pack(side=tk.LEFT)

        self.prev_btn = tk.Button(left_nav, text="<< Prev Window", command=self.prev_window)
        self.prev_btn.pack(side=tk.LEFT, padx=2)

        self.prev_1d_btn = tk.Button(left_nav, text="<< Prev 1d", command=self.prev_1d)
        self.prev_1d_btn.pack(side=tk.LEFT, padx=2)
        
        # Center (slider + status)
        center_nav = tk.Frame(nav_frame)
        center_nav.pack(side=tk.LEFT, expand=True, fill=tk.X)

        self.scrollbar = ttk.Scale(center_nav, from_=0, to=total_days-self.window_days, orient="horizontal", command=self.scrollbar_move)
        self.scrollbar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.status = tk.Label(center_nav, text="", anchor="center", width=30)
        self.status.pack(side=tk.LEFT, padx=5)

        # Right navigation buttons
        right_nav = tk.Frame(nav_frame)
        right_nav.pack(side=tk.RIGHT)

        self.next_1d_btn = tk.Button(right_nav, text="Next 1d >>", command=self.next_1d)
        self.next_1d_btn.pack(side=tk.LEFT, padx=2)

        self.next_btn = tk.Button(right_nav, text="Next Window>>", command=self.next_window)
        self.next_btn.pack(side=tk.LEFT, padx=2)
        
        self.render_candle_chart()

    def on_close(self):
        self.root.destroy()  # Closes the Tk window

    def render_candle_chart(self):
        days = self.unique_days[self.start_idx:self.end_idx]
        
        # Data window
        mask = (self.df.index.normalize() >= days[0]) & (self.df.index.normalize() <= days[-1])
        window_df = self.df.loc[mask].copy()
        window_df['day'] = window_df.index.normalize()
        window_df = window_df.reset_index()
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        # Draw alternating day backgrounds
        unique_days_in_window = window_df['day'].unique()
        for i, day in enumerate(unique_days_in_window):
            day_df = window_df[window_df['day'] == day]
            if day_df.empty:
                print_log(f"    Skipping day {day}, empty.")
                continue
            left = day_df.index.min()
            right = day_df.index.max()
            ax.axvspan(left-0.5, right+0.5, color="#f0f0f0" if i % 2 else "white", alpha=0.5, zorder=0)

        # Plot zones/levels
        if self.show_objects:
            all_objects = safe_read_json(DISPLAY_PATH, default=[])
            visible_start = self.df.index.get_loc(window_df['timestamp'].iloc[0])
            visible_end = visible_start + len(window_df)
            visible_ymin, visible_ymax = ax.get_ylim()
            local_window_width = visible_end - visible_start

            for obj in all_objects:
                
                if obj['type'] == 'structure' and 'points' in obj:
                    # Check if any of the structure's points are in visible range
                    if all(visible_start <= x <= visible_end for x, _ in obj['points']):
                        self.draw_object(ax, obj, visible_start, local_window_width)
                    continue

                if "left" not in obj:
                    continue

                obj_x = obj["left"]

                # Show if it's before window, but overlaps Y axis
                if obj_x <= visible_start:
                    if "top" in obj and "bottom" in obj:
                        if obj["bottom"] <= visible_ymax and obj["top"] >= visible_ymin:
                            self.draw_object(ax, obj, visible_start, local_window_width)
                    elif "y" in obj:
                        if visible_ymin <= obj["y"] <= visible_ymax:
                            self.draw_object(ax, obj, visible_start, local_window_width)
                
                # Show object if it's within visible window
                if obj_x <= visible_end:
                    self.draw_object(ax, obj, visible_start, local_window_width)

        # Draw candlesticks
        window_df.set_index('timestamp', inplace=True)
        candle_high = window_df['high'].max()
        candle_low = window_df['low'].min()
        ax.set_ylim(candle_low * 0.995, candle_high * 1.005)

        mpf.plot(window_df, ax=ax, type='candle', style='charles', datetime_format='%Y-%m-%d', 
                volume=False, xrotation=20, warn_too_much_data=10000)

        ax.set_title(f"{days[0].strftime('%Y-%m-%d')} to {days[-1].strftime('%Y-%m-%d')} ({len(window_df)} candles)")
        self.canvas.draw()
        self.status.config(text=f"Showing days {self.start_idx+1} to {self.end_idx} of {len(self.unique_days)} Days")

    def draw_object(self, ax, obj, visible_start, local_window_width):
        color = color_map.get(obj['type'], 'gray')
        global_left = obj.get("left", 0)
        local_left = max(0, global_left - visible_start)
        
        # Clip width if object starts before visible_start
        visible_width = local_window_width - max(0, -local_left)
        if visible_width <= 0:
            return  # Nothing to draw
        
        # Draw Zone (rectangle)
        if 'top' in obj and 'bottom' in obj:
            height = obj['top'] - obj['bottom']
            zone_width = abs(local_left - visible_width)
            rect = Rectangle((local_left, obj['bottom']), 
                             zone_width, height,
                            linewidth=1.5, edgecolor=color, 
                            facecolor=color, alpha=0.15, zorder=1)
            ax.add_patch(rect)

        # Draw Level (horizontal line)
        elif 'y' in obj:
            ax.hlines(obj['y'],
                      xmin=local_left,
                      xmax= visible_width,
                      colors=color, linestyles='dashed', 
                      linewidth=1, zorder=1)
        
        # Draw Structures (Trends and Swings)
        elif obj['type'] == 'structure' and 'points' in obj:
            if not obj.get("points"):
                return # failsafe
            xs, ys = zip(*obj['points'])
            xs = [x - visible_start for x in xs]

            subtype = obj.get('subtype', 'structure')
            color = color_map.get(subtype, 'gray')
            label = subtype.replace("_", " ").title()

            # Avoid duplicate labels
            existing_labels = [line.get_label() for line in ax.lines]
            ax.plot(xs, ys, linestyle='dotted', linewidth=2, marker='o', color=color, zorder=2,
                    label=label if label not in existing_labels else None)

    def prev_1d(self):
        if self.start_idx > 0:
            self.start_idx -= 1
            self.end_idx = min(self.start_idx + self.window_days, len(self.unique_days))
            self.render_candle_chart()
            self.scrollbar.set(self.start_idx)

    def next_1d(self):
        if self.end_idx < len(self.unique_days):
            self.start_idx += 1
            self.end_idx = min(self.start_idx + self.window_days, len(self.unique_days))
            self.render_candle_chart()
            self.scrollbar.set(self.start_idx)
            
    def prev_window(self):
        if self.start_idx > 0:
            self.start_idx = max(0, self.start_idx - self.window_days)
            self.end_idx = self.start_idx + self.window_days
            self.render_candle_chart()
            self.scrollbar.set(self.start_idx)
        
    def next_window(self):
        if self.end_idx < total_days:
            self.start_idx = min(total_days - self.window_days, self.start_idx + self.window_days)
            self.end_idx = self.start_idx + self.window_days
            self.render_candle_chart()
            self.scrollbar.set(self.start_idx)
        
    def scrollbar_move(self, value):
        value = int(float(value))
        self.start_idx = value
        self.end_idx = min(self.start_idx + self.window_days, total_days)
        self.render_candle_chart()

    def step_button_manager(self):
        if self.timeline_step <= 0: # were at the start
            self.timeline_step = 0
            self.step_fwd_btn.config(state=tk.NORMAL)
            self.step_back_btn.config(state=tk.DISABLED)
            self.show_all_btn.config(state=tk.NORMAL)
        
        elif self.timeline_step >= self.timeline_step_limit:
            self.timeline_step = self.timeline_step_limit
            self.step_fwd_btn.config(state=tk.DISABLED)
            self.step_back_btn.config(state=tk.NORMAL)
            self.show_all_btn.config(state=tk.DISABLED)

        elif 0 < self.timeline_step < self.timeline_step_limit:
            self.step_fwd_btn.config(state=tk.NORMAL)
            self.step_back_btn.config(state=tk.NORMAL)
            self.show_all_btn.config(state=tk.NORMAL)

    def step_object_forward(self):
        if self.timeline_step < self.timeline_step_limit:
            self.timeline_step += 1
            display_json_update(self.timeline_step)
        self.step_button_manager()
        self.render_candle_chart()

    def step_object_backward(self):
        if self.timeline_step > 0:
            self.timeline_step -= 1
            display_json_update(self.timeline_step)
        self.step_button_manager()
        self.render_candle_chart()

    def show_all_steps(self):
        display_json_update("all")
        self.timeline_step = self.timeline_step_limit
        self.step_button_manager()
        self.render_candle_chart()

    def overlay_switch(self):
        self.show_objects = not self.show_objects
        self.timeline_step = 0
        self.render_candle_chart()

        if self.show_objects:
            self.overlays_on_off_btn.config(text="Overlays: ON")
            display_json_update(self.timeline_step)
            self.step_button_manager()
        else:
            self.overlays_on_off_btn.config(text="Overlays: OFF")
            self.step_fwd_btn.config(state=tk.DISABLED)
            self.step_back_btn.config(state=tk.DISABLED)
            self.show_all_btn.config(state=tk.DISABLED)

if __name__ == "__main__":
    root = tk.Tk()
    root.title(f"15-Minute Candles Visualizer ({WINDOW_DAYS} Days Scrollable Window)")
    candle_win = CandleWindow(root, df, unique_days)
    root.mainloop()
