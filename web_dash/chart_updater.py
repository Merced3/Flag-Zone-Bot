# web_dash/chart_updater.py
from pathlib import Path
import plotly.graph_objects as go
import plotly.io as pio
from web_dash.charts.live_chart import generate_live_chart
from web_dash.charts.zones_chart import generate_zones_chart
import httpx

def _as_figure(component_or_figure):
    """Accepts dcc.Graph, dict, or Figure and returns a real go.Figure."""
    fig_like = getattr(component_or_figure, "figure", component_or_figure)
    return go.Figure(fig_like)

def update_chart(timeframe="2M", chart_type="live", notify=False):
    """
    Saves a snapshot of a chart based on timeframe and chart type.
    chart_type: "live" (2M/5M/15M) or "zones".
    """
    # Build a clean figure for static export
    if chart_type == "zones":
        fig = _as_figure(generate_zones_chart())
        out = Path(f"storage/SPY_{timeframe}-zone_chart.png")  # keep your naming

        # Guardrails for zones (categorical x)
        fig.update_layout(
            template=None,
            uirevision=None,
            xaxis=dict(type="category"),   # <-- was "date" (wrong for zones)
        )
    elif chart_type == "live":
        fig = _as_figure(generate_live_chart(timeframe))
        out = Path(f"storage/SPY_{timeframe}_chart.png")

        # Guardrails for live (datetime x)
        fig.update_layout(
            template=None,
            uirevision=None,
            xaxis=dict(type="date"),
        )
    else:
        raise ValueError(f"[update_chart] Invalid chart_type: {chart_type}")

    out.parent.mkdir(parents=True, exist_ok=True)
    pio.write_image(fig, str(out), format="png", width=1400, height=700, engine="kaleido")

    if notify:
        tfs = ["zones"] if chart_type == "zones" else [timeframe]
        try:
            httpx.post("http://127.0.0.1:8000/trigger-chart-update", json={"timeframes": tfs})
        except Exception as e:
            print(f"[update_chart] WS notify failed: {e}")
