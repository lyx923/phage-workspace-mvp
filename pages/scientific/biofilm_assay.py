# pages/scientific/biofilm_assay.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
from datetime import datetime
from flask import session
from config import get_driver
from data_access.audit import audit

dash.register_page(__name__, path="/scientific/biofilm-assay", name="生物膜实验")

CONTROL_TYPE_OPTIONS = [
    {"label": "工程化噬菌体 (engineered_phage)", "value": "engineered_phage"},
    {"label": "野生型噬菌体 (wild_type_phage)", "value": "wild_type_phage"},
    {"label": "游离酶 (free_enzyme)", "value": "free_enzyme"},
    {"label": "空白对照 (blank)", "value": "blank"},
]

CTYPE_MAP = {
    "engineered_phage": "🧬 工程化噬菌体", 
    "wild_type_phage": "🦠 野生型噬菌体", 
    "free_enzyme": "🧪 游离酶", 
    "blank": "⚪ 空白对照"
}

# ★ 新增：PRD 规定的实验状态枚举
STATUS_OPTIONS = [
    {"label": "📝 草稿 (draft)", "value": "draft"},
    {"label": "✅ 已完成 (completed)", "value": "completed"},
    {"label": "📄 已发表 (published)", "value": "published"},
]
STATUS_MAP = {opt["value"]: opt["label"] for opt in STATUS_OPTIONS}

COLUMNS = [
    {"field": "id", "headerName": "ID", "width": 150, "cellStyle": {"fontFamily": "monospace", "fontSize": "12px"}},
    {"field": "ctype_cn", "headerName": "处理类型", "flex": 1, "minWidth": 150},
    {"field": "host_strain_id", "headerName": "宿主菌", "width": 150},
    {"field": "phage_id", "headerName": "噬菌体", "width": 150},
    {"field": "biofilm_reduction_pct", "headerName": "消除率 %", "width": 110, "type": "numericColumn", "cellStyle": {"fontWeight": "bold", "color": "#0D9373"}},
    {"field": "biofilm_residual_od", "headerName": "残留 OD", "width": 100, "type": "numericColumn"},
    {"field": "moi", "headerName": "MOI", "width": 80},
    {"field": "treatment_duration_h", "headerName": "时长(h)", "width": 90},
    {"field": "status_cn", "headerName": "状态", "width": 120},
    {"field": "batch_name", "headerName": "所属批次", "width": 150},
    {"field": "created_by", "headerName": "录入人", "width": 110},
    # ★ 修复：加宽操作列到 160，并强制不换行
    {"field": "actions", "headerName": "操作", "width": 160, "sortable": False, "filter": False, 
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "textAlign": "center", "fontWeight": "bold", "whiteSpace": "nowrap"}},
]

# 健壮的数据拉取函数
def _get_phages():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (p:Phage) RETURN p.phage_id AS id, p.name AS name ORDER BY p.created_at DESC LIMIT 100")
            return [{"label": f"{r['name']} ({r['id']})", "value": r['id']} for r in rows if r.get('id')]
    except Exception as e: 
        print(f"Error loading phages: {e}")
        return []

def _get_hosts():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (h:HostStrain) RETURN h.host_strain_id AS id, h.strain_label AS label ORDER BY h.strain_label LIMIT 100")
            return [{"label": f"{r['label']} ({r['id']})", "value": r['id']} for r in rows if r.get('id')]
    except Exception as e: 
        print(f"Error loading hosts: {e}")
        return []

def _get_batches():
    try:
        with get_driver().session() as s:
            rows = s.run("MATCH (b:ExperimentBatch) RETURN b.id AS id, b.name AS name ORDER BY b.created_at DESC")
            return [{"label": f"{r['name'] or r['id']}", "value": r['id']} for r in rows if r.get('id')]
    except Exception as e: 
        print(f"Error loading batches: {e}")
        return []

