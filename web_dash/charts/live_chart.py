# web_dash/charts/live_chart.py
import pandas as pd
import pytz
import plotly.graph_objs as go
from dash import dcc
from utils.ema_utils import load_ema_json
from paths import get_ema_path, CANDLE_LOGS, LINE_DATA_PATH, MARKERS_PATH
from utils.json_utils import read_config
from shared_state import safe_read_json
from collections import deque
import io
import numpy as np
import warnings

# silence just this pandas deprecation (safe until we remove .to_pydatetime)
warnings.filterwarnings(
    "ignore",
    message="The behavior of DatetimeProperties.to_pydatetime is deprecated",
    category=FutureWarning,
)

NY = "America/New_York"

def to_local_naive(ts_series):
    # Convert whatever is in your logs (ISO strings / epoch) → tz-aware UTC
    # → convert to America/New_York → strip tz (tz-naive datetimes for Plotly)
    s = pd.to_datetime(ts_series, utc=True, errors="coerce")
    return s.dt.tz_convert(NY).dt.tz_localize(None)

def _read_last_jsonl(path, n=600):
    """
    Fast-ish tail for JSONL files: read only the last n lines.
    """
    dq = deque(maxlen=n)
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            dq.append(line)
    if not dq:
        return pd.DataFrame(columns=['timestamp','open','high','low','close'])
    return pd.read_json(io.StringIO(''.join(dq)), lines=True)

def generate_live_chart(timeframe):
    # Load candle data from log file
    candle_path = CANDLE_LOGS.get(timeframe)
    # print(f"[generate_live_chart] Loading candles from: {candle_path}")
    try:
        N_MAP = {"2M": 600, "5M": 600, "15M": 600}  # tune as you like
        df_candles = _read_last_jsonl(candle_path, N_MAP.get(timeframe, 600))
        df_candles['timestamp'] = to_local_naive(df_candles['timestamp'])
        df_candles['timestamp'] = pd.to_datetime(df_candles['timestamp'], errors='coerce')  # <- ensure datetime64[ns]
        df_candles = df_candles.sort_values('timestamp').reset_index(drop=True)

        if df_candles.empty or 'timestamp' not in df_candles.columns:
            raise ValueError("No candle data found.")
    except Exception as e:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title=f"Live {timeframe} Chart - No candle data",
            xaxis_title="",
            yaxis_title="",
            height=700
        )
        return dcc.Graph(figure=empty_fig, style={"height": "700px"})
    
    # This is for later, just saving this for whenever we need it
    #flag_data = safe_read_json(LINE_DATA_PATH)
    #marker_data = safe_read_json(MARKERS_PATH)

    # Load EMAs
    ema_path = get_ema_path(timeframe)
    emas = load_ema_json(ema_path)
    df_emas = pd.DataFrame(emas) if emas else None

    if df_emas is not None and not df_emas.empty:
        # make sure x is numeric
        df_emas['x'] = pd.to_numeric(df_emas['x'], errors='coerce')

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


    fig = go.Figure()

    # --- Candlesticks ---
    candlex = df_candles['timestamp']
    if hasattr(candlex, "dt"):
        # Python datetime array (export-safe) without the FutureWarning
        candlex = np.array(candlex.dt.to_pydatetime(), dtype=object)
    fig.add_trace(go.Candlestick(
        x=candlex,
        open=df_candles['open'],
        high=df_candles['high'],
        low=df_candles['low'],
        close=df_candles['close'],
        name='Price'
    ))

    # --- EMAs ---
    if df_emas is not None:
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
                    line=dict(color=color.lower(), width=1.5),
                    yaxis="y2",
                    connectgaps=False,
                ))

    fig.update_layout(
        title=f"Live {timeframe} Chart",
        xaxis_title='Time',
        yaxis_title='Price',
        xaxis=dict(type="date"),
        xaxis_rangeslider_visible=False,
        uirevision=f"live-{timeframe}",
        yaxis2=dict(overlaying="y", matches="y", showticklabels=False, showgrid=False)
    )

    fig.update_traces(cliponaxis=True, selector=dict(type="scatter"))

    # --- keep y-range based ONLY on candles ---
    visible_min = df_candles['low'].min()
    visible_max = df_candles['high'].max()
    span = float(visible_max - visible_min)
    pad = max(span * 0.05, 0.05)

    fig.update_yaxes(
        range=[visible_min - pad, visible_max + pad],
        autorange=False
    )

    return dcc.Graph(figure=fig, style={"height": "700px"})
