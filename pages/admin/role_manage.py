# pages/admin/role_manage.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx, ALL
import dash_bootstrap_components as dbc
from config import get_driver
from src.shared.audit_service import write_audit_event
from flask import session

dash.register_page(__name__, path="/admin/role-manage", name="角色管理")

PERMISSION_TREE = {
    "🤖 Agent 域": {
        "任务中心": [
            ("AgentTask:create", "创建新任务"),
            ("AgentTask:read", "查看任务列表/回放"),
            ("AgentTask:approve", "批准计划/结果"),
            ("AgentTask:cancel", "强制取消任务"),
        ]
    },
    "🔬 科学域": {
        "噬菌体库": [("Phage:read", "查看列表/血缘"), ("Phage:write", "录入/编辑噬菌体")],
        "裂解实验": [("LysisAssay:read", "查看数据"), ("LysisAssay:write", "录入/编辑"), ("LysisAssay:review", "QC 审核")],
        "临床病例": [("ClinicalCase:read", "查看病例"), ("ClinicalCase:write", "录入/修改结局")],
        "证据包": [("EvidencePackage:read", "查看包"), ("EvidencePackage:create", "生成草稿"), ("EvidencePackage:review", "审核")],
    },
    "🕵️ 情报域": {
        "情报事件": [("IntelligenceEvent:read", "查看概览/事件"), ("IntelligenceEvent:create", "录入/抓取"), ("IntelligenceEvent:review", "确认事实")],
        "开发项目": [("DevelopmentProgram:read", "查看项目"), ("DevelopmentProgram:write", "新建/修改")],
        "决策记录": [("DecisionRecord:read", "查看记录"), ("DecisionRecord:write", "复盘"), ("IntelligenceProduct:review", "审核简报")],
    },
    "⚙️ 系统管理": {
        "用户管理": [("system:user:read", "查看列表"), ("system:user:write", "新增/编辑/删除"), ("system:user:status", "切换启停")],
    }
}

def _init_all_permissions():
    with get_driver().session() as s:
        for domain, pages in PERMISSION_TREE.items():
            for page, perms in pages.items():
                for k, n in perms:
                    s.run("MERGE (p:Permission {perm_key: $k}) SET p.name = $n", k=k, n=n)

_init_all_permissions()

layout = html.Div([
    html.Div(id="rm-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("角色管理", className="page-title"),
            html.Div("维护系统角色，为角色分配菜单和操作权限", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-rm-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增角色"], id="btn-rm-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="surface-card", style={"padding": "20px"}, children=[html.Div(id="rm-grid-placeholder")]),

    dbc.Offcanvas(
        id="rm-offcanvas", title="新增角色", placement="end", is_open=False, style={"width": "450px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("角色标识 *", width=3), dbc.Col(dbc.Input(id="rm-form-key", placeholder="如 observer"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("角色名称 *", width=3), dbc.Col(dbc.Input(id="rm-form-name", placeholder="如 只读观察员"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("描述", width=3), dbc.Col(dbc.Textarea(id="rm-form-desc", rows=3), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-rm-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-rm-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="rm-form-feedback", className="mt-3"),
        ])]
    ),

    dcc.Store(id="store-rm-active-role"),
    dbc.Modal(
        id="modal-rm-perms", is_open=False, size="lg", centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("分配权限")),
            dbc.ModalBody([
                html.Div(id="rm-perms-info", className="mb-3 fw-bold text-primary fs-5"),
                html.Div([
                    html.Button("✅ 全选", id="btn-rm-select-all", className="btn btn-sm btn-outline-primary me-2"),
                    html.Button("❌ 清空", id="btn-rm-deselect-all", className="btn btn-sm btn-outline-secondary"),
                ], className="mb-4"),
                dbc.Accordion(id="rm-perms-accordion", always_open=True, children=[])
            ]),
            dbc.ModalFooter([
                html.Button("取消", id="btn-rm-perms-cancel", className="btn-outline-custom me-2"),
                html.Button("保存权限配置", id="btn-rm-perms-save", className="btn-primary-custom"),
            ]),
        ]
    ),

    # ★ 删除角色确认弹窗
    dcc.Store(id="store-rm-delete-role"),
    dbc.Modal(
        id="modal-rm-delete", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody(id="rm-delete-msg"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-rm-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-rm-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    )
])

def _render_rm_table(rows):
    if not rows: return html.Div("暂无数据", style={"textAlign": "center", "padding": "30px", "color": "var(--c-text-muted)"})
    trs = []
    for r in rows:
        if r["role_key"] in ["admin", "agent"]:
            actions = html.Td("系统内置", style={"color": "var(--c-text-muted)", "textAlign": "center"})
        else:
            actions = html.Td([
                html.Button([html.I(className="bi bi-gear me-1"), "分配权限"], id={"type": "btn-rm-perms", "index": r["role_key"]}, className="btn btn-sm btn-link text-decoration-none fw-bold p-0 me-3"),
                html.Button([html.I(className="bi bi-trash me-1"), "删除"], id={"type": "btn-rm-delete", "index": r["role_key"]}, className="btn btn-sm btn-link text-danger text-decoration-none fw-bold p-0")
            ], style={"textAlign": "center"})
            
        trs.append(html.Tr([
            html.Td(r["role_key"], style={"fontFamily": "monospace"}),
            html.Td(r["name"]),
            html.Td(r["description"] or "—"),
            actions
        ]))
    return dbc.Table([
        html.Thead(html.Tr([html.Th("角色标识"), html.Th("角色名称"), html.Th("描述"), html.Th("操作", style={"textAlign": "center"})])),
        html.Tbody(trs)
    ], hover=True, style={"fontSize": "14px", "verticalAlign": "middle"})