layout = html.Div([
    html.Div(id="ba-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("生物膜实验", className="page-title"),
            html.Div("定量评估结晶紫染色 OD 与消除率", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-ba-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "录入实验"], id="btn-ba-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="ba-grid", columnDefs=COLUMNS, rowData=[], 
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight", "localeText": {"noRowsToShow": "暂无数据"}}, 
            style={"height": None, "minHeight": "400px"}
        ),
    ]),

    # 新建 / 编辑 复用抽屉
    dcc.Store(id="store-ba-edit-id"),
    dbc.Offcanvas(
        id="ba-offcanvas", title="录入生物膜实验", placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("处理类型 *", width=4), dbc.Col(dbc.Select(id="ba-form-ctype", options=CONTROL_TYPE_OPTIONS, value="engineered_phage"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("宿主菌", width=4), dbc.Col(dcc.Dropdown(id="ba-form-host", options=[]), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("噬菌体", width=4), dbc.Col(dcc.Dropdown(id="ba-form-phage", options=[]), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("形成 OD *", width=4), dbc.Col(dbc.Input(id="ba-form-od-form", type="number", step="0.01", value=1.2), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("残留 OD *", width=4), dbc.Col(dbc.Input(id="ba-form-od-res", type="number", step="0.01", value=0.3), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("MOI", width=4), dbc.Col(dbc.Input(id="ba-form-moi", type="number", step="0.1", value=1.0), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("处理时长(h)", width=4), dbc.Col(dbc.Input(id="ba-form-duration", type="number", value=24), width=8)], className="mb-3"),
            # ★ 新增：实验状态选择
            dbc.Row([dbc.Label("实验状态", width=4), dbc.Col(dbc.Select(id="ba-form-status", options=STATUS_OPTIONS, value="completed"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("所属批次 *", width=4), dbc.Col(dcc.Dropdown(id="ba-form-batch", options=[]), width=8)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-ba-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存修改"], id="btn-ba-save", className="btn-primary-custom"),
                html.Button([html.I(className="bi bi-trash me-1"), "删除"], id="btn-ba-delete", className="btn-danger-custom ms-2", style={"display": "none"}),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ba-form-feedback", className="mt-3"),
        ])]) ,

    # 删除确认弹窗
    dcc.Store(id="store-ba-delete-id"),
    dbc.Modal(
        id="modal-ba-delete", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody("确定要删除这条生物膜实验记录吗？此操作不可撤销。"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-ba-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-ba-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    )
])

# ============================================================
# 列表加载
# ============================================================
@callback(
    Output("ba-grid", "rowData"),
    Input("btn-ba-refresh", "n_clicks"),
    Input("btn-ba-save", "n_clicks"),
    Input("btn-ba-del-confirm", "n_clicks"),
)
def load_biofilm(_, __, ___):
    try:
        with get_driver().session() as s:
            rows = [dict(r) for r in s.run("""
                MATCH (b:BiofilmAssay)
                OPTIONAL MATCH (b)-[:BELONGS_TO_BATCH]->(batch:ExperimentBatch)
                RETURN b.id AS id, b.control_type AS control_type,
                       b.host_strain_id AS host_strain_id, b.phage_id AS phage_id,
                       b.biofilm_formation_od AS biofilm_formation_od,
                       b.biofilm_reduction_pct AS biofilm_reduction_pct,
                       b.biofilm_residual_od AS biofilm_residual_od,
                       b.moi AS moi, b.treatment_duration_h AS treatment_duration_h,
                       b.status AS status, b.created_by AS created_by,
                       batch.name AS batch_name, batch.id AS batch_id
                ORDER BY b.created_at DESC LIMIT 100
            """)]
            
            for r in rows:
                ctype = str(r.get("control_type") or "").strip()
                st = str(r.get("status") or "").strip()
                r["ctype_cn"] = CTYPE_MAP.get(ctype, ctype)
                r["status_cn"] = STATUS_MAP.get(st, st)
                r["actions"] = "⚙️ 编辑 / 删除"
                
            return rows
    except Exception as e: 
        print(f"Error loading biofilm: {e}")
        return []

# ============================================================
# 回调拆分：打开抽屉、加载下拉选项
# ============================================================
@callback(
    Output("ba-offcanvas", "is_open"),
    Output("ba-offcanvas", "title"),
    Output("ba-form-host", "options"),
    Output("ba-form-phage", "options"),
    Output("ba-form-batch", "options"),
    Output("store-ba-edit-id", "data"),
    Output("btn-ba-delete", "style"),
    Input("btn-ba-new", "n_clicks"),
    Input("btn-ba-cancel", "n_clicks"),
    Input("ba-grid", "cellClicked"),
    State("ba-grid", "rowData"),
    prevent_initial_call=True,
)
def toggle_ba_offcanvas(new_n, cancel_n, cell, data):
    trigger = ctx.triggered_id
    
    if trigger == "btn-ba-cancel":
        return False, no_update, no_update, no_update, no_update, no_update, no_update

    hosts = _get_hosts()
    phages = _get_phages()
    batches = _get_batches()

    if trigger == "btn-ba-new":
        return True, "录入生物膜实验", hosts, phages, batches, None, {"display": "none"}

    if trigger == "ba-grid" and cell and cell.get("colId") == "actions":
        rowIndex = cell.get("rowIndex")
        if rowIndex is not None and data and rowIndex < len(data):
            row = data[rowIndex]
            return True, "编辑生物膜实验", hosts, phages, batches, row["id"], {"display": "inline-block"}

    return False, no_update, no_update, no_update, no_update, no_update, no_update

# ============================================================
# 回调拆分：回填表单数据
# ============================================================
@callback(
    Output("ba-form-ctype", "value"),
    Output("ba-form-host", "value"),
    Output("ba-form-phage", "value"),
    Output("ba-form-od-form", "value"),
    Output("ba-form-od-res", "value"),
    Output("ba-form-moi", "value"),
    Output("ba-form-duration", "value"),
    Output("ba-form-status", "value"), # ★ 新增
    Output("ba-form-batch", "value"),
    Input("store-ba-edit-id", "data"),
    State("ba-grid", "rowData"),
    State("ba-grid", "cellClicked"),
    prevent_initial_call=True,
)
def fill_form_data(edit_id, data, cell):
    # 新建：填入默认值
    if not edit_id:
        return "engineered_phage", None, None, 1.2, 0.3, 1.0, 24, "completed", None

    # 编辑：回填数据
    if cell and data:
        rowIndex = cell.get("rowIndex")
        if rowIndex is not None and rowIndex < len(data):
            row = data[rowIndex]
            return (
                row.get("control_type", "engineered_phage"),
                row.get("host_strain_id"),
                row.get("phage_id"),
                row.get("biofilm_formation_od"),
                row.get("biofilm_residual_od"),
                row.get("moi"),
                row.get("treatment_duration_h"),
                row.get("status", "completed"), # ★ 新增回填
                row.get("batch_id")
            )
    return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

# 保存（新增/更新）
@callback(
    Output("ba-form-feedback", "children"),
    Output("ba-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ba-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ba-save", "n_clicks"),
    State("store-ba-edit-id", "data"),
    State("ba-form-ctype", "value"),
    State("ba-form-host", "value"),
    State("ba-form-phage", "value"),
    State("ba-form-od-form", "value"),
    State("ba-form-od-res", "value"),
    State("ba-form-moi", "value"),
    State("ba-form-duration", "value"),
    State("ba-form-status", "value"), # ★ 接收状态
    State("ba-form-batch", "value"),
    prevent_initial_call=True,
)
def save_biofilm(_, edit_id, ctype, host, phage, od_form, od_res, moi, duration, estatus, batch_id):
    if not batch_id:
        return dbc.Alert("必须选择实验批次", color="danger"), no_update, no_update
    try:
        user = session.get("user", {})
        creator = user.get("name", "未知用户")

        reduction = 0.0
        if od_form and od_form > 0:
            reduction = round((1 - (od_res / od_form)) * 100, 1)
            
        with get_driver().session() as s:
            if edit_id:
                # 更新
                s.run("""
                    MATCH (b:BiofilmAssay {id: $id})
                    SET b.control_type = $ctype, b.host_strain_id = $host, b.phage_id = $phage,
                        b.biofilm_formation_od = $od_form, b.biofilm_residual_od = $od_res,
                        b.biofilm_reduction_pct = $reduction,
                        b.moi = $moi, b.treatment_duration_h = $duration,
                        b.status = $estatus, b.updated_at = datetime()
                    WITH b
                    OPTIONAL MATCH (b)-[r:BELONGS_TO_BATCH]->()
                    DELETE r
                    WITH b
                    MATCH (batch:ExperimentBatch {id: $batch_id})
                    CREATE (b)-[:BELONGS_TO_BATCH {recorded_at: datetime()}]->(batch)
                """, id=edit_id, ctype=ctype, host=host, phage=phage,
                     od_form=float(od_form) if od_form else 0.0,
                     od_res=float(od_res) if od_res else 0.0,
                     reduction=reduction,
                     moi=float(moi) if moi else None,
                     duration=float(duration) if duration else None,
                     estatus=estatus,
                     batch_id=batch_id)
                audit("UPDATE", "BiofilmAssay", edit_id, reason=f"更新生物膜实验: {edit_id}")
                msg = f"更新成功，消除率 {reduction}%"
            else:
                # 新建
                bf_id = f"BF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:3].upper()}"
                s.run("""
                    CREATE (b:BiofilmAssay {
                        id: $id, control_type: $ctype, host_strain_id: $host, phage_id: $phage,
                        biofilm_formation_od: $od_form, biofilm_residual_od: $od_res,
                        biofilm_reduction_pct: $reduction,
                        moi: $moi, treatment_duration_h: $duration,
                        status: $estatus, created_at: datetime(), created_by: $creator
                    })
                    WITH b
                    MATCH (batch:ExperimentBatch {id: $batch_id})
                    CREATE (b)-[:BELONGS_TO_BATCH {recorded_at: datetime()}]->(batch)
                """, id=bf_id, ctype=ctype, host=host, phage=phage,
                     od_form=float(od_form) if od_form else 0.0,
                     od_res=float(od_res) if od_res else 0.0,
                     reduction=reduction,
                     moi=float(moi) if moi else None,
                     duration=float(duration) if duration else None,
                     estatus=estatus,
                     batch_id=batch_id, creator=creator)
                audit("CREATE", "BiofilmAssay", bf_id, reason=f"录入生物膜实验: {bf_id}")
                msg = f"录入成功，消除率 {reduction}%"

        return dbc.Alert(msg, color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update

# 触发删除弹窗
@callback(
    Output("modal-ba-delete", "is_open"),
    Output("store-ba-delete-id", "data"),
    Input("btn-ba-delete", "n_clicks"),
    State("store-ba-edit-id", "data"),
    prevent_initial_call=True,
)
def trigger_delete(n, edit_id):
    if not n or not edit_id:
        return no_update, no_update
    return True, edit_id

# 确认删除
@callback(
    Output("modal-ba-delete", "is_open", allow_duplicate=True),
    Output("ba-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ba-refresh", "n_clicks", allow_duplicate=True),
    Output("ba-form-feedback", "children", allow_duplicate=True),
    Input("btn-ba-del-confirm", "n_clicks"),
    Input("btn-ba-del-cancel", "n_clicks"),
    State("store-ba-delete-id", "data"),
    prevent_initial_call=True,
)
def confirm_delete(confirm_n, cancel_n, delete_id):
    trigger = ctx.triggered_id
    if trigger == "btn-ba-del-cancel" or not delete_id:
        return False, no_update, no_update, no_update

    try:
        with get_driver().session() as s:
            s.run("MATCH (b:BiofilmAssay {id: $id}) DETACH DELETE b", id=delete_id)
        
        audit("UPDATE", "BiofilmAssay", delete_id, reason=f"删除生物膜实验记录: {delete_id}")
        msg = dbc.Alert(f"记录 {delete_id} 已成功删除", color="success", dismissable=True)
        
        return False, False, 1, msg
    except Exception as e:
        return False, no_update, no_update, dbc.Alert(f"删除失败: {e}", color="danger")