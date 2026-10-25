# pages/scientific/phage_library.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
from datetime import datetime
from flask import session
from config import get_driver
from data_access.queries import list_phages
from data_access.audit import audit

dash.register_page(__name__, path="/scientific/phage-library", name="噬菌体库")

FAMILY_OPTIONS = [
    {"label": "Myoviridae",     "value": "Myoviridae"},
    {"label": "Siphoviridae",   "value": "Siphoviridae"},
    {"label": "Podoviridae",    "value": "Podoviridae"},
    {"label": "Microviridae",   "value": "Microviridae"},
    {"label": "Inoviridae",     "value": "Inoviridae"},
    {"label": "其他",           "value": "other"},
]

# ★ v0.7 新增：工程化状态枚举
ENGINEERING_STATUS_OPTIONS = [
    {"label": "💡 概念设计 (designed)", "value": "designed"},
    {"label": "🛠️ 已构建 (constructed)", "value": "constructed"},
    {"label": "🧪 PCR 验证 (pcr_verified)", "value": "pcr_verified"},
    {"label": "🧬 Sanger 验证 (sanger_verified)", "value": "sanger_verified"},
    {"label": "✅ 功能验证 (functionally_validated)", "value": "functionally_validated"},
]
ENG_STATUS_MAP = {opt["value"]: opt["label"] for opt in ENGINEERING_STATUS_OPTIONS}

