# pages/admin/user_manage.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx, ALL
import dash_bootstrap_components as dbc
from werkzeug.security import generate_password_hash
from config import get_driver
from src.shared.audit_service import write_audit_event
from flask import session

dash.register_page(__name__, path="/admin/user-manage", name="用户管理")

layout = html.Div([
    html.Div(id="um-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("用户管理", className="page-title"),
            html.Div("管理系统登录账户、分配角色", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-um-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增用户"], id="btn-um-new", className="btn-primary-custom"),
        ]),
    ]),

    html.Div(className="surface-card", style={"padding": "20px"}, children=[
        html.Div(id="um-table-container", style={"overflowX": "auto"}),
        html.Div(id="um-pagination-container", style={"display": "flex", "justifyContent": "flex-end", "marginTop": "16px"})
    ]),

    dcc.Store(id="store-um-all-users", data=[]),
    dcc.Store(id="store-um-current-page", data=1),
    
    dcc.Store(id="store-um-edit-mode"), 
    dcc.Store(id="store-um-active-username"),
    dbc.Offcanvas(
        id="um-offcanvas", title="用户信息", placement="end", is_open=False, style={"width": "450px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("用户名 *", width=3), dbc.Col(dbc.Input(id="um-form-username"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("姓名 *", width=3), dbc.Col(dbc.Input(id="um-form-name"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("分配角色 *", width=3), dbc.Col(dcc.Dropdown(id="um-form-role"), width=9)], className="mb-3"),
            dbc.Row([
                dbc.Label("密码", width=3), 
                dbc.Col(dbc.Input(id="um-form-pwd", type="password", placeholder="新增必填，编辑留空则不修改"), width=9)
            ], className="mb-4"),
            
            html.Div([
                html.Button("取消", id="btn-um-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-um-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="um-form-feedback", className="mt-3"),
        ])]
    ),

    dcc.Store(id="store-um-delete-target"),
    dbc.Modal(
        id="modal-um-delete", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody(id="um-delete-msg", children="确定要删除该用户吗？此操作不可撤销。"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-um-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-um-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    )
])

def _get_roles():
    with get_driver().session() as s:
        return [{"label": r["name"], "value": r["role_key"]} for r in s.run("MATCH (r:Role) RETURN r.role_key AS role_key, r.name AS name ORDER BY r.role_key")]

@callback(
    Output("store-um-all-users", "data"),
    Output("um-error-banner", "children"),
    Input("btn-um-refresh", "n_clicks"),
    Input("interval-global", "n_intervals"),
    Input("btn-um-save", "n_clicks"),
    Input("btn-um-del-confirm", "n_clicks"),
)
def cb_load_users(_, __, ___, ____):
    try:
        with get_driver().session() as s:
            q = """
            MATCH (u:User)
            OPTIONAL MATCH (u)-[:HAS_ROLE]->(r:Role)
            RETURN u.username AS username, u.name AS name, u.status AS status,
                   coalesce(r.name, '未分配') AS role_name
            ORDER BY u.username
            """
            rows = [dict(r) for r in s.run(q)]
            return rows, None
    except Exception as e:
        return [], dbc.Alert(f"加载失败: {e}", color="danger")

