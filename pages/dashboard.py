# pages/dashboard.py
import re
import json
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
    _run,
)

dash.register_page(__name__, path="/", name="主控台")

LOCAL_TZ = timezone(timedelta(hours=8))
PAGE_SIZE = 20
_ISO_PATTERN = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

def _safe_ts(v):
    if v is None: return ""
    try:
        if isinstance(v, str):
            s = v.strip()
            if not s: return ""
            s_clean = s.replace("Z", "+00:00")
            try: dt = datetime.fromisoformat(s_clean)
            except ValueError: return s[:19]
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(LOCAL_TZ)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(v, "to_native"): v = v.to_native()
        if hasattr(v, "strftime"):
            if getattr(v, "tzinfo", None) is None: v = v.replace(tzinfo=timezone.utc)
            v = v.astimezone(LOCAL_TZ)
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return str(v)
    except Exception:
        return str(v)

def _pretty_reason(text):
    if not text: return ""
    def _repl(m): return f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(4)}:{m.group(5)}"
    return _ISO_PATTERN.sub(_repl, text)

def _render_audit_row(a):
    reason = _pretty_reason(a.get("reason") or a.get("object_id") or "(无描述)")
    return html.Div([
        html.Span(f"[{a.get('action_type') or '?'}]", className="badge-status badge-active me-2"),
        html.Span(reason, style={"flex": "1"}),
        html.Span(_safe_ts(a.get("timestamp")), style={"fontSize": "12px", "color": "var(--c-text-muted)", "fontFamily": "monospace", "whiteSpace": "nowrap", "marginLeft": "12px"}),
    ], className="audit-row")

# ============================================================
# 图表构建
# ============================================================
def _build_trend_chart(days, vals):
    fig = go.Figure()
    if not days:
        days = [(datetime.now() - timedelta(days=i)).strftime("%m/%d") for i in range(6, -1, -1)]
        vals = [0] * 7
    fig.add_trace(go.Scatter(x=days, y=vals, mode="lines+markers", name="噬菌体",
        line=dict(color="#1B6CA8", width=2), marker=dict(size=5), fill="tozeroy", fillcolor="rgba(27,108,168,0.08)"))
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=8, b=0), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        showlegend=False, xaxis=dict(showgrid=False, tickfont=dict(size=11, color="#94A3B8")),
        yaxis=dict(showgrid=True, gridcolor="#E2E8F0", tickfont=dict(size=11, color="#94A3B8"), zeroline=False))
    return fig

