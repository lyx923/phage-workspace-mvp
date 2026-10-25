# app.py
import os
from datetime import timedelta

import dash
import dash_bootstrap_components as dbc
from dash import html, dcc, Input, Output, State, no_update, clientside_callback
from flask import session

from components.navbar import create_navbar
from components.sidebar import create_sidebar
from components.confirm_dialog import create_confirm_dialog

app = dash.Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP],
    suppress_callback_exceptions=True,
    title="AI 精准抗感染平台",
)
server = app.server

# ============================================================
# ★ 认证配置
# ============================================================
server.secret_key = os.environ.get(
    "DASH_SECRET_KEY", "dev-secret-change-me-in-prod"
)
server.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=7)
server.config["SESSION_COOKIE_HTTPONLY"] = True
server.config["SESSION_COOKIE_SAMESITE"] = "Lax"

BREADCRUMB_MAP = {
    "/":                             [("主控台", None)],
    "/scientific/phage-library":     [("科学域", None), ("噬菌体库", None)],
    "/scientific/host-strain":       [("科学域", None), ("宿主菌株图谱", None)],
    "/scientific/enzyme-gene":       [("科学域", None), ("酶基因库", None)],
    "/scientific/lysis-assay":       [("科学域", None), ("裂解实验", None)],
    "/scientific/biofilm-assay":     [("科学域", None), ("生物膜实验", None)],
    "/scientific/clinical-cases":    [("科学域", None), ("临床病例", None)],
    "/scientific/evidence-packages": [("科学域", None), ("证据包管理", None)],
    "/ci/intelligence-board":        [("情报域", None), ("情报概览", None)],
    "/ci/programs":                  [("情报域", None), ("开发项目", None)],
    "/ci/events":                    [("情报域", None), ("情报事件", None)],
    "/ci/strategies":                [("情报域", None), ("工程策略", None)],
    "/ci/tech-assessment":           [("情报域", None), ("技术评估", None)],
    "/ci/decision-records":          [("情报域", None), ("决策记录", None)],
    "/knowledge-graph":              [("知识图谱", None)],
    "/ai-assistant":                 [("AI 助手", None)],
    "/admin/experiment-batch":       [("系统管理", None), ("实验批次", None)],
    "/admin/data-import":            [("系统管理", None), ("数据导入", None)],
    "/admin/schema":                 [("系统管理", None), ("Schema 管理", None)],
    "/admin/schema-registry":        [("系统管理", None), ("Schema 版本", None)],
    "/admin/audit-log":              [("系统管理", None), ("审计日志", None)],
    "/admin/ontology-module":        [("系统管理", None), ("Ontology 模块", None)],
    "/login":                        [("登录", None)],
}

def _build_breadcrumb(pathname: str):
    crumbs = BREADCRUMB_MAP.get(
        pathname, [(pathname.strip("/") or "主控台", None)])
    items = []
    for i, (label, href) in enumerate(crumbs):
        is_last = i == len(crumbs) - 1
        if is_last:
            items.append(html.Li(label, className="breadcrumb-item active",
                                  **{"aria-current": "page"}))
        else:
            items.append(html.Li(
                html.A(label, href=href, className="bc-link") if href else label,
                className="breadcrumb-item"))
    return html.Nav(
        html.Ol(items, className="breadcrumb mb-0"),
        className="breadcrumb-nav",
        **{"aria-label": "breadcrumb"},
    )