@callback(
    Output("um-table-container", "children"),
    Input("store-um-all-users", "data"),
    Input("store-um-current-page", "data"),
)
def cb_render_table(all_users, current_page):
    if not all_users:
        return html.Div("暂无数据", style={"textAlign": "center", "padding": "30px", "color": "var(--c-text-muted)"})

    page_size = 10
    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    page_users = all_users[start_idx:end_idx]

    table_rows = []
    for r in page_users:
        is_active = r.get("status") == "active"
        
        if r["username"] == "admin":
            status_ui = html.Button("正常", disabled=True, style={
                "backgroundColor": "#22C55E", "color": "white", "border": "none", 
                "borderRadius": "20px", "padding": "2px 10px", "fontSize": "12px", 
                "fontWeight": "600", "opacity": 0.6, "cursor": "not-allowed"
            })
        else:
            status_ui = html.Button(
                "正常" if is_active else "停用",
                id={"type": "btn-toggle-status", "index": r["username"]},
                n_clicks=0,
                style={
                    "backgroundColor": "#22C55E" if is_active else "#EF4444", 
                    "color": "white", "border": "none", "borderRadius": "20px", 
                    "padding": "2px 10px", "fontSize": "12px", "cursor": "pointer", "fontWeight": "600"
                }
            )
        
        if r["username"] == "admin":
            actions = html.Td(html.Span("👑 超级管理员", style={"color": "#D97706", "fontWeight": "600"}), style={"textAlign": "center"})
        else:
            actions = html.Td([
                html.Button([html.I(className="bi bi-pencil-square me-1"), "编辑"], 
                            id={"type": "btn-edit-user", "index": r["username"]}, 
                            className="btn btn-sm btn-link text-decoration-none fw-bold p-0 me-3", style={"color": "var(--c-primary)"}),
                html.Button([html.I(className="bi bi-person-badge me-1"), "分配"], 
                            id={"type": "btn-assign-user", "index": r["username"]}, 
                            className="btn btn-sm btn-link text-decoration-none fw-bold p-0 me-3", style={"color": "var(--c-secondary)"}),
                html.Button([html.I(className="bi bi-trash me-1"), "删除"], 
                            id={"type": "btn-delete-user", "index": r["username"]}, 
                            className="btn btn-sm btn-link text-decoration-none fw-bold p-0", style={"color": "var(--c-danger)"}),
            ], style={"textAlign": "center", "whiteSpace": "nowrap"})

        table_rows.append(html.Tr([
            html.Td(r["username"], style={"fontFamily": "monospace", "fontWeight": "bold"}),
            html.Td(r["name"]),
            html.Td(r["role_name"], style={"color": "var(--c-primary)"}),
            html.Td(status_ui),
            actions
        ]))

    return dbc.Table([
        html.Thead(html.Tr([
            html.Th("用户名"), html.Th("姓名"), html.Th("所属角色"), html.Th("状态"), 
            html.Th("操作", style={"textAlign": "center"})
        ]), style={"borderBottom": "2px solid var(--c-border)"}),
        html.Tbody(table_rows)
    ], hover=True, responsive=True, style={"fontSize": "14px", "verticalAlign": "middle", "marginBottom": "0"})

