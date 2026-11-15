# components/navbar.py
from dash import html, dcc, clientside_callback, Input, Output, callback, no_update
from flask import session
from config import Config, get_driver

SCIENTIFIC_MENU = [
    {"section": "研究对象", "items": [
        ("bi bi-virus", "噬菌体库", "/scientific/phage-library"),
        ("bi bi-diagram-3", "宿主菌株图谱", "/scientific/host-strain"),
    ]},
    {"section": "实验与结果", "items": [
        ("bi bi-bezier2", "酶基因库", "/scientific/enzyme-gene"),
        ("bi bi-eyedropper", "裂解实验记录", "/scientific/lysis-assay"),
        ("bi bi-bounding-box", "生物膜实验", "/scientific/biofilm-assay"),
        ("bi bi-journal-medical", "临床病例", "/scientific/clinical-cases"),
        ("bi bi-folder2-open", "证据包管理", "/scientific/evidence-packages"),
    ]},
]

CI_MENU = [
    {"section": "情报与决策", "items": [
        ("bi bi-bar-chart-line", "情报概览", "/ci/intelligence-board"),
        ("bi bi-building", "开发项目", "/ci/programs"),
        ("bi bi-broadcast", "情报事件", "/ci/events"),
        ("bi bi-file-earmark-check", "决策记录", "/ci/decision-records"),
    ]},
    {"section": "工程分析", "items": [
        ("bi bi-cpu", "工程策略", "/ci/strategies"),
        ("bi bi-graph-up-arrow", "技术评估", "/ci/tech-assessment"),
    ]},
]

ADMIN_MENU = [
    {"section": "数据管理", "items": [
        ("bi bi-people", "用户管理", "/admin/user-manage"),
        ("bi bi-person-badge", "角色管理", "/admin/role-manage"),
        ("bi bi-layers", "实验批次", "/admin/experiment-batch"),
        ("bi bi-cloud-upload", "数据导入", "/admin/data-import"),
        ("bi bi-database-gear", "Schema 管理", "/admin/schema"),
    ]},
    {"section": "审计与治理", "items": [
        ("bi bi-code-square", "Schema 版本", "/admin/schema-registry"),
        ("bi bi-shield-check", "审计日志", "/admin/audit-log"),
        ("bi bi-puzzle", "Ontology 模块", "/admin/ontology-module"),
    ]},
]

def _build_mega_col(menu_def):
    cols = []
    for section in menu_def:
        items = [
            html.A(
                [html.I(className=f"{icon} icon", style={"marginRight": "8px"}), html.Span(label)],
                href=href, className="mega-menu-item",
            )
            for icon, label, href in section["items"]
        ]
        cols.append(html.Div([
            html.Div(section["section"], className="mega-menu-section-title"),
            html.Div(items),
        ], className="mega-menu-col"))
    return cols

def _get_user_perms():
    user = session.get("user")
    if not user: return set()
    if user.get("role") == "admin": return {"system:admin:all"}
    try:
        with get_driver().session() as s:
            res = s.run("""
                MATCH (u:User {username: $uname})-[:HAS_ROLE]->(:Role)-[:HAS_PERMISSION]->(p:Permission)
                RETURN collect(p.perm_key) AS perms
            """, uname=user["username"]).single()
            return set(res["perms"]) if res and res["perms"] else set()
    except Exception:
        return set()

