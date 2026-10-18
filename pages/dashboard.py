# pages/dashboard.py
import re
import traceback
from datetime import datetime, timezone, timedelta

import dash
from dash import (
    html, dcc, Input, Output, State, callback, no_update,
    clientside_callback, Patch,
)
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

from components.kpi_card import kpi_card
from data_access.queries import (
    dashboard_stats,
    list_audit_events,
    phage_trend_7d,
    learning_engine_status,
)

dash.register_page(__name__, path="/", name="主控台")

LOCAL_TZ = timezone(timedelta(hours=8))
PAGE_SIZE = 20
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


def _render_audit_row(a):
    """单条审计记录渲染（供初始加载和滚动加载复用）"""
    reason = _pretty_reason(a.get("reason") or a.get("object_id") or "(无描述)")
    return html.Div([
        html.Span(f"[{a.get('action_type') or '?'}]",
                  className="badge-status badge-active me-2"),
        html.Span(reason, style={"flex": "1"}),
        html.Span(_safe_ts(a.get("timestamp")),
                  style={"fontSize": "12px",
                         "color": "var(--c-text-muted)",
                         "fontFamily": "monospace",
                         "whiteSpace": "nowrap",
                         "marginLeft": "12px"}),
    ], className="audit-row")


# ============================================================
# 图表构建
# ============================================================
def _build_trend_chart(days, vals):
    fig = go.Figure()

    if not days:
        days = [(datetime.now() - timedelta(days=i)).strftime("%m/%d")
                for i in range(6, -1, -1)]
        vals = [0] * 7

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
# Learning Engine 横幅
# ============================================================
def _le_badge(state, label, count=None):
    icon_map = {
        "verified": "bi bi-check-circle-fill",
        "progress": "bi bi-arrow-repeat",
        "pending":  "bi bi-hourglass-split",
    }
    cls_map = {
        "verified": "le-link-item le-verified",
        "progress": "le-link-item le-progress",
        "pending":  "le-link-item le-pending",
    }
    text_map = {"verified": "已验证", "progress": "进行中", "pending": "待启动"}
    text = f"{label} {text_map[state]}"
    if count is not None:
        text += f"（{count}）"
    return html.Div(
        [html.I(className=icon_map[state] + " me-1"), text],
        className=cls_map[state],
        title=f"{label}：{text_map[state]}",
    )


