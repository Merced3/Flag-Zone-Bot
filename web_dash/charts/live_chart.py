# web_dash/charts/live_chart.py
from __future__ import annotations
import re
import numpy as np
import pandas as pd
import plotly.graph_objs as go
from dash import dcc

from utils.json_utils import read_config
from storage.viewport import load_viewport, get_timeframe_bounds
from web_dash.charts.theme import apply_layout, GREEN, RED
from web_dash.assets.object_styles import draw_objects

from paths import get_ema_path
from utils.ema_utils import load_ema_json

_BAR_MINUTES_RE = re.compile(r"(\d+)\s*[mM]")
TZ = "America/New_York"

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
    v = cfg.get(timeframe) or cfg.get(timeframe.upper()) or cfg.get(timeframe.lower())
    return _coerce_pos_int(v, default)

def generate_live_chart(timeframe: str):
    tf = timeframe.lower()
    symbol = read_config("SYMBOL")
    bars_limit = _pick_bars_limit(tf, default=600)
    tf_min = _bar_minutes(tf)
    print(f"\n[live_chart] timeframe: {tf}")

    anchor = str(read_config("LIVE_ANCHOR")).lower()  # 'now' | 'latest'

    # If we have any parts at all, capture their latest ts for a fallback
    _min_ts, latest_parts_ts, _nparts = get_timeframe_bounds(
        timeframe=tf,
        include_days=False,
        include_parts=True,
    )

    if anchor == "latest" and latest_parts_ts is not None:
        t1 = latest_parts_ts
    else:
        t1 = pd.Timestamp.now()
    t0 = t1 - pd.Timedelta(minutes=bars_limit * tf_min)

    df_candles, df_objects = load_viewport(
        symbol=symbol, 
        timeframe=tf,
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
            timeframe=tf,
            t0_iso=t0.isoformat(),
            t1_iso=t1.isoformat(),
            include_days=False,
            include_parts=True,
        )

    if df_candles.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"Live {timeframe} Chart - No candle data",
            xaxis_title="", yaxis_title="", height=700
        )
        return dcc.Graph(figure=fig, style={"height": "700px"})

    # Normalize/clean + tail
    df_candles = df_candles.copy()
    df_candles["timestamp"] = pd.to_datetime(df_candles["ts"], errors="coerce")
    df_candles = df_candles.dropna(subset=["timestamp"]).sort_values("timestamp")
    if bars_limit:
        df_candles = df_candles.tail(bars_limit).reset_index(drop=True)

    # _ts_plot (naive ET) for both candles and objects
    ts = pd.to_datetime(df_candles["ts"], errors="coerce")
    if ts.dt.tz is None:
        ts_local = ts.dt.tz_localize("America/Chicago")
    else:
        ts_local = ts.dt.tz_convert("America/Chicago")
    ts_et = ts_local.dt.tz_convert(TZ)
    df_candles["_ts_plot"] = ts_et.dt.tz_localize(None)

    # Debug
    print(f"[live_chart] candles={len(df_candles)} objects={len(df_objects)}")

    # --- plot ---
    fig = go.Figure()
    candlex = df_candles["_ts_plot"].to_numpy() #candlex = np.array(df_candles["_ts_plot"].dt.to_pydatetime(), dtype=object)
    fig.add_trace(go.Candlestick(
        x=candlex,
        open=df_candles["open"], high=df_candles["high"],
        low=df_candles["low"], close=df_candles["close"],
        increasing_line_color=GREEN, decreasing_line_color=RED,
        increasing_fillcolor=GREEN, decreasing_fillcolor=RED,
        name="Price",
    ))

    # Draw EMAs
    ema_path = get_ema_path(tf.upper()) # get_ema_path() is a older function that runs off of the old uppercase naming convention, will change if need be.
    ema_df = load_ema_json(ema_path)
    if ema_df is not None and not ema_df.empty:
        ema_df["timestamp"] = pd.to_datetime(ema_df["ts"], errors="coerce")
        merged = pd.merge_asof(
            df_candles.sort_values("timestamp"), 
            ema_df.sort_values("timestamp"),
            on="timestamp"
        )
        for col in [c for c in merged.columns if c.lower().startswith("ema")]:
            fig.add_trace(go.Scatter(
                x=candlex, y=merged[col],
                mode="lines", name=col.upper(),
                line=dict(width=1.4, color="#1d4ed8"),
                yaxis="y", hoverinfo="skip",
            ))

    # Draw objects (zones/levels)
    draw_objects(fig, df_objects, df_candles, tf_min, variant="live")

    # Layout: key on the right, focus y-range on candles only
    visible_min = float(df_candles["low"].min())
    visible_max = float(df_candles["high"].max())
    span = max(visible_max - visible_min, 0.0)
    pad = max(span * 0.05, 0.05)

    apply_layout(fig, title=f"{symbol} — Live ({timeframe.upper()})", uirevision=f"live-{timeframe}")
    fig.update_yaxes(range=[visible_min - pad, visible_max + pad], autorange=False)
    fig.update_traces(cliponaxis=True, selector=dict(type="scatter"))

    return dcc.Graph(figure=fig, style={"height": "700px"})