# ============================================================
# 布局
# ============================================================
app.layout = html.Div(
    id="app-root",
    className="app-root",
    children=[
        # ★ 顶部进度条（fixed 定位，永远在最上层，不占空间）
        html.Div(id="top-progress"),
        # ★ 隐藏占位：用于触发 clientside_callback
        dcc.Store(id="progress-hook", data=0),

        dcc.Location(id="url", refresh=False),
        
        # 全局跳转信号
        dcc.Store(id="store-global-redirect", data=None),

        dcc.Store(id="store-sidebar-collapsed", data=True),
        dcc.Store(id="store-chat-history", data=[]),
        dcc.Store(id="store-confirm-payload", data=None),
        dcc.Store(id="store-active-danger-id", data=None),
        dcc.Store(id="store-db-stats", data={}),
        dcc.Store(id="mega-menu-toggle-store", data=0),
        dcc.Store(id="store-schema-pending", data=False),
        dcc.Store(id="store-kg-fullscreen", data=0),
        dcc.Store(id="store-notify-open", data=False),

        dcc.Interval(id="interval-global", interval=7_200_000, n_intervals=0),
        dcc.Interval(id="interval-badge", interval=600_000, n_intervals=0),

        create_navbar(),

        html.Div(
            className="shell-wrapper",
            children=[
                create_sidebar(),
                html.Div(
                    id="main-area",
                    className="main-area expanded",
                    children=[
                        html.Div(id="breadcrumb-bar", className="breadcrumb-bar"),
                        html.Div(
                            id="page-outlet",
                            className="page-outlet",
                            children=[dash.page_container],
                        ),
                    ],
                ),
            ],
        ),

        html.Div(
            className="status-bar",
            children=[
                html.Span(id="status-neo4j", className="status-item",
                          children=[html.Span(className="status-dot dot-ok"), " Neo4j 已连接"]),
                html.Span(id="status-llm", className="status-item",
                          children=[html.Span(className="status-dot dot-ok"), " DeepSeek 已配置"]),
                html.Span(id="status-sync-time", className="status-item"),
                html.Span("lyx", className="status-user"),
            ],
        ),

        html.Div(
            id="notify-toast",
            style={"display": "none"},
            children=[
                html.Button(html.I(className="bi bi-x-lg"), id="btn-notify-close", n_clicks=0, style={"position": "absolute", "top": "10px", "right": "10px", "background": "none", "border": "none", "color": "var(--c-text-muted)", "cursor": "pointer", "fontSize": "14px", "padding": "4px"}),
                html.Div("通知中心", style={"fontWeight": "700", "marginBottom": "8px", "paddingBottom": "6px", "borderBottom": "1px solid var(--c-border)"}),
                html.Div(id="notify-body"),
            ],
        ),

        create_confirm_dialog(),
    ],
)

# ============================================================
# ★ 顶部进度条 hook：监听所有 _dash-update-component 请求
# ============================================================
clientside_callback(
    """
    function(_) {
        if (window.__topProgressBound) {
            return window.dash_clientside.no_update;
        }
        window.__topProgressBound = true;

        var pending = 0;

        function show() {
            var bar = document.getElementById('top-progress');
            if (bar) bar.classList.add('loading');
        }
        function hide() {
            var bar = document.getElementById('top-progress');
            if (bar) bar.classList.remove('loading');
        }

        // ── 拦截 XMLHttpRequest（Dash 用 XHR 发回调） ──
        var origOpen = XMLHttpRequest.prototype.open;
        var origSend = XMLHttpRequest.prototype.send;

        XMLHttpRequest.prototype.open = function() {
            this.__url = arguments[1] || '';
            return origOpen.apply(this, arguments);
        };
        XMLHttpRequest.prototype.send = function() {
            var isDash = (this.__url || '').indexOf('_dash-update-component') !== -1;
            if (isDash) {
                pending += 1;
                show();
                this.addEventListener('loadend', function() {
                    pending = Math.max(0, pending - 1);
                    if (pending === 0) hide();
                });
            }
            return origSend.apply(this, arguments);
        };

        // ── 拦截 fetch（有的 Dash 版本用 fetch） ──
        var origFetch = window.fetch;
        if (origFetch) {
            window.fetch = function() {
                var url = (arguments[0] && arguments[0].url) || arguments[0] || '';
                var isDash = String(url).indexOf('_dash-update-component') !== -1;
                if (isDash) {
                    pending += 1;
                    show();
                    return origFetch.apply(this, arguments).finally(function() {
                        pending = Math.max(0, pending - 1);
                        if (pending === 0) hide();
                    });
                }
                return origFetch.apply(this, arguments);
            };
        }

        return 1;
    }
    """,
    Output("progress-hook", "data"),
    Input("progress-hook", "data"),
    prevent_initial_call=False,
)