@callback(
    Output("um-pagination-container", "children"),
    Input("store-um-all-users", "data"),
    Input("store-um-current-page", "data"),
)
def cb_render_pagination(all_users, current_page):
    total = len(all_users)
    page_size = 10
    max_page = max(1, (total + page_size - 1) // page_size)

    return dbc.Pagination(
        id="um-pagination", max_value=max_page, active_page=current_page,
        fully_expanded=False, first_last=True, previous_next=True, style={"marginBottom": "0"}
    )

@callback(
    Output("store-um-current-page", "data"),
    Input("um-pagination", "active_page"),
    prevent_initial_call=True
)
def cb_update_page(page):
    return page if page else 1

@callback(
    Output("btn-um-refresh", "n_clicks", allow_duplicate=True),
    Input({"type": "btn-toggle-status", "index": ALL}, "n_clicks"),
    State("btn-um-refresh", "n_clicks"),
    prevent_initial_call=True,
)
def cb_toggle_user_status(clicks, current_clicks):
    trigger = ctx.triggered_id
    if not trigger or not any(clicks): return no_update

    username = trigger["index"]
    if username == "admin": return no_update
    
    try:
        with get_driver().session() as s:
            res = s.run("MATCH (u:User {username: $u}) RETURN u.status AS status", u=username).single()
            if not res: return no_update
            
            current_status = res["status"]
            new_status = "disabled" if current_status == "active" else "active"
            
            s.run("MATCH (u:User {username: $u}) SET u.status = $s", u=username, s=new_status)
            
        write_audit_event(
            get_driver(), "STATUS_CHANGE", "User", username, 
            session.get("user", {}).get("username", "admin"), 
            delta={"status": {"before": current_status, "after": new_status}}, 
            reason=f"点击切换用户状态为 {new_status}"
        )
        return (current_clicks or 0) + 1
    except Exception as e:
        print(f"Toggle status error: {e}")
        return no_update

@callback(
    Output("um-offcanvas", "is_open"),
    Output("um-offcanvas", "title"),
    Output("um-form-role", "options"),
    Output("store-um-edit-mode", "data"),
    Output("store-um-active-username", "data"),
    Output("um-form-username", "value"),
    Output("um-form-name", "value"),
    Output("um-form-role", "value"),
    Output("um-form-pwd", "value"),
    Output("um-form-username", "disabled"),
    Input({"type": "btn-edit-user", "index": ALL}, "n_clicks"),
    Input({"type": "btn-assign-user", "index": ALL}, "n_clicks"),
    Input("btn-um-new", "n_clicks"),
    prevent_initial_call=True,
)
def cb_handle_edit_assign(edit_clicks, assign_clicks, new_n):
    trigger = ctx.triggered_id
    if not trigger: return [no_update] * 10

    if trigger == "btn-um-new":
        return True, "新增用户", _get_roles(), False, None, "", "", None, "", False

    if isinstance(trigger, dict) and trigger["type"] in ["btn-edit-user", "btn-assign-user"]:
        triggered_vals = edit_clicks if trigger["type"] == "btn-edit-user" else assign_clicks
        if not any(triggered_vals): return [no_update] * 10

        username = trigger["index"]
        with get_driver().session() as s:
            res = s.run("MATCH (u:User {username: $u}) RETURN u.name AS name", u=username).single()
            role_res = s.run("MATCH (u:User {username: $u})-[:HAS_ROLE]->(r:Role) RETURN r.role_key AS rk", u=username).single()
        
        name = res["name"] if res else ""
        current_role = role_res["rk"] if role_res else None
        title = "编辑用户" if trigger["type"] == "btn-edit-user" else "分配角色"

        return True, title, _get_roles(), True, username, username, name, current_role, "", True

    return [no_update] * 10

@callback(
    Output("modal-um-delete", "is_open"),
    Output("store-um-delete-target", "data"),
    Output("um-delete-msg", "children"),
    Input({"type": "btn-delete-user", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cb_handle_delete(delete_clicks):
    trigger = ctx.triggered_id
    if not trigger or not any(delete_clicks): return no_update, no_update, no_update
    
    username = trigger["index"]
    return True, username, f"确定要删除用户 [{username}] 吗？此操作不可撤销，且会解除其所有角色绑定。"

@callback(
    Output("um-offcanvas", "is_open", allow_duplicate=True),
    Output("modal-um-delete", "is_open", allow_duplicate=True),
    Input("btn-um-cancel", "n_clicks"),
    Input("btn-um-del-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_cancel(cancel_n, del_cancel_n):
    return False, False

@callback(
    Output("um-form-feedback", "children"),
    Output("btn-um-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-um-save", "n_clicks"),
    State("store-um-edit-mode", "data"),
    State("um-form-username", "value"),
    State("um-form-name", "value"),
    State("um-form-role", "value"),
    State("um-form-pwd", "value"),
    State("btn-um-refresh", "n_clicks"),
    prevent_initial_call=True,
)
def cb_save_user(_, is_edit, username, name, role_key, pwd, current_clicks):
    if not username or not name or not role_key:
        return dbc.Alert("用户名、姓名、角色为必填项", color="danger"), no_update
    if not is_edit and not pwd:
        return dbc.Alert("新增用户必须填写初始密码", color="danger"), no_update

    try:
        with get_driver().session() as s:
            if not is_edit:
                if s.run("MATCH (u:User {username: $u}) RETURN 1", u=username).single():
                    return dbc.Alert(f"用户名 {username} 已存在", color="warning"), no_update
                s.run("CREATE (u:User {username: $u, name: $n, password_hash: $p, status: 'active', role: $r})", u=username, n=name, p=generate_password_hash(pwd), r=role_key)
            else:
                s.run("MATCH (u:User {username: $u}) SET u.name = $n", u=username, n=name)
                if pwd:
                    s.run("MATCH (u:User {username: $u}) SET u.password_hash = $p", u=username, p=generate_password_hash(pwd))
            
            s.run("MATCH (u:User {username: $u})-[rel:HAS_ROLE]->() DELETE rel", u=username)
            s.run("MATCH (u:User {username: $u}) MATCH (r:Role {role_key: $rk}) MERGE (u)-[:HAS_ROLE]->(r) SET u.role = $rk", u=username, rk=role_key)
            
        write_audit_event(get_driver(), "UPDATE" if is_edit else "CREATE", "User", username, session.get("user", {}).get("username", "admin"), reason=f"{'修改' if is_edit else '创建'}用户 {username}")
        return dbc.Alert("保存成功", color="success", duration=3000), (current_clicks or 0) + 1
    except Exception as e:
        return dbc.Alert(f"保存失败: {e}", color="danger"), no_update

@callback(
    Output("modal-um-delete", "is_open", allow_duplicate=True),
    Output("btn-um-refresh", "n_clicks", allow_duplicate=True),
    Output("um-error-banner", "children", allow_duplicate=True),
    Input("btn-um-del-confirm", "n_clicks"),
    State("store-um-delete-target", "data"),
    State("btn-um-refresh", "n_clicks"),
    prevent_initial_call=True,
)
def cb_confirm_delete(confirm_n, username, current_clicks):
    if not username: return no_update, no_update, no_update

    try:
        # ★ 核心修复：先写审计，再物理删除（如果审计失败则直接抛出异常阻断后续操作）
        write_audit_event(get_driver(), "DELETE", "User", username, session.get("user", {}).get("username", "admin"), reason=f"删除了用户 {username}")
        
        with get_driver().session() as s:
            s.run("MATCH (u:User {username: $u}) DETACH DELETE u", u=username)
            
        return False, (current_clicks or 0) + 1, dbc.Alert(f"用户 {username} 已删除", color="success", dismissable=True)
    except Exception as e:
        return False, no_update, dbc.Alert(f"删除失败: {e}", color="danger", dismissable=True)