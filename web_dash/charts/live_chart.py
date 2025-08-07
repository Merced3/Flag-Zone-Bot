# web_dash/charts/live_chart.py
import pandas as pd
import plotly.graph_objs as go
from dash import dcc
from utils.ema_utils import load_ema_json
from paths import get_ema_path, CANDLE_LOGS, LINE_DATA_PATH, MARKERS_PATH
from utils.json_utils import read_config
from shared_state import safe_read_json


def generate_live_chart(timeframe):
    # Load candle data from log file
    candle_path = CANDLE_LOGS.get(timeframe)
    # print(f"[generate_live_chart] Loading candles from: {candle_path}")
    try:
        df_candles = pd.read_json(candle_path, lines=True)
        if df_candles.empty or 'timestamp' not in df_candles.columns:
            raise ValueError("No candle data found.")
        df_candles['timestamp'] = pd.to_datetime(df_candles['timestamp'])
    except Exception as e:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Live {timeframe} Chart - No candle data",
            xaxis_title="",
            yaxis_title="",
            height=700
        )
        return dcc.Graph(figure=empty_fig, style={"height": "700px"})
    
    # print(f"[generate_live_chart] Loaded {len(df_candles)} candles for {timeframe} timeframe.")

    # This is for later, just saving this for whenever we need it
    #flag_data = safe_read_json(LINE_DATA_PATH)
    #marker_data = safe_read_json(MARKERS_PATH)

    # Load EMAs
    ema_path = get_ema_path(timeframe)
    emas = load_ema_json(ema_path)
    df_emas = pd.DataFrame(emas) if emas else None

    if df_emas is not None:
        # Step 1: Create a mapping from global index → timestamp
        df_candles = df_candles.reset_index(drop=True)
        candle_count = len(df_candles)
        start_index = df_emas['x'].min()
        end_index = df_emas['x'].max()

        # This assumes your last `candle_count` candles correspond to global index range
        # e.g. candle 0 maps to global_idx = total_global - candle_count
        global_offset = df_emas['x'].max() - (candle_count - 1)
        df_candles['global_idx'] = range(global_offset, global_offset + candle_count)

        # Step 2: Map EMA x values to timestamps
        index_map = dict(zip(df_candles['global_idx'], df_candles['timestamp']))
        df_emas['timestamp'] = df_emas['x'].map(index_map)

        # Step 3: Drop any rows without mapped timestamp (out of range)
        df_emas.dropna(subset=['timestamp'], inplace=True)


    fig = go.Figure()

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df_candles['timestamp'],
        open=df_candles['open'],
        high=df_candles['high'],
        low=df_candles['low'],
        close=df_candles['close'],
        name='Price'
    ))

    # Overlay EMAs
    ema_settings = read_config("EMAS")
    if df_emas is not None:
        for window, color in ema_settings:
            col = str(window)
            if col in df_emas.columns:
                fig.add_trace(go.Scatter(
                    x=df_emas['timestamp'],
                    y=df_emas[col],
                    mode='lines',
                    name=f'EMA {window}',
                    line=dict(color=color.lower())
                ))

    fig.update_layout(
        title=f"Live {timeframe} Chart",
        xaxis_title='Time',
        yaxis_title='Price',
        xaxis_rangeslider_visible=False
    )

    return dcc.Graph(figure=fig, style={"height": "700px"})