def _build_eop_bar(rows):
    fig = go.Figure()
    if not rows: return fig
    wt_x, wt_y, eng_x, eng_y = [], [], [], []
    for r in rows:
        if r.get("is_engineered"):
            eng_x.append(r.get("host_label", "Unknown"))
            eng_y.append(r.get("eop_value", 0))
        else:
            wt_x.append(r.get("host_label", "Unknown"))
            wt_y.append(r.get("eop_value", 0))
            
    fig.add_trace(go.Bar(x=wt_x, y=wt_y, name="野生型 (WT)", marker_color="#94A3B8"))
    fig.add_trace(go.Bar(x=eng_x, y=eng_y, name="编辑型 (Eng)", marker_color="#F59E0B"))
    fig.update_layout(
        barmode='group', height=260, margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, tickfont=dict(size=10)),
        yaxis=dict(title="EOP", showgrid=True, gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

def _build_od_line(rows):
    fig = go.Figure()
    if not rows: return fig
    for r in rows:
        od_str = r.get("od_timeseries")
        if not od_str: continue
        try:
            data = json.loads(od_str) if isinstance(od_str, str) else od_str
            times = [d["t_h"] for d in data]
            ods = [d["od"] for d in data]
            name = f"{'Eng' if r.get('is_engineered') else 'WT'}-{r.get('phage_name','')}"
            fig.add_trace(go.Scatter(x=times, y=ods, mode="lines+markers", name=name, line=dict(width=2)))
        except: pass
    fig.update_layout(
        height=260, margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="时间 (h)", showgrid=True, gridcolor="#E2E8F0"),
        yaxis=dict(title="OD600", showgrid=True, gridcolor="#E2E8F0"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

def _build_biofilm_bar(rows):
    fig = go.Figure()
    if not rows: return fig
    
    # ★ 修改：把处理类型（control_type）也拼接到 Y 轴标签中
    CTYPE_MAP = {
        "engineered_phage": "🧬 工程化",
        "wild_type_phage": "🦠 野生型",
        "free_enzyme": "🧪 游离酶",
        "blank": "⚪ 空白对照"
    }
    names = [
        f"{CTYPE_MAP.get(r.get('control_type'), r.get('control_type') or '未知')} - {str(r.get('phage_id', 'Blank'))[:8]}" 
        for r in rows
    ]
    
    vals = [r.get("biofilm_reduction_pct", 0) for r in rows]
    colors = ["#0D9373" if v > 80 else "#F59E0B" if v > 50 else "#DC2626" for v in vals]
    
    fig.add_trace(go.Bar(
        x=vals, y=names, orientation='h', 
        marker_color=colors, text=[f"{v}%" for v in vals], textposition='auto'
    ))
    fig.update_layout(
        height=260, margin=dict(l=0, r=0, t=20, b=0),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(title="消除率 (%)", showgrid=True, gridcolor="#E2E8F0", range=[0, 105]),
        yaxis=dict(autorange="reversed", tickfont=dict(size=11))
    )
    return fig

# ============================================================
# Learning Engine 横幅
# ============================================================
def _le_badge(state, label, count=None):
    icon_map = {"verified": "bi bi-check-circle-fill", "progress": "bi bi-arrow-repeat", "pending":  "bi bi-hourglass-split"}
    cls_map = {"verified": "le-link-item le-verified", "progress": "le-link-item le-progress", "pending":  "le-link-item le-pending"}
    text_map = {"verified": "已验证", "progress": "进行中", "pending": "待启动"}
    text = f"{label} {text_map[state]}"
    if count is not None: text += f"（{count}）"
    return html.Div([html.I(className=icon_map[state] + " me-1"), text], className=cls_map[state], title=f"{label}：{text_map[state]}")

def _build_le_banner(le):
    reuse, case_linked, pkg_linked = le.get("reuse_events", 0), le.get("case_linked", 0), le.get("pkg_linked", 0)
    approved, total_pkgs = le.get("approved_pkgs", 0), le.get("total_pkgs", 0)
    
    s1 = "verified" if (reuse > 0 and case_linked > 0 and pkg_linked > 0) else "progress" if (reuse > 0 or case_linked > 0 or pkg_linked > 0) else "pending"
    s2 = "verified" if approved > 0 else "progress" if total_pkgs > 0 else "pending"
    s3 = "verified" if reuse > 0 else "pending"
    display_s2_count = approved if approved > 0 else total_pkgs

    return [
        html.Div([html.Div("Learning Engine 状态", className="le-banner-title"), html.Div("验证假设：过去的病例/实验经验能否被编码、审核、复用", style={"fontSize": "12px", "color": "var(--c-text-secondary)"})]),
        html.Div(style={"flex": "1"}),
        _le_badge(s1, "链路 #1", reuse), _le_badge(s2, "链路 #2", display_s2_count), _le_badge(s3, "链路 #3", reuse),
        html.A("查看详情 →", href="/knowledge-graph", style={"fontSize": "12px", "color": "var(--c-primary)", "fontWeight": "600", "textDecoration": "none"}),
    ]

# ============================================================
# 布局
# ============================================================
layout = html.Div([
    # 页头
    html.Div(className="page-header", children=[
        html.Div([html.Div("主控台", className="page-title"), html.Div("平台资产 · 情报闭环 · 实验验证", className="page-subtitle")]),
        html.Div(className="page-actions", children=[
            html.A([html.I(className="bi bi-plus-lg me-1"), "新增噬菌体"], href="/scientific/phage-library", className="btn-primary-custom"),
            html.A([html.I(className="bi bi-folder-plus me-1"), "新建证据包"], href="/scientific/evidence-packages", className="btn-outline-custom"),
        ]),
    ]),

    # 1. 资产 KPI
    html.Div(id="dash-kpi-row", className="mb-4"),

    # 2. Learning Engine 状态
    html.Div(id="dash-le-banner", className="le-banner mb-4"),

    # 3. 实验进度概览
    html.Div(className="surface-card mb-4", children=[
        html.Div([html.I(className="bi bi-bar-chart-steps me-2"), "实验进度概览"], className="surface-card-header"),
        html.Div(id="dash-exp-progress", className="surface-card-body"),
    ]),

    # 4. 近期活动 + 快捷操作
    dbc.Row(className="g-3 mb-4", children=[
        dbc.Col(md=7, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.Span([html.I(className="bi bi-activity me-2"), "近期活动"]), html.A("查看全部 →", href="/admin/audit-log", style={"fontSize": "12px", "color": "var(--c-primary)", "textDecoration": "none"})], className="surface-card-header"),
                html.Div(id="dash-recent-audits", className="surface-card-body dash-scroll-body", children=[]),
            ]),
        ]),
        dbc.Col(md=5, children=[
            html.Div(className="surface-card mb-3", children=[
                html.Div([html.I(className="bi bi-lightning-charge me-2"), "快速操作"], className="surface-card-header"),
                html.Div(className="surface-card-body", children=[
                    dbc.Row(className="g-2", children=[
                        dbc.Col(html.A([html.I(className="bi bi-plus-circle me-2"), "录入噬菌体"], href="/scientific/phage-library", className="btn-primary-custom w-100 justify-content-center"), md=6),
                        dbc.Col(html.A([html.I(className="bi bi-eyedropper me-2"), "记录实验"], href="/scientific/lysis-assay", className="btn-outline-custom w-100 justify-content-center"), md=6),
                        dbc.Col(html.A([html.I(className="bi bi-fingerprint me-2"), "录入酶基因"], href="/scientific/enzyme-gene", className="btn-outline-custom w-100 justify-content-center"), md=6),
                        dbc.Col(html.A([html.I(className="bi bi-bounding-box me-2"), "生物膜实验"], href="/scientific/biofilm-assay", className="btn-outline-custom w-100 justify-content-center"), md=6),
                    ]),
                ]),
            ]),
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-stars me-2"), "AI 快速查询"], className="surface-card-header"),
                html.Div(className="surface-card-body", children=[
                    html.P("向 AI 助手提问，检索将基于结构化 Ontology 数据", style={"fontSize": "12px", "color": "var(--c-text-secondary)", "marginBottom": "10px"}),
                    dbc.InputGroup(className="mb-2", children=[
                        dbc.Input(id="dash-quick-query", placeholder="例如：最近哪个噬菌体复用率最高？", style={"fontSize": "13px"}),
                        dbc.Button(html.I(className="bi bi-arrow-right"), id="btn-quick-query", color="primary"),
                    ]),
                    html.A("进入完整 AI 助手 →", href="/ai-assistant", style={"fontSize": "12px", "color": "var(--c-primary)", "textDecoration": "none"}),
                ]),
            ]),
        ]),
    ]),

    # 5. 统计图（四宫格）
    dbc.Row(className="g-3 mb-4", children=[
        # 左上：EOP 对比
        dbc.Col(md=6, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-bar-chart me-2"), "EOP 感染能力对比 (编辑型 vs 野生型)"], className="surface-card-header"),
                html.Div(dcc.Graph(id="dash-eop-chart", config={"displayModeBar": False}), className="surface-card-body", style={"padding": "12px"}),
            ]),
        ]),
        # 右上：OD 溶菌曲线
        dbc.Col(md=6, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-graph-up me-2"), "溶菌曲线对比 (OD600)"], className="surface-card-header"),
                html.Div(dcc.Graph(id="dash-od-chart", config={"displayModeBar": False}), className="surface-card-body", style={"padding": "12px"}),
            ]),
        ]),
        # 左下：生物膜排行
        dbc.Col(md=6, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-bounding-box me-2"), "生物膜消除率排行 Top 10"], className="surface-card-header"),
                html.Div(dcc.Graph(id="dash-biofilm-chart", config={"displayModeBar": False}), className="surface-card-body", style={"padding": "12px"}),
            ]),
        ]),
        # 右下：趋势
        dbc.Col(md=6, children=[
            html.Div(className="surface-card", children=[
                html.Div([html.I(className="bi bi-graph-up-arrow me-2"), "噬菌体录入趋势（7日）"], className="surface-card-header"),
                html.Div(dcc.Graph(id="dash-trend-chart", config={"displayModeBar": False}), className="surface-card-body", style={"padding": "12px"}),
            ]),
        ]),
    ]),

    # 隐藏控件
    html.Button(id="btn-audit-load-more", n_clicks=0, style={"display": "none"}),
    dcc.Store(id="audit-page", data=1),
    dcc.Store(id="audit-scroll-hook", data=0),
    dcc.Interval(id="interval-dashboard", interval=7_200_000, n_intervals=0),
])


