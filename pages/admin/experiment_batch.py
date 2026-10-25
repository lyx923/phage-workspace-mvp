# pages/admin/experiment_batch.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import uuid
from datetime import datetime
from flask import session
from config import get_driver
from data_access.audit import audit

dash.register_page(__name__, path="/admin/experiment-batch", name="实验批次")

# ============================================================
# ★ PRD 规定的实验类型枚举
# ============================================================
EXPERIMENT_TYPE_OPTIONS = [
    {"label": "🧪 酶筛选 (enzyme_screening)", "value": "enzyme_screening"},
    {"label": "🧬 噬菌体工程 (phage_engineering)", "value": "phage_engineering"},
    {"label": "🦠 裂解实验 (lysis_assay)", "value": "lysis_assay"},
    {"label": "🔬 生物膜实验 (biofilm_assay)", "value": "biofilm_assay"},
    {"label": "🧬 测序分析 (sequencing)", "value": "sequencing"},
]
TYPE_MAP = {opt["value"]: opt["label"] for opt in EXPERIMENT_TYPE_OPTIONS}

# ★ PRD 规定的状态枚举
STATUS_OPTIONS = [
    {"label": "📅 已计划 (planned)", "value": "planned"},
    {"label": "⏳ 进行中 (in_progress)", "value": "in_progress"},
    {"label": "✅ 已完成 (completed)", "value": "completed"},
    {"label": "❌ 失败 (failed)", "value": "failed"},
]
STATUS_MAP = {opt["value"]: opt["label"] for opt in STATUS_OPTIONS}

COLUMNS = [
    {"field": "id", "headerName": "批次 ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "12px"}},
    {"field": "name", "headerName": "批次名称", "flex": 1, "minWidth": 200},
    {"field": "type_cn", "headerName": "实验类型", "width": 220},
    {"field": "operator", "headerName": "操作人", "width": 110},
    {"field": "date", "headerName": "实验日期", "width": 120},
    {"field": "status_cn", "headerName": "状态", "width": 140},
    # ★ 加宽操作列到 160
    {"field": "actions", "headerName": "操作与详情", "width": 160, "sortable": False, "filter": False, 
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "textAlign": "center", "fontWeight": "bold"}},
]

layout = html.Div([
    html.Div(id="eb-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("实验批次管理", className="page-title"),
            html.Div("数据血缘锚点 · 追溯实验数据的来源批次", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-eb-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新建批次"], id="btn-eb-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="eb-grid", columnDefs=COLUMNS, rowData=[], 
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight", "localeText": {"noRowsToShow": "暂无数据"}}, 
            style={"height": None, "minHeight": "400px"}
        ),
    ]),

    # 新建抽屉
    dbc.Offcanvas(
        id="eb-offcanvas", title="新建实验批次", placement="end", is_open=False, style={"width": "480px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("批次名称 *", width=3), dbc.Col(dbc.Input(id="eb-form-name", placeholder="如 AlgL 酶筛选第一批"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("实验类型", width=3), dbc.Col(dbc.Select(id="eb-form-type", options=EXPERIMENT_TYPE_OPTIONS, value="enzyme_screening"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("实验状态", width=3), dbc.Col(dbc.Select(id="eb-form-status", options=STATUS_OPTIONS, value="in_progress"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("操作人", width=3), dbc.Col(dbc.Input(id="eb-form-operator", disabled=True), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("实验日期", width=3), dbc.Col(dbc.Input(id="eb-form-date", type="date"), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-eb-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "创建"], id="btn-eb-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="eb-form-feedback", className="mt-3"),
        ])]),

    # 统一详情面板（包含状态修改 + 关联数据）
    dcc.Store(id="store-active-batch"),
    dbc.Offcanvas(
        id="eb-detail-drawer", title="批次详情与管理", placement="end", is_open=False, style={"width": "500px"},
        children=[
            html.Div(id="eb-detail-info", style={"marginBottom": "20px"}),
            
            html.Hr(),
            html.H6([html.I(className="bi bi-gear me-2"), "修改批次状态"], style={"fontWeight": "600"}),
            dbc.Row(className="mt-3 mb-4", children=[
                dbc.Col(dbc.Select(id="eb-detail-status-select", options=STATUS_OPTIONS), width=8),
                dbc.Col(html.Button("保存修改", id="btn-eb-detail-status-save", className="btn-primary-custom w-100"), width=4)
            ]),
            html.Div(id="eb-detail-status-feedback"),
            
            html.Hr(),
            html.H6([html.I(className="bi bi-diagram-3 me-2"), "挂载关联数据"], style={"fontWeight": "600"}),
            html.Div(id="eb-detail-related", className="mt-3")
        ]
    )
])

