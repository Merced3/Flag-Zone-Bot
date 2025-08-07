# web_dash/dash_app.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import dash
from dash import dcc, html
from charts.live_chart import generate_live_chart
from charts.zones_chart import generate_zones_chart

app = dash.Dash(__name__, title="SPY Bot Multi-Timeframe Viewer")

app.layout = html.Div([
    html.H1("SPY Bot: Multi-Timeframe View", style={"textAlign": "center"}),
    
    dcc.Tabs([
        dcc.Tab(label="Zones Chart (15M History)", children=[generate_zones_chart()]),
        dcc.Tab(label="Live 15M Chart", children=[generate_live_chart("15M")]),
        dcc.Tab(label="Live 5M Chart", children=[generate_live_chart("5M")]),
        dcc.Tab(label="Live 2M Chart", children=[generate_live_chart("2M")]),
    ])
])

if __name__ == "__main__":
    app.run(debug=False, port=8050)