def create_navbar():
    version_str = getattr(Config, "APP_VERSION", "0.8.0-EXP")
    short_ver = "v" + ".".join(version_str.split("-")[0].split(".")[:2])
    
    return html.Header(
        className="top-navbar",
        children=[
            dcc.Store(id="navbar-init-hook", data=0),
            html.Button(html.I(className="bi bi-list"), id="btn-sidebar-toggle", className="btn-sidebar-toggle", n_clicks=0),
            html.A([html.Div("AI", className="brand-icon"), html.Span("助手", className="brand-name"), html.Span(short_ver, className="brand-version")], href="/", className="navbar-brand-box"),
            html.A("主控台", href="/", className="nav-item-btn"),
            
            html.Div(id="nav-item-scientific", style={"position": "relative", "display": "none"}, children=[
                html.Button(["科学域", html.I(className="bi bi-chevron-down caret ms-1")], id="nav-scientific-btn", className="nav-item-btn", n_clicks=0),
                html.Div(id="mega-scientific", className="mega-menu", children=_build_mega_col(SCIENTIFIC_MENU)),
            ]),
            
            html.Div(id="nav-item-ci", style={"position": "relative", "display": "none"}, children=[
                html.Button(["情报域", html.I(className="bi bi-chevron-down caret ms-1")], id="nav-ci-btn", className="nav-item-btn", n_clicks=0),
                html.Div(id="mega-ci", className="mega-menu", children=_build_mega_col(CI_MENU)),
            ]),

            html.A("知识图谱", href="/knowledge-graph", className="nav-item-btn"),
            html.A([html.I(className="bi bi-stars me-1"), "AI 助手"], href="/ai-assistant", className="nav-item-btn"),
            
            html.Div(className="navbar-right", children=[
                html.A([html.I(className="bi bi-clipboard-check"), html.Span("0", className="badge-count", id="badge-review")], href="/admin/audit-log", className="icon-btn", title="审核队列"),
                html.Button(html.I(className="bi bi-bell"), id="btn-notify", className="icon-btn", n_clicks=0, title="通知"),
                
                html.Div(id="nav-item-admin", style={"position": "relative", "display": "none"}, children=[
                    html.Button(html.I(className="bi bi-gear"), id="nav-admin-btn", className="icon-btn", n_clicks=0, title="系统管理"),
                    html.Div(id="mega-admin", className="mega-menu", style={"right": "0", "left": "auto", "minWidth": "340px"}, children=_build_mega_col(ADMIN_MENU)),
                ]),
                
                html.Div(className="user-menu-wrap", children=[
                    html.Button([html.I(className="bi bi-person-circle"), html.Span(id="navbar-user-name", children="登录")], id="btn-user-menu", className="user-menu-btn", n_clicks=0, title="用户菜单"),
                    html.Div(
                        id="user-menu-dropdown", className="user-menu-dropdown",
                        children=[
                            html.Div(id="user-menu-info", className="user-menu-info", children=[html.Div("未登录", style={"fontSize": "13px"})]),
                            html.Div(className="user-menu-divider"),
                            html.Button([html.I(className="bi bi-box-arrow-right me-2"), "退出登录"], id="btn-logout", className="user-menu-item logout", n_clicks=0),
                        ],
                    ),
                ]),
            ]),
        ],
    )

@callback(
    Output("nav-item-scientific", "style"),
    Output("nav-item-ci", "style"),
    Output("nav-item-admin", "style"),
    Input("url", "pathname"),
)
def render_navbar_visibility(pathname):
    perms = _get_user_perms()
    is_admin = "system:admin:all" in perms
    
    can_scientific = is_admin or "Phage:read" in perms
    can_ci = is_admin or "IntelligenceEvent:read" in perms
    can_admin = is_admin or "system:user:read" in perms

    return (
        {"position": "relative", "display": "block"} if can_scientific else {"display": "none"},
        {"position": "relative", "display": "block"} if can_ci else {"display": "none"},
        {"position": "relative", "display": "block"} if can_admin else {"display": "none"},
    )

# 客户端交互回调保持原样
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
        if (!triggered || triggered.length === 0) return window.dash_clientside.no_update;
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
    Output("mega-menu-toggle-store", "data"), Input("nav-scientific-btn", "n_clicks"), Input("nav-ci-btn", "n_clicks"), Input("nav-admin-btn", "n_clicks"), prevent_initial_call=True,
)
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
                    menus.forEach(function(id) { var el = document.getElementById(id); if (el) el.classList.remove('show'); });
                }
            });
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("mega-menu-toggle-store", "id"), Input("mega-menu-toggle-store", "id"), prevent_initial_call=False,
)
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
    Output("user-menu-dropdown", "className"), Input("btn-user-menu", "n_clicks"), prevent_initial_call=True,
)
clientside_callback(
    """
    function(_) {
        if (!window.__userMenuBound) {
            window.__userMenuBound = true;
            document.addEventListener('click', function(e) {
                var wrap = document.querySelector('.user-menu-wrap');
                var dd = document.getElementById('user-menu-dropdown');
                if (!wrap || !dd) return;
                if (!wrap.contains(e.target)) dd.classList.remove('show');
            });
        }
        return window.dash_clientside.no_update;
    }
    """,
    Output("btn-user-menu", "title"), Input("btn-user-menu", "title"), prevent_initial_call=False,
)
clientside_callback(
    """
    function(_) {
        setTimeout(function() { ['mega-scientific', 'mega-ci', 'mega-admin'].forEach(function(id) { var el = document.getElementById(id); if (el) el.classList.remove('show'); }); }, 100); 
        return 1;
    }
    """,
    Output("navbar-init-hook", "data"), Input("url", "pathname"), prevent_initial_call=False,
)