@callback(
    Output("rm-grid-placeholder", "children"),
    Output("rm-error-banner", "children"),
    Input("btn-rm-refresh", "n_clicks"),
    Input("interval-global", "n_intervals"),
    Input("btn-rm-save", "n_clicks"),
    Input("btn-rm-perms-save", "n_clicks"),
    Input("btn-rm-del-confirm", "n_clicks"),
)
def cb_load_roles(_, __, ___, ____, _____):
    try:
        with get_driver().session() as s:
            q = "MATCH (r:Role) RETURN r.role_key AS role_key, r.name AS name, coalesce(r.description, '') AS description ORDER BY r.role_key"
            rows = [dict(r) for r in s.run(q)]
            return _render_rm_table(rows), None
    except Exception as e:
        return None, dbc.Alert(f"加载失败: {e}", color="danger")

@callback(Output("rm-offcanvas", "is_open"), Input("btn-rm-new", "n_clicks"), Input("btn-rm-cancel", "n_clicks"), prevent_initial_call=True)
def cb_toggle_rm(new_n, cancel_n): return ctx.triggered_id == "btn-rm-new"

@callback(
    Output("rm-form-feedback", "children"),
    Output("btn-rm-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-rm-save", "n_clicks"),
    State("rm-form-key", "value"), State("rm-form-name", "value"), State("rm-form-desc", "value"),
    prevent_initial_call=True,
)
def cb_save_role(_, role_key, name, desc):
    if not role_key or not name: return dbc.Alert("必填项缺失", color="danger"), no_update
    try:
        with get_driver().session() as s:
            if s.run("MATCH (r:Role {role_key: $k}) RETURN 1", k=role_key).single():
                return dbc.Alert("角色标识已存在", color="warning"), no_update
            s.run("CREATE (r:Role {role_key: $k, name: $n, description: $d})", k=role_key, n=name, d=desc)
        write_audit_event(get_driver(), "CREATE", "Role", role_key, session.get("user", {}).get("username", "admin"), reason=f"创建角色 {name}")
        return dbc.Alert("创建成功", color="success", duration=3000), 1
    except Exception as e:
        return dbc.Alert(f"保存失败: {e}", color="danger"), no_update

