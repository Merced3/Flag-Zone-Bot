# web_dash/charts/live_chart.py
from __future__ import annotations
import re
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from dash import dcc

from utils.json_utils import read_config
from paths import get_ema_path
from utils.ema_utils import load_ema_json
from storage.viewport import load_viewport, get_timeframe_bounds
from storage.objects.io import read_current_objects

_BAR_MINUTES_RE = re.compile(r"(\d+)\s*[mM]")

def _bar_minutes(tf: str) -> int:
    m = _BAR_MINUTES_RE.match(str(tf))
    return int(m.group(1)) if m else 1  # default to 1 minute if weird tf

def _coerce_pos_int(val, default: int) -> int:
    try:
        n = int(float(val))
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default

def _pick_bars_limit(timeframe: str, default: int = 600) -> int:
    cfg = read_config("LIVE_BARS") or {}
    # tolerate casing differences: "15M" vs "15m"
    v = cfg.get(timeframe)
    if v is None:
        v = cfg.get(timeframe.upper())
    if v is None:
        v = cfg.get(timeframe.lower())
    return _coerce_pos_int(v, default)

def generate_live_chart(timeframe: str):
    symbol = read_config("SYMBOL")
    bars_limit = _pick_bars_limit(timeframe, default=600)
    tf_min = _bar_minutes(timeframe)

    # read preferred anchor from config; default to 'latest' for dev convenience
    anchor = str(read_config("LIVE_ANCHOR")).lower()  # 'now' | 'latest'

    # If we have any parts at all, capture their latest ts for a fallback
    _min_ts, latest_parts_ts, _nparts = get_timeframe_bounds(
        timeframe=timeframe,
        include_days=False,
        include_parts=True,
    )

    # choose t1
    if anchor == "latest" and latest_parts_ts is not None:
        t1 = latest_parts_ts
    else:
        t1 = pd.Timestamp.now()

    t0 = t1 - pd.Timedelta(minutes=bars_limit * tf_min)

    # parts-only read for Live
    df_candles, df_objects = load_viewport(
        symbol=symbol, 
        timeframe=timeframe,
        t0_iso=t0.isoformat(),
        t1_iso=t1.isoformat(),
        include_days=False,    # LIVE = parts only
        include_parts=True,
    )

    # fallback: if 'now' produced 0 rows but we DO have parts, re-anchor to latest
    if df_candles.empty and latest_parts_ts is not None and anchor != "latest":
        t1 = latest_parts_ts
        t0 = t1 - pd.Timedelta(minutes=bars_limit * tf_min)
        df_candles, _ = load_viewport(
            symbol=symbol,
            timeframe=timeframe,
            t0_iso=t0.isoformat(),
            t1_iso=t1.isoformat(),
            include_days=False,
            include_parts=True,
        )
    
    # still empty? render a placeholder cleanly
    if df_candles.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"Live {timeframe} Chart - No candle data",
            xaxis_title="", yaxis_title="", height=700
        )
        return dcc.Graph(figure=fig, style={"height": "700px"})

    # Normalize/clean + tail + EMAs
    df_candles = df_candles.copy()
    df_candles["timestamp"] = pd.to_datetime(df_candles["ts"], errors="coerce")
    df_candles = df_candles.dropna(subset=["timestamp"]).sort_values("timestamp")
    if bars_limit: # keep only last N bars to be safe even if viewport gave us more
        df_candles = df_candles.tail(bars_limit).reset_index(drop=True)
    
    """ Ignoring EMA's until candles are plotted. """

    # --- plot (Can re-enable EMAs later) ---
    fig = go.Figure()
    candlex = np.array(df_candles["timestamp"].dt.to_pydatetime(), dtype=object)
    fig.add_trace(go.Candlestick(
        x=candlex,
        open=df_candles["open"], high=df_candles["high"],
        low=df_candles["low"], close=df_candles["close"],
        name="Price",
    ))

    # Layout: key on the right, focus y-range on candles only
    visible_min = float(df_candles["low"].min())
    visible_max = float(df_candles["high"].max())
    span = max(visible_max - visible_min, 0.0)
    pad = max(span * 0.05, 0.05)

    fig.update_layout(
        title=f"Live {timeframe} Chart",
        xaxis_title='Time',
        yaxis_title='Price',
        xaxis=dict(type="date"),
        xaxis_rangeslider_visible=False,
        uirevision=f"live-{timeframe}",
        yaxis2=dict(overlaying="y", matches="y", showticklabels=False, showgrid=False),
        legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),  # legend outside on the right
        height=700,
    )
    fig.update_yaxes(range=[visible_min - pad, visible_max + pad], autorange=False)
    fig.update_traces(cliponaxis=True, selector=dict(type="scatter"))

    return dcc.Graph(figure=fig, style={"height": "700px"})
