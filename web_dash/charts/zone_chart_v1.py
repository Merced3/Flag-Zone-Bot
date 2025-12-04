# web_dash/charts/zones_chart_v1.py
from __future__ import annotations
from dash import dcc
import plotly.graph_objs as go
import pandas as pd
from utils.json_utils import read_config
from storage.viewport import load_viewport, days_window

def generate_zones_chart(timeframe: str = "15M", days: int = 15):
    symbol = read_config("SYMBOL")
    t0, t1, picked = days_window(timeframe, days) # optional: keep only those picked dates in the final df if you want hard enforcement

    df_candles, df_objects = load_viewport(
        symbol=symbol, timeframe=timeframe,
        t0_iso=t0, t1_iso=t1,
        include_days=True, include_parts=False,
    )
    
    if df_candles.empty:
        fig = go.Figure().update_layout(title=f"Zones {timeframe} — no data", height=700)
        return dcc.Graph(figure=fig, style={"height": "700px"})

    df = df_candles.copy()
    ts = pd.to_datetime(df["ts"], errors="coerce")
    df["d"] = ts.dt.tz_localize(None).dt.date
    last_days = sorted(df["d"].unique())[-days:]
    df = df[df["d"].isin(last_days)]

    fig = go.Figure([go.Candlestick(
        x=pd.to_datetime(df["ts"]),
        open=df["open"], high=df["high"], low=df["low"], close=df["close"]
    )])
    ymin, ymax = float(df["low"].min()), float(df["high"].max())
    pad = (ymax - ymin) * 0.05
    fig.update_yaxes(range=[ymin - pad, ymax + pad])

    fig.update_layout(
        title=f"{symbol} — Zones ({timeframe})",
        xaxis_rangeslider_visible=False,
        uirevision="zones"
    )
    return dcc.Graph(figure=fig, style={"height": "700px"})
