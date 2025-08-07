# web_dash/chart_updater.py
from web_dash.charts.live_chart import generate_live_chart
from web_dash.charts.zones_chart import generate_zones_chart
import httpx

def update_chart(timeframe="2M", chart_type="live"):
    """
    Saves a snapshot of a chart based on timeframe and chart type.

    chart_type can be:
    - "live"   → Live 2M / 5M / 15M candles + EMAs
    - "zones"  → Static zone chart based on 15M history
    """
    # After saving, notify WebSocket server
    try:
        # Hit the /trigger endpoint (we’ll make this next)
        httpx.post(f"http://localhost:8000/trigger-chart-update", json={"timeframe": timeframe})
    except Exception as e:
        print(f"[update_chart] Failed to notify WebSocket clients: {e}")

    if chart_type == "live":
        fig = generate_live_chart(timeframe).figure
        output_path = f"storage/SPY_{timeframe}_chart.png"
    elif chart_type == "zones":
        fig = generate_zones_chart().figure
        output_path = f"storage/SPY_15-min_chart.png"
    else:
        raise ValueError(f"[update_chart] Invalid chart_type: {chart_type}")

    # Save the figure using plotly + kaleido
    fig.write_image(output_path, width=1400, height=700)
