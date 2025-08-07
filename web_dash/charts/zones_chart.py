# web_dash/charts/zones_chart.py
from dash import dcc
import plotly.graph_objs as go
import pandas as pd
from paths import SPY_15_MINUTE_CANDLES_PATH
from shared_state import safe_read_json
from paths import OBJECTS_PATH

def generate_zones_chart():
    df = pd.read_csv(SPY_15_MINUTE_CANDLES_PATH)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    full_df = df.copy()
    df['timestamp_str'] = df['timestamp'].dt.strftime('%m/%d %H:%M')

    full_df = full_df.reset_index(drop=True)
    full_df['global_index'] = range(len(full_df))
    full_index_to_timestamp = dict(zip(full_df['global_index'], full_df['timestamp'].dt.strftime('%m/%d %H:%M')))
    
    # --- Show only last N unique trading days ---
    WINDOW_DAYS = 5  # or 10 if you prefer
    df['day'] = df['timestamp'].dt.normalize()
    unique_days = sorted(df['day'].unique())

    if len(unique_days) > WINDOW_DAYS:
        recent_days = unique_days[-WINDOW_DAYS:]
        df = df[df['day'].isin(recent_days)]

    # Reset index and build timestamp mapping AFTER filtering
    df = df.reset_index(drop=True)
   
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df['timestamp_str'],
        open=df['open'], high=df['high'],
        low=df['low'], close=df['close'],
        name="15M Candles"
    ))

    objects = safe_read_json(OBJECTS_PATH, default=[])
    for obj in objects:
        left_idx = obj.get('left')
        start_left = full_index_to_timestamp.get(left_idx)
        end_right = df['timestamp_str'].iloc[-1]

        if start_left not in df['timestamp_str'].values:
            start_left = df['timestamp_str'].iloc[0]
            
        # Levels
        if 'y' in obj:
            fig.add_shape(
                type="line",
                x0=start_left,
                x1=end_right,
                y0=obj['y'], 
                y1=obj['y'],
                line=dict(color="Green" if obj['type'] == "support" else "Red", width=2, dash="dot"),
                xref='x', yref='y'
            )
        # Zones
        if 'top' in obj and 'bottom' in obj:
            fig.add_shape(
                type="rect",
                x0=start_left,
                x1=end_right,
                y0=obj['bottom'], 
                y1=obj['top'],
                fillcolor="LightGreen" if obj['type'] == "support" else "LightCoral",
                opacity=0.3, line_width=0
            )

    fig.update_layout(
        xaxis=dict(
            type='category',
            tickangle=-45,
            tickmode='auto',
            tickfont=dict(size=8),
            showgrid=False,
        ),
        xaxis_rangeslider_visible=False
    )

    # Calculate min/max from visible candle prices only (excluding zones)
    visible_min = df['low'].min()
    visible_max = df['high'].max()
    padding = (visible_max - visible_min) * 0.05  # 5% buffer

    fig.update_yaxes(
        range=[visible_min - padding, visible_max + padding]
    )

    return dcc.Graph(figure=fig, style={"height": "700px"})