# ★ 删除角色逻辑
@callback(
    Output("modal-rm-delete", "is_open"),
    Output("store-rm-delete-role", "data"),
    Output("rm-delete-msg", "children"),
    Input({"type": "btn-rm-delete", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cb_trigger_rm_delete(n_clicks_list):
    trigger = ctx.triggered_id
    if not trigger or not any(n_clicks_list): return no_update, no_update, no_update
    role_key = trigger["index"]
    return True, role_key, f"确定要删除角色 [{role_key}] 吗？此操作不可撤销，该角色下的用户将失去对应权限。"

@callback(
    Output("modal-rm-delete", "is_open", allow_duplicate=True),
    Output("btn-rm-refresh", "n_clicks", allow_duplicate=True),
    Output("rm-error-banner", "children", allow_duplicate=True),
    Input("btn-rm-del-confirm", "n_clicks"),
    Input("btn-rm-del-cancel", "n_clicks"),
    State("store-rm-delete-role", "data"),
    prevent_initial_call=True,
)
def cb_confirm_rm_delete(confirm_n, cancel_n, role_key):
    if ctx.triggered_id == "btn-rm-del-cancel" or not role_key:
        return False, no_update, no_update
    try:
        with get_driver().session() as s:
            s.run("MATCH (r:Role {role_key: $k}) DETACH DELETE r", k=role_key)
        write_audit_event(get_driver(), "DELETE", "Role", role_key, session.get("user", {}).get("username", "admin"), reason=f"删除了角色 {role_key}")
        return False, 1, dbc.Alert(f"角色 {role_key} 已删除", color="success", dismissable=True)
    except Exception as e:
        return False, no_update, dbc.Alert(f"删除失败: {e}", color="danger")

# 权限分配相关回调 (保持不变)
@callback(
    Output("modal-rm-perms", "is_open"),
    Output("store-rm-active-role", "data"),
    Output("rm-perms-info", "children"),
    Output("rm-perms-accordion", "children"),
    Input({"type": "btn-rm-perms", "index": ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cb_open_perms(n_clicks_list):
    trigger = ctx.triggered_id
    if not trigger or not any(n_clicks_list): return no_update, no_update, no_update, no_update
    role_key = trigger["index"]
    
    with get_driver().session() as s:
        res = s.run("MATCH (r:Role {role_key: $r}) RETURN r.name AS name", r=role_key).single()
        role_name = res["name"] if res else role_key
        my_perms = set(r["k"] for r in s.run("MATCH (:Role {role_key: $r})-[:HAS_PERMISSION]->(p:Permission) RETURN p.perm_key AS k", r=role_key))

    accordion_items = []
    for domain_name, pages in PERMISSION_TREE.items():
        domain_perms = [p[0] for page in pages.values() for p in page]
        domain_checked = [p for p in domain_perms if p in my_perms]
        
        page_blocks = []
        for page_name, perms in pages.items():
            page_perm_keys = [p[0] for p in perms]
            page_checked = [p for p in page_perm_keys if p in my_perms]
            
            page_blocks.append(
                html.Div([
                    html.Div(page_name, style={"fontWeight": "600", "fontSize": "13px", "marginBottom": "8px", "color": "var(--c-text-secondary)"}),
                    dcc.Checklist(
                        id={"type": "perm-checklist", "index": role_key, "page": page_name},
                        options=[{"label": f" {desc} ({key})", "value": key} for key, desc in perms],
                        value=page_checked,
                        labelStyle={"display": "block", "marginBottom": "6px", "fontSize": "13px", "cursor": "pointer"},
                        inputStyle={"marginRight": "8px"}
                    )
                ], style={"marginBottom": "16px", "paddingLeft": "10px", "borderLeft": "2px solid #E2E8F0"})
            )
        accordion_items.append(dbc.AccordionItem(page_blocks, title=f"{domain_name} (已选 {len(domain_checked)}/{len(domain_perms)})"))
    return True, role_key, f"正在为角色 [{role_name}] 分配权限", accordion_items

@callback(
    Output("rm-perms-accordion", "children", allow_duplicate=True),
    Input("btn-rm-select-all", "n_clicks"), Input("btn-rm-deselect-all", "n_clicks"),
    State("store-rm-active-role", "data"), prevent_initial_call=True,
)
def cb_batch_select(select_all_n, deselect_all_n, role_key):
    if not role_key: return no_update
    is_select_all = (ctx.triggered_id == "btn-rm-select-all")
    with get_driver().session() as s:
        res = s.run("MATCH (r:Role {role_key: $r}) RETURN r.name AS name", r=role_key).single()
        role_name = res["name"] if res else role_key

    accordion_items = []
    for domain_name, pages in PERMISSION_TREE.items():
        domain_perms = [p[0] for page in pages.values() for p in page]
        page_blocks = []
        for page_name, perms in pages.items():
            page_perm_keys = [p[0] for p in perms]
            page_checked = page_perm_keys if is_select_all else []
            page_blocks.append(
                html.Div([
                    html.Div(page_name, style={"fontWeight": "600", "fontSize": "13px", "marginBottom": "8px", "color": "var(--c-text-secondary)"}),
                    dcc.Checklist(
                        id={"type": "perm-checklist", "index": role_key, "page": page_name},
                        options=[{"label": f" {desc} ({key})", "value": key} for key, desc in perms],
                        value=page_checked,
                        labelStyle={"display": "block", "marginBottom": "6px", "fontSize": "13px", "cursor": "pointer"},
                        inputStyle={"marginRight": "8px"}
                    )
                ], style={"marginBottom": "16px", "paddingLeft": "10px", "borderLeft": "2px solid #E2E8F0"})
            )
        checked_count = len(domain_perms) if is_select_all else 0
        accordion_items.append(dbc.AccordionItem(page_blocks, title=f"{domain_name} (已选 {checked_count}/{len(domain_perms)})"))
    return accordion_items

@callback(
    Output("modal-rm-perms", "is_open", allow_duplicate=True),
    Output("btn-rm-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-rm-perms-save", "n_clicks"), Input("btn-rm-perms-cancel", "n_clicks"),
    State("store-rm-active-role", "data"), State({"type": "perm-checklist", "index": ALL, "page": ALL}, "value"),
    prevent_initial_call=True,
)
def cb_save_perms(save_n, cancel_n, role_key, all_values):
    if ctx.triggered_id == "btn-rm-perms-cancel" or not role_key: return False, no_update
    selected_perms = []
    if all_values:
        for val_list in all_values:
            if val_list: selected_perms.extend(val_list)
    try:
        with get_driver().session() as s:
            s.run("MATCH (:Role {role_key: $r})-[rel:HAS_PERMISSION]->() DELETE rel", r=role_key)
            if selected_perms:
                s.run("MATCH (r:Role {role_key: $r}) UNWIND $perms AS pk MATCH (p:Permission {perm_key: pk}) MERGE (r)-[:HAS_PERMISSION]->(p)", r=role_key, perms=selected_perms)
        write_audit_event(get_driver(), "UPDATE", "Role", role_key, session.get("user", {}).get("username", "admin"), reason="更新了角色的权限分配")
        return False, 1
    except Exception as e:
        print(f"Save perms error: {e}")
        return no_update, no_update