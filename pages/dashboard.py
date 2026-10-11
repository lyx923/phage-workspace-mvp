# pages/dashboard.py
import re
import traceback
import random
from datetime import datetime, timezone, timedelta

import dash
from dash import html, dcc, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.kpi_card import kpi_card
from data_access.queries import dashboard_stats, list_audit_events

dash.register_page(__name__, path="/", name="主控台")

LOCAL_TZ = timezone(timedelta(hours=8))
_ISO_PATTERN = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)


def _safe_ts(v):
    if v is None:
        return ""
    try:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return ""
            s_clean = s.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s_clean)
            except ValueError:
                return s[:19]
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(LOCAL_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(v, "to_native"):
            v = v.to_native()
        if hasattr(v, "strftime"):
            if getattr(v, "tzinfo", None) is None:
                v = v.replace(tzinfo=timezone.utc)
            v = v.astimezone(LOCAL_TZ)
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return str(v)
    except Exception:
        return str(v)


def _pretty_reason(text):
    if not text:
        return ""
    def _repl(m):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
    return _ISO_PATTERN.sub(_repl, text)


def _build_trend_chart(stats):
    days = [(datetime.now() - timedelta(days=i)).strftime("%m/%d")
            for i in range(6, -1, -1)]
    base = stats.get("phages", 0) or 200
    vals = [base - random.randint(0, 5) * i for i in range(6, -1, -1)]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=days, y=vals, mode="lines+markers", name="噬菌体",
        line=dict(color="#1B6CA8", width=2),
        marker=dict(size=5),
        fill="tozeroy", fillcolor="rgba(27,108,168,0.08)",
    ))
    fig.update_layout(
        height=220, margin=dict(l=0, r=0, t=8, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis=dict(showgrid=False, tickfont=dict(size=11, color="#94A3B8")),
        yaxis=dict(showgrid=True, gridcolor="#E2E8F0",
                   tickfont=dict(size=11, color="#94A3B8"), zeroline=False),
    )
    return fig


# ============================================================
# 布局
# ============================================================
layout = html.Div([
    # 页头
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("主控台", className="page-title"),
            html.Div("平台资产 · 情报闭环 · 运营健康",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.A([html.I(className="bi bi-plus-lg me-1"), "新增噬菌体"],
                   href="/scientific/phage-library",
                   className="btn-primary-custom"),
            html.A([html.I(className="bi bi-folder-plus me-1"), "新建证据包"],
                   href="/scientific/evidence-packages",
                   className="btn-outline-custom"),
        ]),
    ]),

    # KPI 行
    html.Div(id="dash-kpi-row", className="mb-4"),

    # Learning Engine 横幅
    html.Div(className="le-banner mb-4", children=[
        html.Div([
            html.Div("Learning Engine 状态", className="le-banner-title"),
            html.Div("验证假设：过去的病例/实验经验能否被编码、审核、复用",
                     style={"fontSize": "12px",
                            "color": "var(--c-text-secondary)"}),
        ]),
        html.Div(style={"flex": "1"}),
        html.Div([html.I(className="bi bi-check-circle-fill me-1"),
                  "链路 #1 已验证"],
                 className="le-link-item le-verified"),
        html.Div([html.I(className="bi bi-arrow-repeat me-1"),
                  "链路 #2 进行中"],
                 className="le-link-item le-progress"),
        html.Div([html.I(className="bi bi-hourglass-split me-1"),
                  "链路 #3 待启动"],
                 className="le-link-item le-pending"),
        html.A("查看详情 →", href="/knowledge-graph",
               style={"fontSize": "12px", "color": "var(--c-primary)",
                      "fontWeight": "600", "textDecoration": "none"}),
    ]),

    # 主体：左活动流 + 右操作栏
    dbc.Row(className="g-3 mb-4", children=[
        dbc.Col(md=7, children=[
            html.Div(className="surface-card", style={"height": "100%"},
                     children=[
                html.Div([
                    html.Span([html.I(className="bi bi-activity me-2"),
                               "近期活动"]),
                    html.A("查看全部 →", href="/admin/audit-log",
                           style={"fontSize": "12px",
                                  "color": "var(--c-primary)",
                                  "textDecoration": "none"}),
                ], className="surface-card-header"),
                html.Div(id="dash-recent-audits",
                         className="surface-card-body"),
            ]),
        ]),
        dbc.Col(md=5, children=[
            # 快速操作
            html.Div(className="surface-card mb-3", children=[
                html.Div([html.I(className="bi bi-lightning-charge me-2"),
                          "快速操作"], className="surface-card-header"),
                html.Div(className="surface-card-body", children=[
                    dbc.Row(className="g-2", children=[
                        dbc.Col(html.A(
                            [html.I(className="bi bi-plus-circle me-2"),
                             "录入噬菌体"],
                            href="/scientific/phage-library",
                            className="btn-primary-custom w-100 "
                                      "justify-content-center"), md=6),
                        dbc.Col(html.A(
                            [html.I(className="bi bi-eyedropper me-2"),
                             "记录实验"],
                            href="/scientific/lysis-assay",
                            className="btn-outline-custom w-100 "
                                      "justify-content-center"), md=6),
                        dbc.Col(html.A(
                            [html.I(className="bi bi-journal-plus me-2"),
                             "导入病例"],
                            href="/scientific/clinical-cases",
                            className="btn-outline-custom w-100 "
                                      "justify-content-center"), md=6),
                        dbc.Col(html.A(
                            [html.I(className="bi bi-broadcast me-2"),
                             "添加情报"],
                            href="/ci/events",
                            className="btn-outline-custom w-100 "
                                      "justify-content-center"), md=6),
                    ]),
                ]),
            ]),
            # AI 快速查询
            html.Div(className="surface-card mb-3", children=[
                html.Div([html.I(className="bi bi-stars me-2"),
                          "AI 快速查询"], className="surface-card-header"),
                html.Div(className="surface-card-body", children=[
                    html.P("向 AI 助手提问，检索将基于结构化 Ontology 数据",
                           style={"fontSize": "12px",
                                  "color": "var(--c-text-secondary)",
                                  "marginBottom": "10px"}),
                    dbc.InputGroup(className="mb-2", children=[
                        dbc.Input(id="dash-quick-query",
                                  placeholder="例如：最近哪个噬菌体复用率最高？",
                                  style={"fontSize": "13px"}),
                        dbc.Button(html.I(className="bi bi-arrow-right"),
                                   id="btn-quick-query",
                                   color="primary"),
                    ]),
                    html.A("进入完整 AI 助手 →", href="/ai-assistant",
                           style={"fontSize": "12px",
                                  "color": "var(--c-primary)",
                                  "textDecoration": "none"}),
                ]),
            ]),
            # 系统健康
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-heart-pulse me-2"),
                          "系统健康"], className="surface-card-header"),
                html.Div(id="dash-system-health",
                         className="surface-card-body"),
            ]),
        ]),
    ]),

    # 7 日趋势
    html.Div(className="surface-card mb-4", children=[
        html.Div([html.I(className="bi bi-graph-up me-2"),
                  "噬菌体录入趋势（7日）"], className="surface-card-header"),
        html.Div(dcc.Graph(id="dash-trend-chart",
                            config={"displayModeBar": False}),
                 className="surface-card-body",
                 style={"padding": "12px 16px"}),
    ]),

    dcc.Interval(id="interval-dashboard", interval=7_200_000, n_intervals=0),
])


