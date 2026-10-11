# pages/ci/intelligence_board.py
import dash
import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc

from components.kpi_card import kpi_card
from data_access.queries import (
    intelligence_board_kpis,
    list_intelligence_events_for_board,
    list_programs_for_pipeline,
)

dash.register_page(__name__, path="/ci/intelligence-board", name="情报概览")

IMPACT_COLORS = {
    "critical": "#991B1B",
    "high":     "#DC2626",
    "medium":   "#F59E0B",
    "low":      "#0D9373",
}

STAGES = ["discovery", "preclinical", "phase_1", "phase_2", "phase_3", "commercial"]


def _timeline_fig(events):
    if not events:
        return go.Figure()
    df = pd.DataFrame(events)
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df = df.dropna(subset=["event_date"]).sort_values("event_date")
    df["color"] = df["impact_level"].map(IMPACT_COLORS).fillna("#94A3B8")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["event_date"],
        y=df["org_name"].fillna("未知"),
        mode="markers",
        marker=dict(size=12, color=df["color"],
                    line=dict(width=2, color="white")),
        text=df["title"],
        hovertemplate="<b>%{text}</b><br>%{x|%Y-%m-%d}<extra></extra>",
    ))
    fig.update_layout(
        height=280, margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=True, gridcolor="#E2E8F0",
                   tickfont=dict(size=11, color="#94A3B8")),
        yaxis=dict(showgrid=False,
                   tickfont=dict(size=11, color="#64748B")),
        hovermode="closest",
    )
    return fig


def _type_bar(events):
    if not events:
        return go.Figure()
    df = pd.DataFrame(events)
    cnts = df["event_type"].value_counts().reset_index()
    cnts.columns = ["type", "count"]
    fig = go.Figure(go.Bar(
        x=cnts["count"], y=cnts["type"], orientation="h",
        marker=dict(color="#1B6CA8"),
    ))
    fig.update_layout(
        height=280, margin=dict(l=0, r=16, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(tickfont=dict(size=11)),
        xaxis=dict(gridcolor="#E2E8F0"),
    )
    return fig


def _pipeline(programs):
    stage_map = {s: [] for s in STAGES}
    for p in programs:
        s = p.get("stage") or "discovery"
        stage_map.setdefault(s, []).append(p)

    cols = []
    for stage in STAGES:
        items = stage_map.get(stage, [])
        cards = [
            html.Div([
                html.Div(p.get("name") or p["id"],
                         style={"fontSize": "12px", "fontWeight": "600"}),
                html.Div(p.get("org_name") or "—",
                         style={"fontSize": "11px", "color": "var(--c-text-muted)"}),
            ], style={"padding": "6px", "borderBottom": "1px solid var(--c-border)"})
            for p in items[:4]
        ]
        if len(items) > 4:
            cards.append(html.Div(f"+ {len(items)-4} 更多…",
                                   style={"fontSize": "11px",
                                          "color": "var(--c-text-muted)",
                                          "textAlign": "center",
                                          "padding": "4px"}))
        cols.append(dbc.Col(html.Div([
            html.Div(stage.upper(),
                     style={"fontSize": "11px", "fontWeight": "700",
                            "color": "var(--c-text-muted)",
                            "textTransform": "uppercase",
                            "letterSpacing": "0.5px",
                            "paddingBottom": "6px",
                            "borderBottom": "2px solid var(--c-primary)",
                            "marginBottom": "8px"}),
            html.Div(f"{len(items)} 个项目",
                     style={"fontSize": "20px", "fontWeight": "700",
                            "marginBottom": "8px"}),
            html.Div(cards),
        ], style={"background": "var(--c-surface)",
                  "border": "1px solid var(--c-border)",
                  "borderRadius": "10px",
                  "padding": "12px", "minHeight": "160px"}),
            md=2))   # 6 列布局

    return dbc.Row(cols, className="g-2")


layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("情报概览", className="page-title"),
            html.Div("竞争情报全景 · 事件时间线 · 开发管线",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ib-refresh", className="btn-outline-custom"),
            html.A([html.I(className="bi bi-plus-lg me-1"), "添加情报事件"],
                   href="/ci/events", className="btn-primary-custom"),
        ]),
    ]),

    dbc.Row(id="ib-kpi-row", className="g-3 mb-4"),

    dbc.Row(className="g-3 mb-4", children=[
        dbc.Col(md=8, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-clock-history me-2"),
                          "情报事件时间线（近 90 天）"],
                         className="surface-card-header"),
                html.Div(dcc.Graph(id="ib-timeline",
                                    config={"displayModeBar": False}),
                         className="surface-card-body",
                         style={"padding": "12px"}),
            ]),
        ]),
        dbc.Col(md=4, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-bar-chart me-2"),
                          "事件类型分布"],
                         className="surface-card-header"),
                html.Div(dcc.Graph(id="ib-type-bar",
                                    config={"displayModeBar": False}),
                         className="surface-card-body",
                         style={"padding": "12px"}),
            ]),
        ]),
    ]),

    html.Div(className="surface-card mb-4", children=[
        html.Div([html.I(className="bi bi-diagram-2 me-2"), "竞争开发管线"],
                 className="surface-card-header"),
        html.Div(id="ib-pipeline", className="surface-card-body"),
    ]),
])


@callback(
    Output("ib-kpi-row", "children"),
    Output("ib-timeline", "figure"),
    Output("ib-type-bar", "figure"),
    Output("ib-pipeline", "children"),
    Input("btn-ib-refresh", "n_clicks"),
    Input("interval-global", "n_intervals"),
)
def cb_load(_, __):
    try:
        k = intelligence_board_kpis()
        events = list_intelligence_events_for_board(limit=200)
        programs = list_programs_for_pipeline(limit=100)
    except Exception as e:
        return (dbc.Alert(f"加载失败：{e}", color="danger"),
                go.Figure(), go.Figure(), "")

    kpis = dbc.Row(className="g-3", children=[
        dbc.Col(kpi_card("情报事件总数", k["total_events"], "bi bi-broadcast",
                         theme="blue"), md=3),
        dbc.Col(kpi_card("高影响事件", k["high_impact"], "bi bi-exclamation-triangle",
                         theme="red"), md=3),
        dbc.Col(kpi_card("活跃项目", k["active_programs"], "bi bi-building",
                         theme="green"), md=3),
        dbc.Col(kpi_card("涉及组织", k["orgs_involved"], "bi bi-people",
                         theme="amber"), md=3),
    ])

    return kpis, _timeline_fig(events), _type_bar(events), _pipeline(programs)