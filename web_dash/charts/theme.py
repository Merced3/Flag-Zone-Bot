# web_dash/charts/theme.py
PAPER_BG = "#f7f8fa"   # matches assets/style.css body bg
PLOT_BG  = "#fdfdfd"
GRID     = "#eaecef"
GREEN    = "#16a34a"
RED      = "#ef4444"

def apply_layout(fig, title, uirevision):
    fig.update_layout(
        title=title,
        margin=dict(l=30, r=20, t=40, b=30),
        paper_bgcolor=PAPER_BG, plot_bgcolor=PLOT_BG,
        xaxis=dict(title=None, showspikes=True, spikemode="across", spikesnap="cursor"),
        yaxis=dict(title=None, gridcolor=GRID, zeroline=False),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        height=700, uirevision=uirevision,
    )
