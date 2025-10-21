# web_dash/dash_app.py 
# Run Frontend: "python web_dash/dash_app.py"
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import dash
from dash import dcc, html, callback, ctx
from dash.dependencies import Input, Output, MATCH, State
from dash_extensions import WebSocket
import dash.exceptions

from charts.live_chart import generate_live_chart
from charts.zones_chart import generate_zones_chart
from utils.json_utils import read_config

import logging
logging.getLogger("werkzeug").setLevel(logging.WARNING)

print("[dash_app] using file:", __file__)

TIMEFRAMES = read_config("TIMEFRAMES")  # e.g. ["2M","5M","15M"]
SYMBOL = read_config("SYMBOL") # e.g. "SPY"

tabs = [
    {"label": "Zones", "value": "zones"},
    *[{"label": tf, "value": tf} for tf in TIMEFRAMES]
]

app = dash.Dash(__name__, title=f"{SYMBOL} Bot Multi-Timeframe Viewer")

def tab_block(tf_label, tf_key):
    """
    Builds a tab with its own WebSocket + Graph using pattern-matching IDs.
    tf_key can be "2M", "5M", "15M", or "zones".
    """
    ws_id    = {"type": "ws",    "tf": tf_key}
    graph_id = {"type": "graph", "tf": tf_key}

    # Initial figure (seed) — light & fast:
    initial_fig = generate_zones_chart("15M").figure if tf_key == "zones" else generate_live_chart(tf_key).figure

    return dcc.Tab(
        label=tf_label, value=tf_key,
        children=[
            WebSocket(id=ws_id, url="ws://127.0.0.1:8000/ws/chart-updates"),
            dcc.Loading(children=[
                dcc.Graph(id=graph_id, figure=initial_fig, style={"height": "700px"})
            ], type="default")
        ]
    )

app.layout = html.Div([
    html.H1(f"{SYMBOL} Bot: Multi-Timeframe View", style={"textAlign": "center"}),
    dcc.Tabs(
        id="mtf-tabs",
        value="zones",
        children=[
        tab_block("Zones Chart (15M History)", "zones"),
        tab_block("Live 15M Chart", "15M"),
        tab_block("Live 5M Chart",  "5M"),
        tab_block("Live 2M Chart",  "2M"),
    ])
])

@callback(
    Output({"type": "graph", "tf": MATCH}, "figure"),
    Input({"type": "ws", "tf": MATCH}, "message"),
    Input("mtf-tabs", "value"),                                     # <— also trigger on tab switch
    State({"type": "graph", "tf": MATCH}, "id"),                     # <— know which TF this instance owns
)
def refresh_any(msg, selected_tab, graph_id):
    tf_key = graph_id["tf"]

    # A) WS-driven refresh (payload must match this TF)
    if msg:
        payload = msg.get("data") if isinstance(msg, dict) else msg
        if isinstance(payload, str) and payload == f"chart:{tf_key}":
            return (generate_zones_chart("15M").figure
                    if tf_key == "zones"
                    else generate_live_chart(tf_key).figure)

    # B) Tab-activation refresh (user clicked into this TF)
    if selected_tab == tf_key:
        return (generate_zones_chart("15M").figure
                if tf_key == "zones"
                else generate_live_chart(tf_key).figure)

    # Otherwise, do nothing for this graph instance
    raise dash.exceptions.PreventUpdate

if __name__ == "__main__":
    app.run(debug=False, port=8050)
