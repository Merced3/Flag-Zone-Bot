# web_dash/dash_app.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import dash
from dash import dcc, html
from dash.dependencies import Input, Output
from dash_extensions import WebSocket
from charts.live_chart import generate_live_chart
from charts.zones_chart import generate_zones_chart
import dash.exceptions

app = dash.Dash(__name__, title="SPY Bot Multi-Timeframe Viewer")

app.layout = html.Div([
    html.H1("SPY Bot: Multi-Timeframe View", style={"textAlign": "center"}),

    dcc.Tabs([
        dcc.Tab(label="Zones Chart (15M History)", children=[generate_zones_chart()]),

        dcc.Tab(label="Live 15M Chart", children=[
            WebSocket(id="ws-15m", url="ws://127.0.0.1:8000/ws/chart-updates"),
            dcc.Graph(id="live-15m-chart", 
                      figure=generate_live_chart("15M").figure,
                      style={"height": "700px"})
        ]),

        dcc.Tab(label="Live 5M Chart", children=[
            WebSocket(id="ws-5m", url="ws://127.0.0.1:8000/ws/chart-updates"),
            dcc.Graph(id="live-5m-chart", 
                      figure=generate_live_chart("5M").figure,
                      style={"height": "700px"})
        ]),

        dcc.Tab(label="Live 2M Chart", children=[
            WebSocket(id="ws-2m", url="ws://127.0.0.1:8000/ws/chart-updates"),
            dcc.Graph(id="live-2m-chart", 
                      figure=generate_live_chart("2M").figure,
                      style={"height": "700px"})
        ]),
    ])
])

@app.callback(Output("live-2m-chart", "figure"), Input("ws-2m", "message"))
def refresh_2m(msg):
    if not msg:
        raise dash.exceptions.PreventUpdate
    payload = msg.get("data") if isinstance(msg, dict) else msg
    if payload != "chart:2M":
        raise dash.exceptions.PreventUpdate
    return generate_live_chart("2M").figure

@app.callback(Output("live-5m-chart", "figure"), Input("ws-5m", "message"))
def refresh_5m(msg):
    if not msg:
        raise dash.exceptions.PreventUpdate
    payload = msg.get("data") if isinstance(msg, dict) else msg
    if payload != "chart:5M":
        raise dash.exceptions.PreventUpdate
    return generate_live_chart("5M").figure

@app.callback(Output("live-15m-chart", "figure"), Input("ws-15m", "message"))
def refresh_15m(msg):
    if not msg:
        raise dash.exceptions.PreventUpdate
    payload = msg.get("data") if isinstance(msg, dict) else msg
    if payload != "chart:15M":
        raise dash.exceptions.PreventUpdate
    return generate_live_chart("15M").figure

if __name__ == "__main__":
    app.run(debug=False, port=8050)
