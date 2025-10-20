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
from storage.viewport import load_viewport

_BAR_MINUTES_RE = re.compile(r"(\d+)\s*[mM]")

def _bar_minutes(tf: str) -> int:
    m = _BAR_MINUTES_RE.match(tf)
    if not m:
        raise ValueError(f"Unrecognized timeframe label: {tf}")
    return int(m.group(1))

def _iso(dt: pd.Timestamp) -> str:
    # viewport wants ISO-like strings
    return pd.Timestamp(dt).isoformat()

def generate_live_chart(timeframe: str):
    symbol = read_config("SYMBOL")

    # ---- Step 1: Read candles from Parquet via viewport with a limiter ----
    # Allow override in config: "LIVE_BARS": {"2M": 600, "5M": 600, "15M": 600}
    cfg_nmap = read_config("LIVE_BARS") or {}
    bars_limit = int(cfg_nmap.get(timeframe, 600))

    tf_min = _bar_minutes(timeframe)
    t1 = pd.Timestamp.now()
    t0 = t1 - pd.Timedelta(minutes=bars_limit * tf_min)

    try:
        df_candles, df_objects = load_viewport(
            symbol=symbol,
            timeframe=timeframe,   # pass exact label as your folder/timeframe label
            t0_iso=_iso(t0),
            t1_iso=_iso(t1),
        )

        if df_candles is None or df_candles.empty or "ts" not in df_candles.columns:
            raise ValueError("No candle data found.")

        # Normalize/clean
        df_candles = df_candles.copy()
        df_candles["timestamp"] = pd.to_datetime(df_candles["ts"], errors="coerce")
        df_candles = df_candles.dropna(subset=["timestamp"]).sort_values("timestamp")
        # keep only last N bars to be safe even if viewport gave us more
        if bars_limit:
            df_candles = df_candles.tail(bars_limit).reset_index(drop=True)

        if df_candles.empty:
            raise ValueError("No candle data found after filtering.")

    except Exception:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Live {timeframe} Chart - No candle data",
            xaxis_title="", yaxis_title="", height=700
        )
        return dcc.Graph(figure=empty_fig, style={"height": "700px"})
    
    # ---- Step 2: Load EMAs and map EMA.x -> candle timestamp ----
    ema_path = get_ema_path(timeframe)
    emas = load_ema_json(ema_path)
    df_emas = pd.DataFrame(emas) if emas else None

    if df_emas is not None and not df_emas.empty:
        df_emas = df_emas.copy()
        df_emas["x"] = pd.to_numeric(df_emas["x"], errors="coerce")

        # 1) build candle index for the visible tail
        df_candles = df_candles.reset_index(drop=True)
        candle_count = len(df_candles)
        start = df_emas['x'].max() - (candle_count - 1)  # where this tail starts in global index
        df_candles['global_idx'] = range(start, start + candle_count)

        # 2) map EMA x -> candle timestamp
        idx_to_ts = dict(zip(df_candles['global_idx'], df_candles['timestamp']))
        df_emas['timestamp'] = df_emas['x'].map(idx_to_ts)
        df_emas['timestamp'] = pd.to_datetime(df_emas['timestamp'], errors='coerce')  # <- force datetime64[ns]

        # 3) keep only rows that actually land in the visible candle window
        df_emas.dropna(subset=['timestamp'], inplace=True)

    # ---- Step 3: Build the figure (candles + EMAs) ----
    fig = go.Figure()
    
    candlex = df_candles['timestamp']
    if hasattr(candlex, "dt"):
        # Python datetime array (export-safe) without the FutureWarning
        candlex = np.array(candlex.dt.to_pydatetime(), dtype=object)
    
    # --- Candles ---
    fig.add_trace(go.Candlestick(
        x=candlex,
        open=df_candles['open'],
        high=df_candles['high'],
        low=df_candles['low'],
        close=df_candles['close'],
        name='Price'
    ))

    # --- EMAs ---
    if df_emas is not None and not df_emas.empty:
        emax = df_emas['timestamp']
        if hasattr(emax, "dt"):
            emax = np.array(emax.dt.to_pydatetime(), dtype=object)

        for window, color in read_config("EMAS"):
            col = str(window)
            if col in df_emas.columns:
                fig.add_trace(go.Scatter(
                    x=emax,
                    y=df_emas[col],
                    mode='lines',
                    name=f'EMA {window}',
                    line=dict(color=str(color).lower(), width=1.5),
                    yaxis="y2",
                    connectgaps=False,
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
