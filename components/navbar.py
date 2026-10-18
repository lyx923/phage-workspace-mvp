# components/navbar.py
from dash import html, dcc, clientside_callback, Input, Output, no_update

# ─────────────────────────────────────────────
# Mega Menu 定义
# ─────────────────────────────────────────────
SCIENTIFIC_MENU = [
    {"section": "研究对象", "items": [
        ("bi bi-virus",      "噬菌体库",   "/scientific/phage-library"),
        ("bi bi-diagram-3",  "宿主菌株图谱", "/scientific/host-strain"),
    ]},
    {"section": "实验与结果", "items": [
        ("bi bi-eyedropper",       "裂解实验记录", "/scientific/lysis-assay"),
        ("bi bi-journal-medical",  "临床病例",     "/scientific/clinical-cases"),
        ("bi bi-folder2-open",     "证据包管理",   "/scientific/evidence-packages"),
    ]},
]

CI_MENU = [
    {"section": "情报与决策", "items": [
        ("bi bi-bar-chart-line",     "情报概览", "/ci/intelligence-board"),
        ("bi bi-building",           "开发项目", "/ci/programs"),
        ("bi bi-broadcast",          "情报事件", "/ci/events"),
        ("bi bi-file-earmark-check", "决策记录", "/ci/decision-records"),
    ]},
    {"section": "工程分析", "items": [
        ("bi bi-cpu",             "工程策略", "/ci/strategies"),
        ("bi bi-graph-up-arrow",  "技术评估", "/ci/tech-assessment"),
    ]},
]

ADMIN_MENU = [
    {"section": "数据管理", "items": [
        ("bi bi-cloud-upload",  "数据导入",     "/admin/data-import"),
        ("bi bi-database-gear", "Schema 管理", "/admin/schema"),
    ]},
    {"section": "审计与治理", "items": [
        ("bi bi-shield-check", "审计日志",       "/admin/audit-log"),
        ("bi bi-puzzle",       "Ontology 模块", "/admin/ontology-module"),
    ]},
]


def _build_mega_col(menu_def):
    cols = []
    for section in menu_def:
        items = [
            html.A(
                [html.I(className=f"{icon} icon"), html.Span(label)],
                href=href, className="mega-menu-item",
            )
            for icon, label, href in section["items"]
        ]
        cols.append(html.Div([
            html.Div(section["section"], className="mega-menu-section-title"),
            html.Div(items),
        ], className="mega-menu-col"))
    return cols


# ─────────────────────────────────────────────
# 顶栏
# ─────────────────────────────────────────────
def create_navbar():
    return html.Header(
        className="top-navbar",
        children=[
            html.Button(html.I(className="bi bi-list"),
                        id="btn-sidebar-toggle",
                        className="btn-sidebar-toggle", n_clicks=0),
            html.A(
                [
                    html.Div("AI", className="brand-icon"),
                    html.Span("助手", className="brand-name"),
                    html.Span("v0.6", className="brand-version"),
                ],
                href="/", className="navbar-brand-box",
            ),
            html.A("主控台", href="/", className="nav-item-btn"),

            # 科学域 Mega
            html.Div(style={"position": "relative"}, children=[
                html.Button(
                    ["科学域", html.I(className="bi bi-chevron-down caret ms-1")],
                    id="nav-scientific-btn", className="nav-item-btn", n_clicks=0,
                ),
                html.Div(id="mega-scientific", className="mega-menu",
                         children=_build_mega_col(SCIENTIFIC_MENU)),
            ]),

            # 情报域 Mega
            html.Div(style={"position": "relative"}, children=[
                html.Button(
                    ["情报域", html.I(className="bi bi-chevron-down caret ms-1")],
                    id="nav-ci-btn", className="nav-item-btn", n_clicks=0,
                ),
                html.Div(id="mega-ci", className="mega-menu",
                         children=_build_mega_col(CI_MENU)),
            ]),

            html.A("知识图谱", href="/knowledge-graph", className="nav-item-btn"),
            html.A([html.I(className="bi bi-stars me-1"), "AI 助手"],
                   href="/ai-assistant", className="nav-item-btn"),

            # 右侧
            html.Div(className="navbar-right", children=[
                html.A(
                    [html.I(className="bi bi-clipboard-check"),
                     html.Span("0", className="badge-count", id="badge-review")],
                    href="/admin/audit-log",
                    className="icon-btn", title="审核队列",
                ),
                html.Button(html.I(className="bi bi-bell"),
                            id="btn-notify", className="icon-btn",
                            n_clicks=0, title="通知"),
                # 系统管理 Mega（右侧对齐）
                html.Div(style={"position": "relative"}, children=[
                    html.Button(html.I(className="bi bi-gear"),
                                id="nav-admin-btn", className="icon-btn",
                                n_clicks=0, title="系统管理"),
                    html.Div(id="mega-admin", className="mega-menu",
                             style={"right": "0", "left": "auto",
                                    "minWidth": "340px"},
                             children=_build_mega_col(ADMIN_MENU)),
                ]),

                # ★ 用户菜单（替代原 btn-user）
                html.Div(className="user-menu-wrap", children=[
                    html.Button(
                        [
                            html.I(className="bi bi-person-circle"),
                            html.Span(id="navbar-user-name", children="登录"),
                        ],
                        id="btn-user-menu",
                        className="user-menu-btn",
                        n_clicks=0,
                        title="用户菜单",
                    ),
                    html.Div(
                        id="user-menu-dropdown",
                        className="user-menu-dropdown",
                        children=[
                            html.Div(id="user-menu-info",
                                     className="user-menu-info",
                                     children=[
                                         html.Div("未登录",
                                                  style={"fontSize": "13px"}),
                                     ]),
                            html.Div(className="user-menu-divider"),
                            html.Button(
                                [html.I(className="bi bi-box-arrow-right me-2"),
                                 "退出登录"],
                                id="btn-logout",
                                className="user-menu-item logout",
                                n_clicks=0,
                            ),
                        ],
                    ),
                ]),
            ]),
        ],
    )


