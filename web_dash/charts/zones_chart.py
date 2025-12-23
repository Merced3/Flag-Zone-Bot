# web_dash/charts/zones_chart.py
from __future__ import annotations
import re
from dash import dcc
import plotly.graph_objs as go
import pandas as pd
from utils.json_utils import read_config
from storage.viewport import load_viewport, days_window
from web_dash.assets.object_styles import draw_objects
from web_dash.charts.theme import apply_layout, GREEN, RED

TZ = "America/New_York"

def _tf_minutes(tf: str) -> int:
    # robust: "15m", "15M" -> 15; "2m" -> 2
    m = re.search(r"(\d+)\s*[mM]", tf)
    return int(m.group(1)) if m else 15

def _apply_market_rangebreaks(fig: go.Figure):
    # kill weekends + overnight gaps so days sit flush
    fig.update_xaxes(
        rangebreaks=[
            dict(bounds=["sat", "mon"]),
            dict(bounds=[16, 9.5], pattern="hour"),
        ],
        showgrid=False,
    )

def _add_day_bands(fig: go.Figure, ts_plot: pd.Series, tf_minutes: int, opacity=0.40):
    # assumes df_c['ts'] exists (ISO with tz per your storage contract)
    dates = ts_plot.dt.floor("D")
    for i, d in enumerate(pd.unique(dates)):
        mask = dates == d
        if not mask.any():
            continue
        x0 = ts_plot[mask].min()
        x1 = ts_plot[mask].max() + pd.Timedelta(minutes=tf_minutes)
        color = "#f1f3f5" if i % 2 == 0 else "#ffffff"
        fig.add_vrect(x0=x0, x1=x1, fillcolor=color, opacity=opacity,
                      layer="below", line_width=0)

def generate_zones_chart(timeframe: str = "15m", days: int = 10):
    #print(f"\n[zones_chart] timeframe: {timeframe}, days: {days}")
    symbol = read_config("SYMBOL")
    t0, t1, picked = days_window(timeframe, days)

    # 1) Pull BOTH dayfiles and parts so days aren’t missing candles
    df_c, df_o = load_viewport(
        symbol=symbol, timeframe=timeframe,
        t0_iso=t0, t1_iso=t1,
        include_days=True, include_parts=False,
    )

    # --- debug: counts per ET day before trimming ---
    ts_et_raw = pd.to_datetime(df_c["ts"], utc=True, errors="coerce").dt.tz_convert(TZ)
    pre_counts_c = pd.Series(ts_et_raw.dt.date).value_counts().sort_index()
    
    # objects structure: Columns: [object_id, id, type, left, y, top, bottom, status, symbol, timeframe]
    if "ts" in df_o.columns: # We need to change this, not just the if statement but the contents inside to better handle what we want to display in terminal, best fit.
        ts_et_o = pd.to_datetime(df_o["ts"], utc=True, errors="coerce").dt.tz_convert(TZ)
        pre_counts_o = pd.Series(ts_et_o.dt.date).value_counts().sort_index()

    # Empty case
    if df_c.empty:
        empty = go.Figure().update_layout(
            title=f"{symbol} — Zones ({timeframe}) — no data",
            height=700, xaxis_rangeslider_visible=False
        )
        return dcc.Graph(figure=empty, style={"height": "700px"})
    
    # Normalize time → ET and make it NAIVE for Plotly/rangebreaks; do not trim rows
    ts_local = pd.to_datetime(df_c["ts"], errors="coerce").dt.tz_localize("America/Chicago")
    ts_et = ts_local.dt.tz_convert(TZ)
    ts_plot = ts_et.dt.tz_localize(None)
    df_c = df_c.assign(_ts_plot=ts_plot, _et_date=ts_plot.dt.date)  # _et_date only for debug/stats


    # 4) Candles
    # Use naive ET timestamps so rangebreaks don’t remove midday bars
    x = ts_plot
    fig = go.Figure(go.Candlestick(
        x=x,
        open=df_c["open"], high=df_c["high"], low=df_c["low"], close=df_c["close"],
        increasing_line_color=GREEN, decreasing_line_color=RED,
        increasing_fillcolor=GREEN, decreasing_fillcolor=RED,
        name="Price",
    ))

    # 5) Remove gaps + add day stripes + overlay objects
    _apply_market_rangebreaks(fig)
    _add_day_bands(fig, df_c["_ts_plot"], _tf_minutes(timeframe))
    draw_objects(fig, df_o, df_c, _tf_minutes(timeframe), variant="zones")

    # 6) Layout polish
    apply_layout(fig, title=f"{symbol} — Historical ({timeframe.upper()})", uirevision="zones")

    return dcc.Graph(figure=fig, style={"height": "700px"})
