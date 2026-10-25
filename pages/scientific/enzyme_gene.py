# pages/scientific/enzyme_gene.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
from datetime import datetime
from flask import session
from config import get_driver
from data_access.audit import audit

dash.register_page(__name__, path="/scientific/enzyme-gene", name="酶基因库")

ENZYME_CLASS_OPTIONS = [
    {"label": "裂解酶 (lyase)", "value": "lyase"},
    {"label": "水解酶 (hydrolase)", "value": "hydrolase"},
    {"label": "其他", "value": "other"},
]

CLASS_MAP = {"lyase": "✂️ 裂解酶", "hydrolase": "💧 水解酶", "other": "⚙️ 其他"}
STATUS_MAP = {"expressed": "✅ 已表达", "validated": "⭐ 已验证", "cloning": "⏳ 构建中"}

COLUMNS = [
    {"field": "id", "headerName": "ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "12px"}},
    {"field": "name", "headerName": "酶名称", "flex": 1, "minWidth": 180},
    {"field": "gene_symbol", "headerName": "基因符号", "width": 120, "cellStyle": {"fontFamily": "monospace"}},
    {"field": "class_cn", "headerName": "酶类型", "width": 130},
    {"field": "target_polysaccharide", "headerName": "靶向多糖", "width": 130},
    {"field": "specific_activity", "headerName": "比活性(U/mg)", "width": 130, "type": "numericColumn"},
    {"field": "status_cn", "headerName": "状态", "width": 120},
    {"field": "activity_assay_date", "headerName": "测定日期", "width": 120},
    {"field": "batch_name", "headerName": "所属批次", "width": 150},
    {"field": "created_by", "headerName": "录入人", "width": 110},
    {"field": "actions", "headerName": "操作", "width": 150, "sortable": False, "filter": False, "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "textAlign": "center", "fontWeight": "bold"}},
]

def _get_batch_options():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (b:ExperimentBatch) RETURN b.id AS id, b.name AS name ORDER BY b.created_at DESC")
            return [{"label": f"{r['name'] or r['id']}", "value": r['id']} for r in rows]
    except:
        return []

layout = html.Div([
    html.Div(id="eg-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("酶基因库", className="page-title"),
            html.Div("管理多糖水解酶基因 · 记录酶活数据", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-eg-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "录入酶基因"], id="btn-eg-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="eg-search", type="text", debounce=True, placeholder="搜索酶名称或 ID…", className="filter-search"),
        html.Div(id="eg-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="eg-grid", columnDefs=COLUMNS, rowData=[], 
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight", "localeText": {"noRowsToShow": "暂无数据"}}, 
            style={"height": None, "minHeight": "400px"}
        ),
    ]),

    # 新建 / 编辑 复用抽屉
    dcc.Store(id="store-eg-edit-id"),
    dbc.Offcanvas(
        id="eg-offcanvas", title="录入酶基因", placement="end", is_open=False, style={"width": "500px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("酶名称 *", width=4), dbc.Col(dbc.Input(id="eg-form-name", placeholder="如 alginate lyase AlgL"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("基因符号 *", width=4), dbc.Col(dbc.Input(id="eg-form-symbol", placeholder="如 algL"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("酶类型 *", width=4), dbc.Col(dbc.Select(id="eg-form-class", options=ENZYME_CLASS_OPTIONS, value="lyase"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("靶向多糖 *", width=4), dbc.Col(dbc.Input(id="eg-form-target", placeholder="如 alginate / cellulose"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("来源物种", width=4), dbc.Col(dbc.Input(id="eg-form-source"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("表达载体", width=4), dbc.Col(dbc.Input(id="eg-form-vector"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("纯化方法", width=4), dbc.Col(dbc.Input(id="eg-form-purification"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("比活性(U/mg)", width=4), dbc.Col(dbc.Input(id="eg-form-activity", type="number", step="0.01"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("测定日期", width=4), dbc.Col(dbc.Input(id="eg-form-date", type="date"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("所属批次 *", width=4), dbc.Col(dcc.Dropdown(id="eg-form-batch", options=[], placeholder="选择批次"), width=8)], className="mb-4"),
            # 抽屉底部的操作按钮区
            html.Div([
                html.Button("取消", id="btn-eg-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存修改"], id="btn-eg-save", className="btn-primary-custom"),
                html.Button([html.I(className="bi bi-trash me-1"), "删除"], id="btn-eg-delete", className="btn-danger-custom ms-2", style={"display": "none"}),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="eg-form-feedback", className="mt-3"),
        ])]),

    # 删除确认弹窗
    dcc.Store(id="store-eg-delete-id"),
    dbc.Modal(
        id="modal-eg-delete", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody("确定要删除这条酶基因记录吗？此操作不可撤销。"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-eg-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-eg-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    )
])

