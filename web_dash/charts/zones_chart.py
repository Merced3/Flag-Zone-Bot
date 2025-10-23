# web_dash/charts/zones_chart.py
from __future__ import annotations
from dash import dcc
import plotly.graph_objs as go
import pandas as pd
from utils.json_utils import read_config
from storage.viewport import load_viewport

DEFAULT_DAYS = 15  # UI can override later

def generate_zones_chart(timeframe: str = "15M", days: int = DEFAULT_DAYS):
    symbol = read_config("SYMBOL")
    t1 = pd.Timestamp.now()
    t0 = t1 - pd.Timedelta(days=days)

    df_candles, df_objects = load_viewport(
        symbol=symbol,
        timeframe=timeframe,
        t0_iso=t0.isoformat(),
        t1_iso=t1.isoformat(),
    )
    
    if df_candles.empty:
        fig = go.Figure().update_layout(title=f"Zones {timeframe} — no data", height=700)
        return dcc.Graph(figure=fig, style={"height": "700px"})

    fig = go.Figure()

    if not df_candles.empty:
        fig.add_trace(go.Candlestick(
            x=pd.to_datetime(df_candles["ts"]),
            open=df_candles["open"],
            high=df_candles["high"],
            low=df_candles["low"],
            close=df_candles["close"]
        ))

        # Pads based on visible candle range
        ymin = float(df_candles["low"].min())
        ymax = float(df_candles["high"].max())
        pad = (ymax - ymin) * 0.05
        fig.update_yaxes(range=[ymin - pad, ymax + pad])

    # (Optional) draw zones/levels from df_objects later

    fig.update_layout(
        title=f"{symbol} — Zones ({timeframe})",
        xaxis_rangeslider_visible=False,
        uirevision="zones"
    )
    return dcc.Graph(figure=fig, style={"height": "700px"})