# ============================================================
# 主回调
# ============================================================
@callback(
    Output("dash-kpi-row", "children"),
    Output("dash-exp-progress", "children"),
    Output("dash-eop-chart", "figure"),
    Output("dash-od-chart", "figure"),
    Output("dash-biofilm-chart", "figure"),
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
        return (dbc.Alert(f"加载失败：{e}", color="danger"), "", go.Figure(), go.Figure(), go.Figure(), go.Figure(), "")

    kpis = dbc.Row(className="g-3", children=[
        dbc.Col(kpi_card("噬菌体", s.get("phages", 0), "bi bi-virus", theme="blue", href="/scientific/phage-library"), md=3),
        dbc.Col(kpi_card("临床病例", s.get("cases", 0), "bi bi-journal-medical", theme="green", href="/scientific/clinical-cases"), md=3),
        dbc.Col(kpi_card("情报事件", s.get("events", 0), "bi bi-broadcast", theme="amber", href="/ci/events"), md=3),
        dbc.Col(kpi_card("监控组织", s.get("orgs", 0), "bi bi-building", theme="red", href="/ci/intelligence-board"), md=3),
    ])

    try:
        exp = _run("""
            CALL { MATCH (e:EnzymeGene) RETURN count(e) AS enz_total, count(CASE WHEN e.status='validated' THEN 1 END) AS enz_done }
            CALL { MATCH (p:Phage) WHERE p.is_engineered = true RETURN count(p) AS eng_total, count(CASE WHEN p.engineering_status IN ['sanger_verified', 'functionally_validated'] THEN 1 END) AS eng_done }
            CALL { MATCH (b:BiofilmAssay) RETURN count(b) AS bio_total, count(CASE WHEN b.status='completed' THEN 1 END) AS bio_done }
            RETURN enz_total, enz_done, eng_total, eng_done, bio_total, bio_done
        """)[0]
        
        def _progress_bar(label, done, total):
            pct = round((done / total * 100), 1) if total > 0 else 0
            color = "success" if pct >= 80 else "warning" if pct >= 40 else "danger"
            return html.Div([
                html.Div([html.Span(label, style={"fontWeight": "600", "fontSize": "13px"}), html.Span(f"{done} / {total}", style={"float": "right", "fontSize": "12px", "color": "var(--c-text-muted)"})], className="mb-1"),
                dbc.Progress(value=pct, color=color, style={"height": "8px"}),
            ], className="mb-3")

        progress_ui = [
            dbc.Row([
                dbc.Col(_progress_bar("🧪 酶筛选验证", exp["enz_done"], exp["enz_total"]), md=4),
                dbc.Col(_progress_bar("🧬 工程化改造", exp["eng_done"], exp["eng_total"]), md=4),
                dbc.Col(_progress_bar("🔬 功能验证 (生物膜)", exp["bio_done"], exp["bio_total"]), md=4),
            ])
        ]
    except Exception:
        progress_ui = dbc.Alert("加载进度失败", color="warning")

    try:
        assay_rows = _run("""
            MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
            WHERE a.eop_value IS NOT NULL OR a.od_timeseries IS NOT NULL
            RETURN ph.name AS phage_name, ph.is_engineered AS is_engineered,
                   h.strain_label AS host_label, a.eop_value AS eop_value, a.od_timeseries AS od_timeseries
            LIMIT 20
        """)
        eop_fig = _build_eop_bar(assay_rows)
        od_fig = _build_od_line(assay_rows)
    except Exception:
        eop_fig, od_fig = go.Figure(), go.Figure()

    try:
        # ★ 修改：查询中加入了 b.control_type AS control_type
        bio_rows = _run("""
            MATCH (b:BiofilmAssay)
            WHERE b.biofilm_reduction_pct IS NOT NULL
            RETURN b.id AS id, b.phage_id AS phage_id, 
                   b.control_type AS control_type,
                   b.biofilm_reduction_pct AS biofilm_reduction_pct
            ORDER BY b.biofilm_reduction_pct DESC LIMIT 10
        """)
        bio_fig = _build_biofilm_bar(bio_rows)
    except Exception:
        bio_fig = go.Figure()

    try:
        days, vals = phage_trend_7d()
    except Exception:
        days, vals = [], []
    trend_fig = _build_trend_chart(days, vals)

    try:
        le = learning_engine_status()
    except Exception:
        le = {}
    le_banner = _build_le_banner(le)

    return kpis, progress_ui, eop_fig, od_fig, bio_fig, trend_fig, le_banner

# ============================================================
# 活动流回调
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

    if triggered == "btn-audit-load-more":
        offset = page * PAGE_SIZE
        try: new_rows = list_audit_events(limit=PAGE_SIZE, offset=offset)
        except: new_rows = []

        if not new_rows:
            patched = Patch()
            patched.append(html.Div("— 已加载全部记录 —", className="audit-end-hint"))
            return patched, page

        patched = Patch()
        for a in new_rows: patched.append(_render_audit_row(a))
        return patched, page + 1

    try: rows = list_audit_events(limit=PAGE_SIZE, offset=0)
    except: rows = []

    if not rows:
        return ([html.Div("暂无审计记录", style={"color": "var(--c-text-muted)", "fontSize": "13px", "padding": "20px 0", "textAlign": "center"})], 1)

    return ([_render_audit_row(a) for a in rows], 1)

clientside_callback(
    """
    function(_) {
        var el = document.getElementById('dash-recent-audits');
        if (!el || el.__scrollBound) return window.dash_clientside.no_update;
        el.__scrollBound = true;
        el.addEventListener('scroll', function() {
            var nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
            if (!nearBottom) return;
            if (el.querySelector('.audit-end-hint')) return;
            var btn = document.getElementById('btn-audit-load-more');
            if (btn && !btn.__loading) {
                btn.__loading = true; btn.click();
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