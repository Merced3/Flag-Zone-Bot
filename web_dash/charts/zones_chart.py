# web_dash/charts/zones_chart.py
from __future__ import annotations
import re
from dash import dcc
import plotly.graph_objs as go
import pandas as pd
from utils.json_utils import read_config
from storage.viewport import load_viewport, days_window

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

def _add_day_bands(fig: go.Figure, ts_plot: pd.Series, tf_minutes: int, opacity=0.26):
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

def _draw_objects(fig: go.Figure, df_o: pd.DataFrame):
    if df_o.empty: return
    # levels
    if "y" in df_o.columns:
        for y in df_o["y"].dropna().astype(float):
            fig.add_hline(y=y, line_width=1, line_dash="dot",
                          line_color="#6b7280", opacity=0.65)
    # zones
    if {"top", "bottom"}.issubset(df_o.columns):
        for _, r in df_o.dropna(subset=["top", "bottom"]).iterrows():
            y0 = float(min(r["top"], r["bottom"]))
            y1 = float(max(r["top"], r["bottom"]))
            fig.add_hrect(y0=y0, y1=y1, line_width=0,
                          fillcolor="#60a5fa", opacity=0.13)

def generate_zones_chart(timeframe: str = "15M", days: int = 10):
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
    print(f"[zones_chart pre] candles per day ({timeframe}):\n{pre_counts_c}")

    if "ts" in df_o.columns:
        ts_et_o = pd.to_datetime(df_o["ts"], utc=True, errors="coerce").dt.tz_convert(TZ)
        pre_counts_o = pd.Series(ts_et_o.dt.date).value_counts().sort_index()
        print(f"[zones_chart pre] objects per day:\n{pre_counts_o}")
    else:
        print("[zones_chart pre] objects have no ts column")

    # Empty case
    if df_c.empty:
        empty = go.Figure().update_layout(
            title=f"{symbol} — Zones ({timeframe}) — no data",
            height=700, xaxis_rangeslider_visible=False
        )
        return dcc.Graph(figure=empty, style={"height": "700px"})
    
    # 2) Normalize time → ET and make it NAIVE for Plotly rangebreaks
    ts_utc = pd.to_datetime(df_c["ts"], utc=True, errors="coerce")
    ts_et  = ts_utc.dt.tz_convert(TZ)
    ts_plot = ts_et.dt.tz_localize(None)  # naive ET datetimes for Plotly

    # 3) Keep last N distinct ET dates (robust if t0/t1 spans more)
    df_c = df_c.assign(_ts_plot=ts_plot, _et_date=ts_plot.dt.date)
    keep_dates = sorted(df_c["_et_date"].unique())[-days:]
    df_c = df_c[df_c["_et_date"].isin(keep_dates)]

    # --- debug: counts per ET day after trimming ---
    post_counts_c = df_c.groupby("_et_date").size()
    print(f"[zones_chart post] candles per day ({timeframe}):\n{post_counts_c}")

    if "ts" in df_o.columns:
        df_o = df_o.assign(_et_date=pd.to_datetime(df_o["ts"], utc=True, errors="coerce").dt.tz_convert(TZ).dt.date)
        post_counts_o = df_o.groupby("_et_date").size()
        print(f"[zones_chart post] objects per day:\n{post_counts_o}")

    # 4) Candles
    # x = pd.to_datetime(df_c["ts"], utc=True, errors="coerce").dt.tz_convert(TZ)
    # Use naive ET timestamps so rangebreaks don’t remove midday bars
    x = ts_plot
    fig = go.Figure(go.Candlestick(
        x=x,
        open=df_c["open"], high=df_c["high"], low=df_c["low"], close=df_c["close"],
        increasing_line_color="#16a34a", decreasing_line_color="#ef4444",
        increasing_fillcolor="#16a34a", decreasing_fillcolor="#ef4444",
        name="Price"
    ))

    # 5) Remove gaps + add day stripes + overlay objects
    _apply_market_rangebreaks(fig)
    _add_day_bands(fig, df_c["_ts_plot"], _tf_minutes(timeframe))
    _draw_objects(fig, df_o)

    # 6) Layout polish
    fig.update_layout(
        title=f"{symbol} — Zones ({timeframe.upper()})",
        margin=dict(l=30, r=20, t=40, b=30),
        paper_bgcolor="#f7f8fa", plot_bgcolor="#fdfdfd",
        xaxis=dict(title=None, showspikes=True, spikemode="across", spikesnap="cursor"),
        yaxis=dict(title=None, gridcolor="#eaecef", zeroline=False),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=700, uirevision="zones",
    )

    return dcc.Graph(figure=fig, style={"height": "700px"})
