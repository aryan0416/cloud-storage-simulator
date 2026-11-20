"""
ui.py
-----
Presentation helpers shared by every page of app.py (no business logic here).

* load_css()         - injects assets/styles.css once per page run
* page_header()      - page title + one-line description + divider
* badge()            - small coloured "pill" (tier, redundancy, status, role)
* info_panel()       - bordered explanation box with a heading
* style_chart()      - one Plotly template applied to every chart
* table()            - st.dataframe with hidden index and full width
* pill_column()      - table column that shows values as coloured pills
"""

import html
from pathlib import Path

import pandas as pd
import streamlit as st

CSS_PATH = Path(__file__).resolve().parent / "assets" / "styles.css"

# Design-system colours (keep in sync with assets/styles.css).
PRIMARY = "#0F62FE"
PRIMARY_DARK = "#0043CE"
TEXT = "#1B2333"
MUTED = "#5D6B82"
BORDER = "#E1E6EF"
FONT = '"Segoe UI", system-ui, -apple-system, Roboto, Helvetica, Arial, sans-serif'

TIER_COLOURS = {"Hot": "#DA1E28", "Cool": "#0F62FE", "Cold": "#6929C4", "Archive": "#6F6F6F"}
REDUNDANCY_COLOURS = {"LRS": "#8D9AAF", "GRS": PRIMARY}
ROLE_COLOURS = {"Owner": PRIMARY, "Contributor": "#198038", "Reader": "#6F6F6F"}

# Material icon names used across the app (Streamlit ":material/name:" syntax).
ICONS = {
    "Dashboard": ":material/dashboard:",
    "File Manager": ":material/folder:",
    "Storage Tiers": ":material/layers:",
    "Redundancy": ":material/cloud_sync:",
    "Backups": ":material/backup:",
    "Cost Estimator": ":material/payments:",
    "Activity Log": ":material/history:",
    "AZ-900 Concepts": ":material/school:",
}

# Icons for st.success / st.info / st.warning / st.error (no emojis).
ALERT_ICONS = {
    "success": ":material/check_circle:",
    "info": ":material/info:",
    "warning": ":material/warning:",
    "error": ":material/error:",
}


def load_css() -> None:
    """Read assets/styles.css and inject it. A missing file only shows a warning."""
    try:
        css = CSS_PATH.read_text(encoding="utf-8")
    except OSError:
        st.warning(f"Style sheet not found at {CSS_PATH}. The app works, but uses the default look.")
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def page_header(title: str, description: str) -> None:
    st.markdown(
        f"<div class='page-header'><div class='title'>{html.escape(title)}</div>"
        f"<div class='desc'>{html.escape(description)}</div></div>",
        unsafe_allow_html=True,
    )


def badge(value: str, kind: str | None = None) -> str:
    """
    Return the HTML for a small rounded pill. The CSS class is chosen from the
    value itself (e.g. 'Hot' -> badge-hot, 'GRS' -> badge-grs) unless kind is given.
    """
    css_class = (kind or value).lower().replace(" ", "-")
    return f"<span class='badge badge-{html.escape(css_class)}'>{html.escape(str(value))}</span>"


def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def info_panel(title: str, body: str, note: bool = False) -> None:
    """Bordered explanation panel with a heading and a short text."""
    css = "info-panel note" if note else "info-panel"
    html_block(f"<div class='{css}'><div class='panel-title'>{html.escape(title)}</div>"
               f"<div class='panel-body'>{body}</div></div>")


def style_chart(fig, height: int = 340):
    """Apply the shared chart template: transparent, system font, muted grid, legend at the bottom."""
    is_pie = any(trace.type == "pie" for trace in fig.data)
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=13, color=TEXT),
        title_font=dict(size=14, color=TEXT),
        margin=dict(t=48 if fig.layout.title.text else 16, r=16,
                    l=16 if is_pie else 72, b=16 if is_pie else 56),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title_text=""),
        hoverlabel=dict(font_family=FONT, bgcolor="#FFFFFF", bordercolor=BORDER),
        colorway=list(TIER_COLOURS.values()),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDER, automargin=True, tickfont=dict(color=MUTED), title_font=dict(color=MUTED))
    fig.update_yaxes(gridcolor="#EEF1F6", zeroline=False, linecolor=BORDER, automargin=True,
                     tickfont=dict(color=MUTED), title_font=dict(color=MUTED))
    return fig


def plotly_chart(fig) -> None:
    """Render with our own template (theme=None stops Streamlit overriding it)."""
    st.plotly_chart(fig, theme=None, width="stretch", config={"displaylogo": False})


def as_pills(series: pd.Series) -> pd.Series:
    """Wrap each value in a one-item list so a MultiselectColumn shows it as a pill."""
    return series.apply(lambda v: [v] if v not in (None, "") else [])


def soft(hex_colour: str) -> str:
    """Light version of a colour (20% opacity) for pill backgrounds in tables."""
    return hex_colour + "33"


def pill_column(label: str, colours: dict[str, str]):
    """Read-only table column showing values as light coloured pills."""
    return st.column_config.MultiselectColumn(
        label, options=list(colours.keys()), color=[soft(c) for c in colours.values()], disabled=True,
    )


def table(df: pd.DataFrame, column_config: dict | None = None, height: int | str = "auto") -> None:
    st.dataframe(df, hide_index=True, width="stretch", column_config=column_config or {}, height=height)