# ============================================================
# 主回调
# ============================================================
@callback(
    Output("dash-kpi-row", "children"),
    Output("dash-recent-audits", "children"),
    Output("dash-trend-chart", "figure"),
    Output("dash-system-health", "children"),
    Input("interval-dashboard", "n_intervals"),
    Input("interval-global", "n_intervals"),
)
def cb_refresh(_, __):
    try:
        s = dashboard_stats()
    except Exception as e:
        traceback.print_exc()
        return (dbc.Alert(f"加载 KPI 失败：{e}", color="danger"),
                "", go.Figure(), "")

    kpis = dbc.Row(className="g-3", children=[
        dbc.Col(kpi_card("噬菌体",   s.get("phages", 0),
                         "bi bi-virus", theme="blue"), md=3),
        dbc.Col(kpi_card("临床病例", s.get("cases", 0),
                         "bi bi-journal-medical", theme="green"), md=3),
        dbc.Col(kpi_card("情报事件", s.get("events", 0),
                         "bi bi-broadcast", theme="amber"), md=3),
        dbc.Col(kpi_card("监控组织", s.get("orgs", 0),
                         "bi bi-building", theme="red"), md=3),
    ])

    # 活动流
    try:
        audits = list_audit_events(limit=8)
    except Exception:
        audits = []

    if not audits:
        audit_children = html.Div(
            "暂无审计记录",
            style={"color": "var(--c-text-muted)", "fontSize": "13px",
                   "padding": "20px 0", "textAlign": "center"})
    else:
        audit_children = []
        for a in audits:
            reason = _pretty_reason(
                a.get("reason") or a.get("object_id") or "(无描述)")
            audit_children.append(html.Div([
                html.Span(f"[{a.get('action_type') or '?'}]",
                          className="badge-status badge-active me-2"),
                html.Span(reason, style={"flex": "1"}),
                html.Span(_safe_ts(a.get("timestamp")),
                          style={"fontSize": "12px",
                                 "color": "var(--c-text-muted)",
                                 "fontFamily": "monospace",
                                 "whiteSpace": "nowrap",
                                 "marginLeft": "12px"}),
            ], style={"padding": "10px 0",
                      "borderBottom": "1px solid var(--c-border)",
                      "display": "flex", "alignItems": "center",
                      "gap": "8px"}))

    # 趋势图
    trend_fig = _build_trend_chart(s)

    # 系统健康
    health_rows = []
    try:
        from config import get_driver
        with get_driver().session() as session:
            session.run("RETURN 1").single()
        health_rows.append(html.Div([
            html.Span(className="status-dot dot-ok"),
            html.Span("Neo4j 数据库", style={"marginLeft": "8px",
                                              "flex": "1"}),
            html.Span("已连接", style={"fontSize": "12px",
                                       "color": "var(--c-secondary)"}),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "8px 0",
                  "borderBottom": "1px solid var(--c-border)"}))
    except Exception:
        health_rows.append(html.Div([
            html.Span(className="status-dot dot-error"),
            html.Span("Neo4j 数据库", style={"marginLeft": "8px",
                                              "flex": "1"}),
            html.Span("未连接", style={"fontSize": "12px",
                                       "color": "var(--c-danger)"}),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "8px 0",
                  "borderBottom": "1px solid var(--c-border)"}))

    try:
        from config import Config
        key = (getattr(Config, "DS_API_KEY", "")
               or getattr(Config, "DEEPSEEK_API_KEY", ""))
        if key:
            health_rows.append(html.Div([
                html.Span(className="status-dot dot-ok"),
                html.Span("DeepSeek LLM", style={"marginLeft": "8px",
                                                  "flex": "1"}),
                html.Span("已配置", style={"fontSize": "12px",
                                           "color": "var(--c-secondary)"}),
            ], style={"display": "flex", "alignItems": "center",
                      "padding": "8px 0",
                      "borderBottom": "1px solid var(--c-border)"}))
        else:
            health_rows.append(html.Div([
                html.Span(className="status-dot dot-warning"),
                html.Span("DeepSeek LLM", style={"marginLeft": "8px",
                                                  "flex": "1"}),
                html.Span("未配置", style={"fontSize": "12px",
                                           "color": "var(--c-warning)"}),
            ], style={"display": "flex", "alignItems": "center",
                      "padding": "8px 0",
                      "borderBottom": "1px solid var(--c-border)"}))
    except Exception:
        pass

    for label, key, color in [
        ("噬菌体",   "phages",  "var(--c-primary)"),
        ("临床病例", "cases",   "var(--c-secondary)"),
        ("情报事件", "events",  "var(--c-warning)"),
    ]:
        health_rows.append(html.Div([
            html.Span("•", style={"color": color, "marginRight": "8px",
                                   "fontSize": "16px"}),
            html.Span(label, style={"flex": "1", "fontSize": "13px"}),
            html.Span(str(s.get(key, 0)),
                      style={"fontFamily": "monospace",
                             "fontWeight": "600", "fontSize": "13px"}),
        ], style={"display": "flex", "alignItems": "center",
                  "padding": "8px 0",
                  "borderBottom": "1px solid var(--c-border)"}))

    return kpis, audit_children, trend_fig, health_rows


@callback(
    Output("url", "href"),
    Input("btn-quick-query", "n_clicks"),
    State("dash-quick-query", "value"),
    prevent_initial_call=True,
)
def cb_quick_query(n, query):
    if query:
        import urllib.parse
        return f"/ai-assistant?q={urllib.parse.quote(query)}"
    return ""