def _build_le_banner(le):
    reuse       = le.get("reuse_events", 0)
    case_linked = le.get("case_linked", 0)
    pkg_linked  = le.get("pkg_linked", 0)
    approved    = le.get("approved_pkgs", 0)
    total_pkgs  = le.get("total_pkgs", 0)

    if reuse > 0 and case_linked > 0 and pkg_linked > 0:
        s1 = "verified"
    elif reuse > 0 or case_linked > 0 or pkg_linked > 0:
        s1 = "progress"
    else:
        s1 = "pending"

    if approved > 0:
        s2 = "verified"
    elif total_pkgs > 0:
        s2 = "progress"
    else:
        s2 = "pending"

    s3 = "verified" if reuse > 0 else "pending"

    # ★ 修复：链路2 如果只有草稿包，显示总包数(total_pkgs)，如果是已审核显示通过数(approved)
    display_s2_count = approved if approved > 0 else total_pkgs

    return [
        html.Div([
            html.Div("Learning Engine 状态", className="le-banner-title"),
            html.Div("验证假设：过去的病例/实验经验能否被编码、审核、复用",
                     style={"fontSize": "12px",
                            "color": "var(--c-text-secondary)"}),
        ]),
        html.Div(style={"flex": "1"}),
        _le_badge(s1, "链路 #1", reuse),
        _le_badge(s2, "链路 #2", display_s2_count),
        _le_badge(s3, "链路 #3", reuse),
        html.A("查看详情 →", href="/knowledge-graph",
               style={"fontSize": "12px", "color": "var(--c-primary)",
                      "fontWeight": "600", "textDecoration": "none"}),
    ]


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
    html.Div(id="dash-le-banner", className="le-banner mb-4"),

    # 主体：左活动流 + 右操作栏
    dbc.Row(className="g-3 mb-4", children=[
        dbc.Col(md=7, children=[
            html.Div(className="surface-card", children=[
                html.Div([
                    html.Span([html.I(className="bi bi-activity me-2"),
                               "近期活动"]),
                    html.A("查看全部 →", href="/admin/audit-log",
                           style={"fontSize": "12px",
                                  "color": "var(--c-primary)",
                                  "textDecoration": "none"}),
                ], className="surface-card-header"),
                # ★ 固定高度滚动容器
                html.Div(
                    id="dash-recent-audits",
                    className="surface-card-body dash-scroll-body",
                    children=[],
                ),
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
            html.Div(className="surface-card", children=[
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

    # ★ 隐藏控件：滚动加载 & 页码状态
    html.Button(id="btn-audit-load-more", n_clicks=0,
                style={"display": "none"}),
    dcc.Store(id="audit-page", data=1),
    dcc.Store(id="audit-scroll-hook", data=0),

    dcc.Interval(id="interval-dashboard", interval=7_200_000, n_intervals=0),
])


# ============================================================
# 主回调（KPI + 趋势 + LE）
# ============================================================
@callback(
    Output("dash-kpi-row", "children"),
    Output("dash-trend-chart", "figure"),
    Output("dash-le-banner", "children"),
    Input("interval-dashboard", "n_intervals"),
    Input("interval-global", "n_intervals"),
)
def cb_refresh(_, __):
    try:
        s = dashboard_stats()
    except Exception as e:
        traceback.print_exc()
        return (dbc.Alert(f"加载 KPI 失败：{e}", color="danger"),
                go.Figure(), "")

    kpis = dbc.Row(className="g-3", children=[
        dbc.Col(kpi_card("噬菌体",   s.get("phages", 0),
                         "bi bi-virus", theme="blue",
                         href="/scientific/phage-library"), md=3),
        dbc.Col(kpi_card("临床病例", s.get("cases", 0),
                         "bi bi-journal-medical", theme="green",
                         href="/scientific/clinical-cases"), md=3),
        dbc.Col(kpi_card("情报事件", s.get("events", 0),
                         "bi bi-broadcast", theme="amber",
                         href="/ci/events"), md=3),
        dbc.Col(kpi_card("监控组织", s.get("orgs", 0),
                         "bi bi-building", theme="red",
                         href="/ci/intelligence-board"), md=3),
    ])

    try:
        days, vals = phage_trend_7d()
    except Exception:
        traceback.print_exc()
        days, vals = [], []
    trend_fig = _build_trend_chart(days, vals)

    try:
        le = learning_engine_status()
    except Exception:
        traceback.print_exc()
        le = {}
    le_banner = _build_le_banner(le)

    return kpis, trend_fig, le_banner


# ============================================================
# 活动流回调：分页加载 + 滚动追加
# ============================================================
@callback(
    Output("dash-recent-audits", "children"),
    Output("audit-page", "data"),
    Input("interval-dashboard", "n_intervals"),
    Input("interval-global", "n_intervals"),
    Input("btn-audit-load-more", "n_clicks"),
    State("audit-page", "data"),
    prevent_initial_call=False,
)
def cb_recent_audits(_, __, ___, page):
    from dash import ctx
    triggered = ctx.triggered_id
    page = page or 1

    # ── 滚动加载下一页：增量追加 ──
    if triggered == "btn-audit-load-more":
        offset = page * PAGE_SIZE
        try:
            new_rows = list_audit_events(limit=PAGE_SIZE, offset=offset)
        except Exception:
            traceback.print_exc()
            new_rows = []

        if not new_rows:
            # 已经到底，追加一条提示，同时锁定 page
            patched = Patch()
            patched.append(html.Div("— 已加载全部记录 —",
                                     className="audit-end-hint"))
            return patched, page

        patched = Patch()
        for a in new_rows:
            patched.append(_render_audit_row(a))
        return patched, page + 1

    # ── interval 刷新：回到第一页 ──
    try:
        rows = list_audit_events(limit=PAGE_SIZE, offset=0)
    except Exception:
        traceback.print_exc()
        rows = []

    if not rows:
        return ([html.Div("暂无审计记录",
                           style={"color": "var(--c-text-muted)",
                                  "fontSize": "13px",
                                  "padding": "20px 0",
                                  "textAlign": "center"})], 1)

    return ([_render_audit_row(a) for a in rows], 1)


# ============================================================
# 滚动到底 → 自动点击隐藏按钮
# ============================================================
clientside_callback(
    """
    function(_) {
        var el = document.getElementById('dash-recent-audits');
        if (!el || el.__scrollBound) return window.dash_clientside.no_update;
        el.__scrollBound = true;

        el.addEventListener('scroll', function() {
            var nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
            if (!nearBottom) return;
            // 已到底提示已存在，不再触发
            if (el.querySelector('.audit-end-hint')) return;

            var btn = document.getElementById('btn-audit-load-more');
            if (btn && !btn.__loading) {
                btn.__loading = true;
                btn.click();
                setTimeout(function(){ btn.__loading = false; }, 600);
            }
        });
        return window.dash_clientside.no_update;
    }
    """,
    Output("audit-scroll-hook", "data"),
    Input("dash-recent-audits", "children"),
    prevent_initial_call=False,
)


# ============================================================
# AI 快速查询跳转
# ============================================================
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