# ★ 扩展后的表格列
COLUMNS = [
    {"field": "id", "headerName": "噬菌体 ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "name", "headerName": "名称", "flex": 1, "minWidth": 150},
    {"field": "is_engineered_cn", "headerName": "类型", "width": 110},
    {"field": "family", "headerName": "科", "width": 130},
    {"field": "receptor_target", "headerName": "受体靶点", "width": 130},
    {"field": "eng_status_cn", "headerName": "改造状态", "width": 160},
    {"field": "parent_phage_id", "headerName": "亲本噬菌体", "width": 150, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "inserted_gene_id", "headerName": "携带酶基因", "width": 150, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "actions", "headerName": "操作", "width": 100, "sortable": False, "filter": False, "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]

# 获取下拉选项
def _get_wt_phages():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (p:Phage) WHERE p.is_engineered IS NULL OR p.is_engineered = false RETURN p.phage_id AS id, p.name AS name ORDER BY p.name LIMIT 100")
            return [{"label": f"{r['name']} ({r['id']})", "value": r['id']} for r in rows]
    except: return []

def _get_enzymes():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (e:EnzymeGene) RETURN e.id AS id, e.name AS name ORDER BY e.name LIMIT 100")
            return [{"label": f"{r['name']} ({r['id']})", "value": r['id']} for r in rows]
    except: return []

layout = html.Div([
    html.Div(id="ph-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("噬菌体库", className="page-title"),
            html.Div("管理天然与工程化噬菌体 · 记录工程化血缘", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-ph-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "录入噬菌体"], id="btn-ph-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ph-search", type="text", debounce=True, value="", placeholder="搜索噬菌体名称或 ID…", className="filter-search"),
        dcc.Dropdown(id="ph-family-filter", options=[{"label": "全部科", "value": ""}] + FAMILY_OPTIONS, value="", clearable=False, style={"width": "180px"}),
        html.Div(id="ph-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="ph-grid", columnDefs=COLUMNS, rowData=[], 
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight", "localeText": {"noRowsToShow": "暂无数据"}}, 
            style={"height": None, "minHeight": "420px"}
        ),
    ]),

    # 录入表单
    dbc.Offcanvas(
        id="ph-offcanvas", title="录入噬菌体", placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("名称 *", width=3), dbc.Col(dbc.Input(id="ph-form-name", placeholder="如 PKP014"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("科", width=3), dbc.Col(dbc.Select(id="ph-form-family", options=FAMILY_OPTIONS, value="Myoviridae"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("受体靶点", width=3), dbc.Col(dbc.Input(id="ph-form-receptor", placeholder="如 LPS / OmpA"), width=9)], className="mb-3"),
            
            # ★ v0.7 新增：工程化配置区
            html.Hr(style={"margin": "10px 0 20px 0"}),
            dbc.Row([dbc.Label("是否工程化", width=3), dbc.Col(dbc.Select(id="ph-form-is-eng", options=[{"label": "🧬 是", "value": "true"}, {"label": "🦠 否 (野生型)", "value": "false"}], value="false"), width=9)], className="mb-3"),
            
            dbc.Row(id="ph-form-eng-fields", style={"display": "none"}, children=[
                dbc.Col(width=12, children=[
                    dbc.Row([dbc.Label("改造状态", width=3), dbc.Col(dbc.Select(id="ph-form-eng-status", options=ENGINEERING_STATUS_OPTIONS, value="designed"), width=9)], className="mb-3"),
                    dbc.Row([dbc.Label("亲本噬菌体", width=3), dbc.Col(dcc.Dropdown(id="ph-form-parent", options=[], placeholder="选择野生型亲本"), width=9)], className="mb-3"),
                    dbc.Row([dbc.Label("携带酶基因", width=3), dbc.Col(dcc.Dropdown(id="ph-form-enzyme", options=[], placeholder="选择插入的酶基因"), width=9)], className="mb-4"),
                ])
            ]),

            html.Div([
                html.Button("取消", id="btn-ph-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-ph-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ph-form-feedback", className="mt-3"),
        ])]),

    # ★ v0.7 新增：详情与血缘抽屉
    dbc.Offcanvas(
        id="ph-detail-drawer", title="噬菌体详情与血缘", placement="end", is_open=False, style={"width": "550px"},
        children=[
            html.Div(id="ph-detail-content")
        ]
    )
])

# 列表加载
@callback(
    Output("ph-grid", "rowData"),
    Output("ph-count-label", "children"),
    Output("ph-error-banner", "children"),  # ★ 修复：补上这个 Output
    Input("btn-ph-refresh", "n_clicks"),
    Input("ph-search", "value"),
    Input("ph-family-filter", "value"),
    Input("btn-ph-save", "n_clicks"),
)
def cb_load(_, search, family, __):
    try:
        with get_driver().session() as s:
            # 查询基础信息 + 关联的酶基因
            q = """
            MATCH (p:Phage)
            WHERE ($kw = '' OR toLower(p.name) CONTAINS toLower($kw) OR toLower(p.phage_id) CONTAINS toLower($kw))
              AND ($fam = '' OR p.family = $fam)
            OPTIONAL MATCH (p)-[:DISPLAYS]->(e:EnzymeGene)
            RETURN p.phage_id AS id, p.name AS name, p.family AS family, p.receptor_target AS receptor_target,
                   p.is_engineered AS is_engineered, p.engineering_status AS eng_status,
                   p.parent_phage_id AS parent_phage_id, e.id AS inserted_gene_id
            ORDER BY p.created_at DESC LIMIT 200
            """
            rows = [dict(r) for r in s.run(q, kw=search or "", fam=family or "")]
            
            for r in rows:
                r["is_engineered_cn"] = "🧬 工程化" if r.get("is_engineered") else "🦠 野生型"
                r["eng_status_cn"] = ENG_STATUS_MAP.get(r.get("eng_status"), "")
                r["actions"] = "🔍 详情"
                
            return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"查询失败：{e}", color="danger")

# 打开抽屉 / 加载下拉选项
@callback(
    Output("ph-offcanvas", "is_open"),
    Output("ph-form-parent", "options"),
    Output("ph-form-enzyme", "options"),
    Input("btn-ph-new", "n_clicks"),
    Input("btn-ph-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    if ctx.triggered_id == "btn-ph-new":
        return True, _get_wt_phages(), _get_enzymes()
    return False, no_update, no_update

# 控制表单工程化字段的显隐
@callback(
    Output("ph-form-eng-fields", "style"),
    Input("ph-form-is-eng", "value"),
)
def toggle_eng_fields(is_eng):
    return {"display": "block"} if is_eng == "true" else {"display": "none"}

# 保存
@callback(
    Output("ph-form-feedback", "children"),
    Output("ph-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ph-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ph-save", "n_clicks"),
    State("ph-form-name", "value"),
    State("ph-form-family", "value"),
    State("ph-form-receptor", "value"),
    State("ph-form-is-eng", "value"),
    State("ph-form-eng-status", "value"),
    State("ph-form-parent", "value"),
    State("ph-form-enzyme", "value"),
    prevent_initial_call=True,
)
def cb_save(_, name, family, receptor, is_eng, eng_status, parent_id, enzyme_id):
    if not name or not name.strip():
        return dbc.Alert("名称不能为空", color="danger"), no_update, no_update
    try:
        user = session.get("user", {})
        creator = user.get("name", "未知用户")
        
        phage_id = f"PHAGE-{name.strip()}"
        is_eng_bool = (is_eng == "true")
        
        with get_driver().session() as s:
            # 1. 创建/更新噬菌体节点
            s.run("""
                MERGE (p:Phage {phage_id: $pid})
                SET p.name = $name, p.family = $family, p.receptor_target = $rec,
                    p.is_engineered = $is_eng, p.engineering_status = $eng_status,
                    p.parent_phage_id = $parent_id, p.created_by = $creator,
                    p.created_at = COALESCE(p.created_at, datetime()), p.updated_at = datetime()
            """, pid=phage_id, name=name.strip(), family=family or "", rec=receptor or "",
                 is_eng=is_eng_bool, eng_status=eng_status if is_eng_bool else None,
                 parent_id=parent_id if is_eng_bool else None, creator=creator)
            
            # 2. 如果工程化，处理血缘关系
            if is_eng_bool:
                # 清除旧关系
                s.run("MATCH (p:Phage {phage_id: $pid})-[r:ENGINEERED_FROM|DISPLAYS]->() DELETE r", pid=phage_id)
                
                # 建立 ENGINEERED_FROM 亲本关系
                if parent_id:
                    s.run("""
                        MATCH (p:Phage {phage_id: $pid})
                        MATCH (parent:Phage {phage_id: $parent_id})
                        CREATE (p)-[:ENGINEERED_FROM {method: 'homologous_recombination', edit_date: date()}]->(parent)
                    """, pid=phage_id, parent_id=parent_id)
                
                # 建立 DISPLAYS 酶基因关系
                if enzyme_id:
                    s.run("""
                        MATCH (p:Phage {phage_id: $pid})
                        MATCH (e:EnzymeGene {id: $enzyme_id})
                        CREATE (p)-[:DISPLAYS {display_location: 'genomic_insertion'}]->(e)
                    """, pid=phage_id, enzyme_id=enzyme_id)

        audit("CREATE", "Phage", phage_id, reason=f"录入噬菌体 {name}")
        return dbc.Alert(f"已成功保存 {phage_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update

# ★ v0.7 详情与血缘展示
@callback(
    Output("ph-detail-drawer", "is_open"),
    Output("ph-detail-content", "children"),
    Input("ph-grid", "cellClicked"),
    State("ph-grid", "rowData"),
    prevent_initial_call=True,
)
def show_detail(cell, data):
    if not cell or not data or cell.get("colId") != "actions":
        return no_update, no_update
        
    row = data[cell["rowIndex"]]
    phage_id = row["id"]
    
    try:
        with get_driver().session() as s:
            # 查询详情和关联
            res = s.run("""
                MATCH (p:Phage {phage_id: $pid})
                OPTIONAL MATCH (p)-[r:ENGINEERED_FROM]->(parent:Phage)
                OPTIONAL MATCH (p)-[d:DISPLAYS]->(eg:EnzymeGene)
                RETURN p, parent, r, eg, d
            """, pid=phage_id).single()
            
            if not res:
                return True, dbc.Alert("未找到该噬菌体", color="warning")
                
            p = dict(res["p"])
            parent = dict(res["parent"]) if res["parent"] else None
            rel = dict(res["r"]) if res["r"] else None
            eg = dict(res["eg"]) if res["eg"] else None
            d_rel = dict(res["d"]) if res["d"] else None

        # 构造 UI
        content = [
            html.H4(p.get("name"), style={"color": "var(--c-primary)", "marginBottom": "4px"}),
            html.Div(p.get("phage_id"), style={"fontFamily": "monospace", "fontSize": "12px", "color": "var(--c-text-muted)", "marginBottom": "20px"}),
            dbc.Row([
                dbc.Col([html.Div("科", className="text-muted small"), html.Div(p.get("family") or "—")], width=6),
                dbc.Col([html.Div("受体靶点", className="text-muted small"), html.Div(p.get("receptor_target") or "—")], width=6),
            ], className="mb-4"),
            dbc.Row([
                dbc.Col([html.Div("类型", className="text-muted small"), html.Div("🧬 工程化" if p.get("is_engineered") else "🦠 野生型", style={"fontWeight": "600"})], width=6),
                dbc.Col([html.Div("改造状态", className="text-muted small"), html.Div(ENG_STATUS_MAP.get(p.get("engineering_status"), "—"))], width=6),
            ], className="mb-4"),
        ]

        # 如果是工程化噬菌体，渲染血缘图
        if p.get("is_engineered"):
            content.append(html.Hr())
            content.append(html.H6([html.I(className="bi bi-diagram-3 me-2"), "工程化血缘"], style={"fontWeight": "600", "marginBottom": "16px"}))
            
            # 血缘卡片
            blood_line = []
            
            # 1. 亲本
            if parent:
                blood_line.append(html.Div([
                    html.Div("野生型亲本", style={"fontSize": "11px", "color": "#64748B", "marginBottom": "4px"}),
                    html.Div([
                        html.I(className="bi bi-virus me-2", style={"color": "#0D9373"}),
                        html.Span(parent.get("name"), style={"fontWeight": "600"}),
                        html.Div(parent.get("phage_id"), style={"fontFamily": "monospace", "fontSize": "10px", "color": "#94A3B8"})
                    ], style={"background": "#F0FDF4", "border": "1px solid #BBF7D0", "padding": "10px 14px", "borderRadius": "8px"})
                ], style={"marginBottom": "12px", "textAlign": "center"}))
            else:
                blood_line.append(html.Div("⚠️ 未关联亲本", style={"textAlign": "center", "color": "var(--c-warning)", "marginBottom": "12px"}))

            # 2. 改造方法
            method_text = rel.get("method", "unknown") if rel else "未知方法"
            blood_line.append(html.Div([
                html.I(className="bi bi-arrow-down", style={"fontSize": "20px", "color": "#CBD5E1"}),
                html.Div(f"改造方法: {method_text}", style={"fontSize": "11px", "color": "#64748B", "marginTop": "4px"})
            ], style={"display": "flex", "flexDirection": "column", "alignItems": "center", "marginBottom": "12px"}))

            # 3. 当前工程噬菌体
            blood_line.append(html.Div([
                html.Div("本株 (工程化)", style={"fontSize": "11px", "color": "#64748B", "marginBottom": "4px"}),
                html.Div([
                    html.I(className="bi bi-virus me-2", style={"color": "#1B6CA8"}),
                    html.Span(p.get("name"), style={"fontWeight": "600"}),
                ], style={"background": "#EFF6FF", "border": "1px solid #BFDBFE", "padding": "10px 14px", "borderRadius": "8px"})
            ], style={"marginBottom": "16px", "textAlign": "center"}))

            # 4. 携带的酶基因
            if eg:
                blood_line.append(html.Div([
                    html.Div("携带酶基因", style={"fontSize": "11px", "color": "#64748B", "marginBottom": "4px"}),
                    html.Div([
                        html.I(className="bi bi-fingerprint me-2", style={"color": "#8B5CF6"}),
                        html.Span(eg.get("name"), style={"fontWeight": "600"}),
                        html.Div(f"比活性: {eg.get('specific_activity') or '—'} U/mg", style={"fontSize": "11px", "color": "#64748B"})
                    ], style={"background": "#F5F3FF", "border": "1px solid #DDD6FE", "padding": "10px 14px", "borderRadius": "8px"})
                ], style={"marginBottom": "12px", "textAlign": "center"}))
            else:
                blood_line.append(html.Div("⚠️ 未关联酶基因", style={"textAlign": "center", "color": "var(--c-warning)"}))
            
            content.append(html.Div(blood_line, style={"padding": "16px", "background": "#F8FAFC", "borderRadius": "8px", "border": "1px dashed #CBD5E1"}))

        return True, content
    except Exception as e:
        return True, dbc.Alert(f"查询失败: {e}", color="danger")