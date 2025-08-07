# web_dash/charts/live_chart.py
import pandas as pd
import plotly.graph_objs as go
from dash import dcc
from utils.ema_utils import load_ema_json
from paths import get_ema_path, CANDLE_LOGS
from utils.json_utils import read_config

def generate_live_chart(timeframe):
    # Load candle data from log file
    candle_path = CANDLE_LOGS.get(timeframe)
    try:
        df_candles = pd.read_csv(candle_path)
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
    
    # Load EMAs
    ema_path = get_ema_path(timeframe)
    emas = load_ema_json(ema_path)
    df_emas = pd.DataFrame(emas) if emas else None

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
                    x=df_emas['x'],
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