# ★ 打开新建抽屉时，自动填充当前登录用户名 和 当天日期
@callback(
    Output("eb-offcanvas", "is_open"),
    Output("eb-form-operator", "value"),
    Output("eb-form-date", "value"),
    Input("btn-eb-new", "n_clicks"),
    Input("btn-eb-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_eb_offcanvas(new_n, cancel_n):
    if ctx.triggered_id == "btn-eb-new":
        user = session.get("user", {})
        op_name = user.get("name", "未知用户")
        today_str = datetime.now().strftime("%Y-%m-%d")  # 获取当天日期 YYYY-MM-DD
        return True, op_name, today_str
    return False, no_update, no_update

# 列表加载
@callback(
    Output("eb-grid", "rowData"),
    Input("btn-eb-refresh", "n_clicks"),
    Input("btn-eb-save", "n_clicks"),
)
def load_batches(_, __):
    try:
        with get_driver().session() as s:
            query = """
            MATCH (b:ExperimentBatch)
            RETURN b.id AS id, b.name AS name, b.experiment_type AS experiment_type, 
                   b.operator AS operator, b.date AS date, b.status AS status
            ORDER BY b.created_at DESC
            """
            rows = [dict(r) for r in s.run(query)]
            for r in rows:
                etype = str(r.get("experiment_type") or "").strip()
                status = str(r.get("status") or "").strip()
                r["type_cn"] = TYPE_MAP.get(etype, etype)
                r["status_cn"] = STATUS_MAP.get(status, status)
                r["actions"] = "⚙️ 详情 / 设置"
            return rows
    except Exception as e: 
        print(f"Error loading batches: {e}")
        return []

# 保存新批次
@callback(
    Output("eb-form-feedback", "children"),
    Output("eb-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-eb-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-eb-save", "n_clicks"),
    State("eb-form-name", "value"),
    State("eb-form-type", "value"),
    State("eb-form-status", "value"),
    State("eb-form-date", "value"),
    prevent_initial_call=True,
)
def save_batch(_, name, etype, estatus, date):
    if not name:
        return dbc.Alert("批次名称必填", color="danger"), no_update, no_update
    try:
        user = session.get("user", {})
        operator = user.get("name", "未知用户")

        b_id = f"BATCH-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:3].upper()}"
        with get_driver().session() as s:
            s.run("""
                CREATE (b:ExperimentBatch {
                    id: $id, name: $name, experiment_type: $etype,
                    operator: $operator, date: $date, status: $estatus,
                    created_at: datetime()
                })
            """, id=b_id, name=name, etype=etype, operator=operator, date=date, estatus=estatus)
            
        audit("CREATE", "ExperimentBatch", b_id, reason=f"新建实验批次: {name}")
        return dbc.Alert("创建成功", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"错误: {e}", color="danger"), no_update, no_update

# 点击操作列，一次性加载详情面板的所有内容
@callback(
    Output("store-active-batch", "data"),
    Output("eb-detail-drawer", "is_open"),
    Output("eb-detail-info", "children"),
    Output("eb-detail-status-select", "value"),
    Output("eb-detail-related", "children"),
    Output("eb-detail-status-feedback", "children"),
    Input("eb-grid", "cellClicked"),
    State("eb-grid", "rowData"),
    prevent_initial_call=True,
)
def open_detail_drawer(cell, data):
    if not cell or not data or cell.get("colId") != "actions":
        return no_update, no_update, no_update, no_update, no_update, no_update
        
    rowIndex = cell.get("rowIndex")
    if rowIndex is None or rowIndex >= len(data):
        return no_update, no_update, no_update, no_update, no_update, no_update
        
    row = data[rowIndex]
    batch_id = row["id"]
    current_status = row.get("status", "in_progress")
    
    # 顶部基础信息
    info_ui = [
        html.H5(f"批次: {row['name']}", style={"color": "var(--c-primary)", "marginBottom": "12px"}),
        html.Div([html.Span("批次 ID: ", style={"fontWeight": "600"}), html.Span(batch_id, style={"fontFamily": "monospace"})], className="mb-2"),
        html.Div([html.Span("实验类型: ", style={"fontWeight": "600"}), html.Span(row['type_cn'])], className="mb-2"),
        html.Div([html.Span("操作人: ", style={"fontWeight": "600"}), html.Span(row['operator'])], className="mb-2"),
        html.Div([html.Span("实验日期: ", style={"fontWeight": "600"}), html.Span(row['date'])], className="mb-2"),
    ]

    # 关联数据查询
    try:
        with get_driver().session() as s:
            counts = s.run("""
                MATCH (n)-[:BELONGS_TO_BATCH]->(b:ExperimentBatch {id: $bid})
                RETURN labels(n)[0] AS type, count(n) AS cnt
            """, bid=batch_id).data()
        
        label_cn = {"EnzymeGene": "酶基因", "LysisAssay": "裂解实验", "BiofilmAssay": "生物膜实验"}
        items = [html.Li(f"{label_cn.get(c['type'], c['type'])} × {c['cnt']} 条") for c in counts]
        if not items: items = [html.Li("暂无关联数据", style={"color": "var(--c-text-muted)"})]
        related_ui = html.Ul(items, style={"fontSize": "13px", "lineHeight": "1.8"})
    except Exception as e:
        related_ui = dbc.Alert(f"查询关联数据失败: {e}", color="danger")

    return batch_id, True, info_ui, current_status, related_ui, ""

# 在抽屉中直接修改状态，保存后立即关闭抽屉并刷新列表
@callback(
    Output("eb-detail-drawer", "is_open", allow_duplicate=True),
    Output("btn-eb-refresh", "n_clicks", allow_duplicate=True),
    Output("eb-error-banner", "children", allow_duplicate=True),
    Input("btn-eb-detail-status-save", "n_clicks"),
    State("store-active-batch", "data"),
    State("eb-detail-status-select", "value"),
    prevent_initial_call=True,
)
def save_detail_status(n_clicks, batch_id, new_status):
    if not n_clicks or not batch_id:
        return no_update, no_update, no_update

    try:
        user = session.get("user", {})
        operator = user.get("name", "未知用户")
        
        with get_driver().session() as s:
            old_status = s.run("MATCH (b:ExperimentBatch {id: $id}) RETURN b.status AS st", id=batch_id).single()["st"]
            s.run("""
                MATCH (b:ExperimentBatch {id: $id})
                SET b.status = $st, b.updated_at = datetime()
            """, id=batch_id, st=new_status)
            
        audit("STATUS_CHANGE", "ExperimentBatch", batch_id, 
              delta={"status": {"before": old_status, "after": new_status}}, 
              reason=f"{operator} 将批次状态修改为 {new_status}")
              
        msg = dbc.Alert(f"状态已成功更新为【{STATUS_MAP.get(new_status)}】", color="success", dismissable=True, duration=3000)
        
        # 返回 False 立刻关闭抽屉，返回 1 触发列表刷新
        return False, 1, msg
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"修改失败：{e}", color="danger", dismissable=True)