# ============================================================
# ★ 全局 JS 跳转回调 (绝对生效)
# ============================================================
clientside_callback(
    """
    function(target) {
        if (target) {
            window.location.href = target;
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("store-global-redirect", "id"),
    Input("store-global-redirect", "data"),
    prevent_initial_call=True,
)

# ============================================================
# 侧边栏 / 面包屑
# ============================================================
@app.callback(
    Output("sidebar-panel", "className"),
    Output("main-area", "className"),
    Output("store-sidebar-collapsed", "data"),
    Input("btn-sidebar-toggle", "n_clicks"),
    Input("url", "pathname"),
    prevent_initial_call=True,
)
def cb_sidebar_toggle(n_clicks, _pathname):
    from dash import ctx
    if ctx.triggered_id == "url":
        return no_update, no_update, no_update
    expanded = (n_clicks or 0) % 2 == 1
    if expanded:
        return "sidebar-panel expanded", "main-area collapsed", False
    return "sidebar-panel collapsed", "main-area expanded", True

@app.callback(
    Output("breadcrumb-bar", "children"),
    Input("url", "pathname"),
)
def cb_breadcrumb(pathname):
    return _build_breadcrumb(pathname or "/")

# ============================================================
# 状态栏 / 徽章 / 通知
# ============================================================
@app.callback(
    Output("status-sync-time", "children"),
    Input("interval-global", "n_intervals"),
)
def cb_sync_time(_):
    from datetime import datetime
    return f"最后同步: {datetime.now().strftime('%H:%M:%S')}"

@app.callback(
    Output("status-neo4j", "children"),
    Input("interval-global", "n_intervals"),
)
def cb_neo4j_status(_):
    try:
        from config import get_driver
        with get_driver().session() as s:
            s.run("RETURN 1").single()
        return [html.Span(className="status-dot dot-ok"), " Neo4j 已连接"]
    except Exception:
        return [html.Span(className="status-dot dot-error"), " Neo4j 未连接"]

@app.callback(
    Output("status-llm", "children"),
    Input("interval-global", "n_intervals"),
)
def cb_llm_status(_):
    try:
        from config import Config
        key = (getattr(Config, "DS_API_KEY", "")
               or getattr(Config, "DEEPSEEK_API_KEY", ""))
        if key:
            return [html.Span(className="status-dot dot-ok"), " DeepSeek 已配置"]
        return [html.Span(className="status-dot dot-warning"), " DeepSeek 未配置"]
    except Exception:
        return [html.Span(className="status-dot dot-warning"), " DeepSeek 未配置"]

@app.callback(
    Output("badge-review", "children"),
    Input("interval-badge", "n_intervals"),
)
def cb_badge_review(_):
    try:
        from config import get_driver
        with get_driver().session() as s:
            rec = s.run("MATCH (r:Review) WHERE r.decision = 'pending' RETURN count(r) AS n").single()
            n = rec["n"] if rec else 0
        return str(n) if n > 0 else ""
    except Exception:
        return ""

@app.callback(
    Output("notify-toast", "style"),
    Output("store-notify-open", "data"),
    Input("btn-notify", "n_clicks"),
    State("store-notify-open", "data"),
    prevent_initial_call=True,
)
def cb_notify_toggle(n_clicks, is_open):
    if is_open:
        return {"display": "none"}, False
    return (
        {"position": "fixed", "top": "68px", "right": "20px",
         "zIndex": "2000", "width": "320px", "display": "block",
         "background": "var(--c-surface)", "border": "1px solid var(--c-border)",
         "borderRadius": "10px", "padding": "16px",
         "boxShadow": "0 8px 24px rgba(0,0,0,0.12)"},
        True,
    )

@app.callback(
    Output("notify-body", "children"),
    Input("store-notify-open", "data"),
    Input("interval-badge", "n_intervals"),
)
def cb_notify_body(is_open, _):
    if not is_open:
        return []
    pending_count = 0
    danger_events = []
    try:
        from config import get_driver
        with get_driver().session() as s:
            rec = s.run("MATCH (r:Review) WHERE r.decision = 'pending' RETURN count(r) AS n").single()
            pending_count = rec["n"] if rec else 0
            rows = list(s.run("""
                MATCH (a:AuditEvent)
                WHERE a.action_type IN ['DANGER_OP', 'DELETE']
                RETURN a.audit_id AS id, a.action_type AS action, a.object_id AS obj, a.timestamp AS ts
                ORDER BY a.timestamp DESC LIMIT 3
            """))
            danger_events = [dict(r) for r in rows]
    except Exception:
        pass

    items = []
    if pending_count > 0:
        items.append(html.Div([
            html.I(className="bi bi-clipboard-check me-2", style={"color": "var(--c-primary)"}),
            html.Span(f"有 {pending_count} 个待审核项"),
            html.A("去处理 →", href="/admin/audit-log", style={"float": "right", "fontSize": "12px", "color": "var(--c-primary)", "textDecoration": "none"}),
        ], style={"padding": "8px 0", "borderBottom": "1px solid var(--c-border)"}))

    for e in danger_events[:3]:
        items.append(html.Div([
            html.I(className="bi bi-exclamation-triangle me-2", style={"color": "var(--c-danger)"}),
            html.Span(f"[{e['action']}] {e.get('obj', '')}", style={"fontSize": "12px"}),
        ], style={"padding": "6px 0"}))

    if not items:
        items = [html.Div("暂无新通知", style={"color": "var(--c-text-muted)", "textAlign": "center", "padding": "12px 0"})]
    return items

@app.callback(
    Output("notify-toast", "style", allow_duplicate=True),
    Output("store-notify-open", "data", allow_duplicate=True),
    Input("btn-notify-close", "n_clicks"),
    prevent_initial_call=True,
)
def cb_notify_close(_):
    return {"display": "none"}, False

# ============================================================
# ★ 全局未登录拦截
# ============================================================
@app.callback(
    Output("url", "pathname", allow_duplicate=True),
    Input("url", "pathname"),
    prevent_initial_call="initial_duplicate",
)
def auth_guard(pathname):
    if not pathname:
        return no_update
    user = session.get("user")
    
    # 如果没登录，且不在登录页，强行踢回登录页
    if not user and pathname != "/login":
        return "/login"
        
    return no_update

# ============================================================
# ★ 退出登录 (发送跳转信号给前端)
# ============================================================
@app.callback(
    Output("store-global-redirect", "data", allow_duplicate=True),
    Input("btn-logout", "n_clicks"),
    prevent_initial_call=True,
)
def cb_logout(n_clicks):
    if not n_clicks:
        return no_update
    from auth import logout_user
    logout_user()
    return "/login"  # 触发全局 JS 跳转到登录页

# ============================================================
# ★ 顶栏用户信息同步
# ============================================================
@app.callback(
    Output("navbar-user-name", "children"),
    Output("user-menu-info", "children"),
    Input("url", "pathname"),
)
def cb_sync_user_display(_pathname):
    user = session.get("user")
    if user:
        return (
            user.get("name", user.get("username", "用户")),
            [
                html.Div([
                    html.I(className="bi bi-person-circle me-2"),
                    html.Span(user.get("name", user.get("username", "")), style={"fontWeight": "600"}),
                ]),
                html.Div(f"@{user.get('username', '')} · {user.get('role', '')}", style={"fontSize": "11px", "color": "var(--c-text-muted)"}),
            ],
        )
    return "登录", [html.Div("未登录", style={"fontSize": "13px"})]

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=8501)