# 处理打开抽屉逻辑：支持新建和编辑
@callback(
    Output("eg-offcanvas", "is_open"),
    Output("eg-offcanvas", "title"),
    Output("eg-form-batch", "options"),
    Output("eg-form-date", "value"),
    Output("store-eg-edit-id", "data"),
    Output("btn-eg-delete", "style"),
    # 表单字段回填
    Output("eg-form-name", "value"),
    Output("eg-form-symbol", "value"),
    Output("eg-form-class", "value"),
    Output("eg-form-target", "value"),
    Output("eg-form-source", "value"),
    Output("eg-form-vector", "value"),
    Output("eg-form-purification", "value"),
    Output("eg-form-activity", "value"),
    Output("eg-form-batch", "value"),
    Input("btn-eg-new", "n_clicks"),
    Input("btn-eg-cancel", "n_clicks"),
    Input("eg-grid", "cellClicked"),
    State("eg-grid", "rowData"),
    prevent_initial_call=True,
)
def toggle_eg_offcanvas(new_n, cancel_n, cell, data):
    trigger = ctx.triggered_id
    if trigger == "btn-eg-cancel":
        return False, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

    latest_batches = _get_batch_options()

    if trigger == "btn-eg-new":
        today_str = datetime.now().strftime("%Y-%m-%d")
        return (True, "录入酶基因", latest_batches, today_str, None, {"display": "none"},
                "", "", "lyase", "", "", "", "", None, None)

    if trigger == "eg-grid" and cell and cell.get("colId") == "actions":
        rowIndex = cell.get("rowIndex")
        if rowIndex is not None and data and rowIndex < len(data):
            row = data[rowIndex]
            
            # ★ 修复：防止 Neo4j 返回日期对象导致前端组件崩溃，强制转为字符串
            raw_date = row.get("activity_assay_date")
            date_str = str(raw_date)[:10] if raw_date else ""
            
            return (True, "编辑酶基因", latest_batches, date_str, row["id"], {"display": "inline-block"},
                    row.get("name", ""), row.get("gene_symbol", ""), row.get("enzyme_class", "lyase"),
                    row.get("target_polysaccharide", ""), row.get("source_organism", ""),
                    row.get("expression_vector", ""), row.get("purification_method", ""),
                    row.get("specific_activity"), row.get("batch_id"))

    return False, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

@callback(
    Output("eg-grid", "rowData"),
    Output("eg-count-label", "children"),
    Input("btn-eg-refresh", "n_clicks"),
    Input("eg-search", "value"),
    Input("btn-eg-save", "n_clicks"),
    Input("btn-eg-del-confirm", "n_clicks"),
)
def load_enzymes(_, search, __, ___):
    try:
        with get_driver().session() as s:
            q = """
            MATCH (e:EnzymeGene)
            WHERE ($kw = '' OR toLower(e.name) CONTAINS toLower($kw) OR toLower(e.id) CONTAINS toLower($kw))
            OPTIONAL MATCH (e)-[:BELONGS_TO_BATCH]->(b:ExperimentBatch)
            RETURN e.id AS id, e.name AS name, e.gene_symbol AS gene_symbol,
                   e.enzyme_class AS enzyme_class, e.target_polysaccharide AS target_polysaccharide,
                   e.specific_activity AS specific_activity, e.status AS status,
                   e.activity_assay_date AS activity_assay_date, e.created_by AS created_by,
                   e.source_organism AS source_organism, e.expression_vector AS expression_vector,
                   e.purification_method AS purification_method,
                   b.name AS batch_name, b.id AS batch_id
            ORDER BY e.created_at DESC LIMIT 100
            """
            rows = [dict(r) for r in s.run(q, kw=search or "")]
            
            for r in rows:
                ecls = str(r.get("enzyme_class") or "").strip()
                st = str(r.get("status") or "").strip()
                r["class_cn"] = CLASS_MAP.get(ecls, ecls)
                r["status_cn"] = STATUS_MAP.get(st, st)
                r["actions"] = "⚙️ 编辑 / 删除"
                
            return rows, f"共 {len(rows)} 条"
    except Exception as e:
        return [], "加载失败"