# ─────────────────────────────────────────────
# Mega Menu 交互：clientside_callback
# ─────────────────────────────────────────────
clientside_callback(
    """
    function(n1, n2, n3) {
        function closeAll() {
            ['mega-scientific', 'mega-ci', 'mega-admin'].forEach(function(id) {
                var el = document.getElementById(id);
                if (el) el.classList.remove('show');
            });
        }
        var triggered = dash_clientside.callback_context.triggered;
        if (!triggered || triggered.length === 0)
            return window.dash_clientside.no_update;
        var tid = triggered[0]['prop_id'].split('.')[0];
        closeAll();
        if (tid === 'nav-scientific-btn') {
            var el = document.getElementById('mega-scientific');
            if (el) el.classList.toggle('show');
        } else if (tid === 'nav-ci-btn') {
            var el = document.getElementById('mega-ci');
            if (el) el.classList.toggle('show');
        } else if (tid === 'nav-admin-btn') {
            var el = document.getElementById('mega-admin');
            if (el) el.classList.toggle('show');
        }
        return (new Date()).getTime();
    }
    """,
    Output("mega-menu-toggle-store", "data"),
    Input("nav-scientific-btn", "n_clicks"),
    Input("nav-ci-btn", "n_clicks"),
    Input("nav-admin-btn", "n_clicks"),
    prevent_initial_call=True,
)


# 点击页面其他区域关闭所有 Mega Menu（只绑定一次）
clientside_callback(
    """
    function(_) {
        if (!window.__megaMenuBound) {
            window.__megaMenuBound = true;
            document.addEventListener('click', function(e) {
                var menus = ['mega-scientific', 'mega-ci', 'mega-admin'];
                var btns  = ['nav-scientific-btn', 'nav-ci-btn', 'nav-admin-btn'];
                var inside = menus.concat(btns).some(function(id) {
                    var el = document.getElementById(id);
                    return el && el.contains(e.target);
                });
                if (!inside) {
                    menus.forEach(function(id) {
                        var el = document.getElementById(id);
                        if (el) el.classList.remove('show');
                    });
                }
            });
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("mega-menu-toggle-store", "id"),
    Input("mega-menu-toggle-store", "id"),
    prevent_initial_call=False,
)


# ─────────────────────────────────────────────
# ★ 用户菜单：点击切换显示/隐藏
# ─────────────────────────────────────────────
clientside_callback(
    """
    function(n) {
        if (!n) return window.dash_clientside.no_update;
        var dd = document.getElementById('user-menu-dropdown');
        if (!dd) return window.dash_clientside.no_update;
        dd.classList.toggle('show');
        return dd.className;
    }
    """,
    Output("user-menu-dropdown", "className"),
    Input("btn-user-menu", "n_clicks"),
    prevent_initial_call=True,
)


# ─────────────────────────────────────────────
# ★ 用户菜单：点击外部区域关闭（只绑定一次）
# ─────────────────────────────────────────────
clientside_callback(
    """
    function(_) {
        if (!window.__userMenuBound) {
            window.__userMenuBound = true;
            document.addEventListener('click', function(e) {
                var wrap = document.querySelector('.user-menu-wrap');
                var dd = document.getElementById('user-menu-dropdown');
                if (!wrap || !dd) return;
                if (!wrap.contains(e.target)) {
                    dd.classList.remove('show');
                }
            });
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("btn-user-menu", "title"),
    Input("btn-user-menu", "title"),
    prevent_initial_call=False,
)