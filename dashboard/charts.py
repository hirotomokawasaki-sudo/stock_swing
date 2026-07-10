"""Plotly figure builders.

Palette: categorical slots 1-3 for the three accounts, slot 4 for the combined
total, assigned in fixed order (never cycled). Validated for CVD separation and
lightness band on the light surface; the sub-3:1 contrast of aqua/yellow is
relieved by the legend + data-table view in the app.
"""

import pandas as pd
import plotly.graph_objects as go

SERIES_COLORS = ["#2a78d6", "#1baf7a", "#eda100"]  # blue, aqua, yellow
TOTAL_COLOR = "#008300"                            # green

SURFACE = "#fcfcfb"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
INK_SECONDARY = "#52514e"
MUTED = "#898781"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _layout(height: int = 420) -> dict:
    return dict(
        height=height,
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=12, color=INK_SECONDARY),
        margin=dict(l=8, r=8, t=32, b=8),
        hovermode="x unified",
        hoverlabel=dict(bgcolor=SURFACE, font=dict(family=FONT, size=12)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0,
                    font=dict(color=INK_SECONDARY)),
        xaxis=dict(showgrid=False, linecolor=AXIS, linewidth=1,
                   ticks="outside", tickcolor=AXIS, tickfont=dict(color=MUTED),
                   showspikes=True, spikemode="across", spikethickness=1,
                   spikecolor=AXIS, spikedash="solid"),
        yaxis=dict(gridcolor=GRID, gridwidth=1, zeroline=False,
                   tickformat="$,.0f", tickfont=dict(color=MUTED),
                   showline=False),
    )


def equity_figure(df: pd.DataFrame, colors: dict[str, str], height: int = 420,
                  baseline: float | None = None) -> go.Figure:
    """Multi-series equity line chart. `df` is indexed by time, one column per series.

    `baseline` draws a horizontal reference line (e.g. starting capital) and
    keeps it inside the visible y-range.
    """
    fig = go.Figure(layout=_layout(height))
    single = len(df.columns) == 1
    for col in df.columns:
        color = colors[col]
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col], name=col, mode="lines",
            line=dict(color=color, width=2, shape="linear"),
            showlegend=not single,
            hovertemplate="%{y:$,.2f}<extra>" + col + "</extra>",
        ))
        # End marker: >=8px dot with a 2px surface ring so it reads over lines.
        last = df[col].dropna()
        if not last.empty:
            fig.add_trace(go.Scatter(
                x=[last.index[-1]], y=[last.iloc[-1]], mode="markers",
                marker=dict(color=color, size=9, line=dict(color=SURFACE, width=2)),
                showlegend=False, hoverinfo="skip",
            ))
    if baseline is not None:
        fig.add_hline(
            y=baseline,
            line=dict(color=MUTED, width=1, dash="dash"),
            annotation_text=f"Base ${baseline:,.0f}",
            annotation_position="top left",
            annotation_font=dict(family=FONT, size=11, color=MUTED),
        )
        # Shapes don't affect autorange, so pin the range to include the baseline.
        lo = min(float(df.min().min()), baseline)
        hi = max(float(df.max().max()), baseline)
        pad = (hi - lo) * 0.06 or hi * 0.01 or 1.0
        fig.update_yaxes(range=[lo - pad, hi + pad])
    return fig


def allocation_figure(labels: list[str], values: list[float], colors: list[str]) -> go.Figure:
    """Single horizontal stacked bar: how the account's equity is deployed."""
    fig = go.Figure(layout=_layout(height=120))
    total = sum(values) or 1.0
    for label, value, color in zip(labels, values, colors):
        fig.add_trace(go.Bar(
            y=[""], x=[value], name=label, orientation="h",
            marker=dict(color=color, line=dict(color=SURFACE, width=2)),
            width=0.5,
            hovertemplate=f"{label}: " + "%{x:$,.0f} (" + f"{value / total:.1%}" + ")<extra></extra>",
        ))
    fig.update_layout(
        barmode="stack", bargap=0,
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        hovermode="closest", margin=dict(l=8, r=8, t=32, b=8),
        legend=dict(traceorder="normal"),
    )
    return fig