@callback(
    Output("eg-form-feedback", "children"),
    Output("eg-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-eg-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-eg-save", "n_clicks"),
    State("store-eg-edit-id", "data"),
    State("eg-form-name", "value"),
    State("eg-form-symbol", "value"),
    State("eg-form-class", "value"),
    State("eg-form-target", "value"),
    State("eg-form-source", "value"),
    State("eg-form-vector", "value"),
    State("eg-form-purification", "value"),
    State("eg-form-activity", "value"),
    State("eg-form-date", "value"),
    State("eg-form-batch", "value"),
    prevent_initial_call=True,
)
def save_enzyme(_, edit_id, name, symbol, eclass, target, source, vector, purification, activity, date, batch_id):
    if not name or not symbol or not batch_id:
        return dbc.Alert("酶名称、基因符号和批次为必填项", color="danger"), no_update, no_update
    try:
        user = session.get("user", {})
        creator = user.get("name", "未知用户")
        
        with get_driver().session() as s:
            if edit_id:
                # 更新
                s.run("""
                    MATCH (e:EnzymeGene {id: $id})
                    SET e.name = $name, e.gene_symbol = $symbol, e.enzyme_class = $eclass,
                        e.target_polysaccharide = $target, e.source_organism = $source,
                        e.expression_vector = $vector, e.purification_method = $purification,
                        e.specific_activity = $activity, e.activity_assay_date = $date,
                        e.updated_at = datetime()
                    WITH e
                    OPTIONAL MATCH (e)-[r:BELONGS_TO_BATCH]->()
                    DELETE r
                    WITH e
                    MATCH (b:ExperimentBatch {id: $batch_id})
                    CREATE (e)-[:BELONGS_TO_BATCH {recorded_at: datetime()}]->(b)
                """, id=edit_id, name=name, symbol=symbol, eclass=eclass, target=target,
                     source=source, vector=vector, purification=purification,
                     activity=float(activity) if activity else None, date=date, batch_id=batch_id)
                audit("UPDATE", "EnzymeGene", edit_id, reason=f"更新酶基因: {name}")
                msg = f"已成功更新酶基因 {edit_id}"
            else:
                # 新建
                eg_id = f"EG-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:3].upper()}"
                s.run("""
                    CREATE (e:EnzymeGene {
                        id: $id, name: $name, gene_symbol: $symbol, enzyme_class: $eclass,
                        target_polysaccharide: $target, source_organism: $source,
                        expression_vector: $vector, purification_method: $purification,
                        specific_activity: $activity, activity_assay_date: $date,
                        status: 'expressed', sequence_verified: false,
                        created_at: datetime(), created_by: $creator
                    })
                    WITH e
                    MATCH (b:ExperimentBatch {id: $batch_id})
                    CREATE (e)-[:BELONGS_TO_BATCH {recorded_at: datetime()}]->(b)
                """, id=eg_id, name=name, symbol=symbol, eclass=eclass, target=target,
                     source=source, vector=vector, purification=purification,
                     activity=float(activity) if activity else None, date=date, batch_id=batch_id, creator=creator)
                audit("CREATE", "EnzymeGene", eg_id, reason=f"录入酶基因: {name}")
                msg = f"已成功录入酶基因 {eg_id}"

        return dbc.Alert(msg, color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update

# 删除逻辑：点击删除按钮 -> 弹出确认框
@callback(
    Output("modal-eg-delete", "is_open"),
    Output("store-eg-delete-id", "data"),
    Input("btn-eg-delete", "n_clicks"),
    State("store-eg-edit-id", "data"),
    prevent_initial_call=True,
)
def trigger_delete(n, edit_id):
    if not n or not edit_id:
        return no_update, no_update
    return True, edit_id

# 确认删除 -> 执行删除并关闭所有
@callback(
    Output("modal-eg-delete", "is_open", allow_duplicate=True),
    Output("eg-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-eg-refresh", "n_clicks", allow_duplicate=True),
    Output("eg-form-feedback", "children", allow_duplicate=True),
    Input("btn-eg-del-confirm", "n_clicks"),
    Input("btn-eg-del-cancel", "n_clicks"),
    State("store-eg-delete-id", "data"),
    prevent_initial_call=True,
)
def confirm_delete(confirm_n, cancel_n, delete_id):
    trigger = ctx.triggered_id
    if trigger == "btn-eg-del-cancel" or not delete_id:
        return False, no_update, no_update, no_update

    try:
        with get_driver().session() as s:
            s.run("MATCH (e:EnzymeGene {id: $id}) DETACH DELETE e", id=delete_id)
        
        # ★ 修复：将 "DELETE" 改为后端允许的 "UPDATE"（或 "LINK_DELETE" / "MIGRATION"）
        audit("UPDATE", "EnzymeGene", delete_id, reason=f"删除酶基因记录: {delete_id}")
        msg = dbc.Alert(f"记录 {delete_id} 已成功删除", color="success", dismissable=True)
        
        # 关闭弹窗、关闭抽屉、刷新列表
        return False, False, 1, msg
    except Exception as e:
        return False, no_update, no_update, dbc.Alert(f"删除失败: {e}", color="danger")