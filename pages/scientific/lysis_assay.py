# pages/scientific/lysis_assay.py
import uuid
import json
from datetime import datetime
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import plotly.graph_objects as go

from data_access.queries import list_phages, list_host_strains, _run
from data_access.audit import audit
from config import get_driver
from src.shared.evidence_source import get_or_create_pathogen

dash.register_page(__name__, path="/scientific/lysis-assay", name="裂解实验")

# ============================================================
# 字典
# ============================================================
RESULT_OPTIONS = [
    {"label": "阳性（Lytic）",     "value": "Lytic"},
    {"label": "阴性（Non-lytic）", "value": "Non-lytic"},
]

ASSAY_TYPE_OPTIONS = [
    {"label": "点滴板 (spot)", "value": "spot"},
    {"label": "液体培养 (liquid)", "value": "liquid"},
    {"label": "双层琼脂 (plaque)", "value": "plaque"},
    {"label": "效率铺板 (eop)", "value": "eop"},
]

ASSAY_TYPE_MAP = {
    "spot": "点滴板 (spot)",
    "liquid": "液体培养 (liquid)",
    "plaque": "双层琼脂 (plaque)",
    "eop": "效率铺板 (eop)",
    "lysis_assay": "🧪 常规裂解"
}

EVIDENCE_OPTIONS = [
    {"label": "L1", "value": "L1"},
    {"label": "L2", "value": "L2"},
    {"label": "L3", "value": "L3"},
    {"label": "L4", "value": "L4"},
    {"label": "L5", "value": "L5"},
]

QC_OPTIONS = [
    {"label": "待审核", "value": "pending"},
    {"label": "已通过", "value": "passed"},
    {"label": "未通过", "value": "failed"},
]
QC_MAP = {"pending": "📝 待审核", "passed": "✅ 已通过", "failed": "❌ 未通过"}

# ★ 优化：使用 flex 让关键列自适应填满屏幕
COLUMNS = [
    {"field": "id", "headerName": "实验 ID", "width": 150, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "phage_name", "headerName": "噬菌体", "flex": 1, "minWidth": 120},
    {"field": "host_label", "headerName": "宿主菌株", "flex": 1, "minWidth": 120},
    {"field": "assay_type_cn", "headerName": "实验类型", "flex": 1, "minWidth": 130},
    {"field": "result", "headerName": "结果", "width": 100},
    {"field": "eop_value", "headerName": "EOP 值", "width": 100, "type": "numericColumn"},
    {"field": "host_mucoid_cn", "headerName": "黏液型宿主", "width": 100},
    {"field": "evidence_level", "headerName": "证据等级", "width": 100},
    {"field": "qc_status_cn", "headerName": "QC 状态", "width": 120},
    {"field": "actions", "headerName": "操作", "flex": 1, "minWidth": 140, "sortable": False, "filter": False, 
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center", "whiteSpace": "nowrap"}},
]

def _list_pathogen_options():
    try:
        rows = _run("MATCH (p:Pathogen) RETURN p.species AS species ORDER BY species")
        return [{"label": r["species"], "value": r["species"]} for r in rows if r.get("species")]
    except: return []

def _get_phage_options():
    try:
        with get_driver().session() as s:
            return [{"label": f"{r['name']} ({r['id']})", "value": r['id']} for r in s.run("MATCH (p:Phage) RETURN p.phage_id AS id, p.name AS name ORDER BY p.name LIMIT 100")]
    except: return []

def _get_host_options():
    try:
        with get_driver().session() as s:
            return [{"label": f"{r['label']} ({r['id']})", "value": r['id']} for r in s.run("MATCH (h:HostStrain) RETURN h.host_strain_id AS id, h.strain_label AS label ORDER BY h.strain_label LIMIT 100")]
    except: return []

# 解析 JSON 渲染 OD 曲线
def _render_od_curve(od_json):
    if not od_json:
        return html.Div("暂无 OD 时序数据", style={"color": "var(--c-text-muted)", "fontSize": "13px", "textAlign": "center", "padding": "20px"})
    
    try:
        data = json.loads(od_json) if isinstance(od_json, str) else od_json
        times = [d["t_h"] for d in data]
        ods = [d["od"] for d in data]
    except Exception:
        return dbc.Alert("时序数据解析失败，请检查 JSON 格式", color="warning", style={"fontSize": "13px"})

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=times, y=ods, mode="lines+markers", name="OD600",
        line=dict(color="#1B6CA8", width=2), marker=dict(size=6)
    ))
    fig.update_layout(
        height=240, margin=dict(l=40, r=20, t=20, b=40),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="时间 (h)", yaxis_title="OD600",
        xaxis=dict(showgrid=True, gridcolor="#E2E8F0"),
        yaxis=dict(showgrid=True, gridcolor="#E2E8F0")
    )
    return dcc.Graph(figure=fig, config={"displayModeBar": False})

layout = html.Div([
    html.Div(id="la-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("裂解实验", className="page-title"),
            html.Div("管理噬菌体 × 宿主互作 · 溶菌曲线 · EOP", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-la-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增实验"], id="btn-la-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="la-search", type="text", debounce=True, value="", placeholder="搜索实验 ID…", className="filter-search"),
        html.Div(id="la-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="la-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight", "localeText": {"noRowsToShow": "暂无数据"}},
            style={"height": None, "minHeight": "420px"}
        ),
    ]),

    # 录入 / 编辑 / 详情 抽屉
    dcc.Store(id="store-la-edit-id"),
    dbc.Offcanvas(
        id="la-offcanvas", title="裂解实验详情", placement="end", is_open=False, style={"width": "600px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("噬菌体 *", width=3), dbc.Col(dcc.Dropdown(id="la-form-phage", options=[], placeholder="选择噬菌体"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("宿主菌株 *", width=3), dbc.Col(dcc.Dropdown(id="la-form-host", options=[], placeholder="选择宿主"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("病原物种 *", width=3), dbc.Col(dcc.Dropdown(id="la-form-pathogen", options=_list_pathogen_options(), placeholder="选择病原"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("实验类型", width=3), dbc.Col(dbc.Select(id="la-form-type", options=ASSAY_TYPE_OPTIONS, value="spot"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("结果", width=3), dbc.Col(dbc.Select(id="la-form-result", options=RESULT_OPTIONS, value="Lytic"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("EOP 值", width=3), dbc.Col(dbc.Input(id="la-form-eop", type="number", step="0.001"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("黏液型宿主", width=3), dbc.Col(dbc.Select(id="la-form-mucoid", options=[{"label":"是","value":"true"},{"label":"否","value":"false"}], value="false"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("证据等级", width=3), dbc.Col(dbc.Select(id="la-form-evidence", options=EVIDENCE_OPTIONS, value="L2"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("QC 状态", width=3), dbc.Col(dbc.Select(id="la-form-qc", options=QC_OPTIONS, value="pending"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("OD 时序 JSON", width=3), dbc.Col(dbc.Textarea(id="la-form-od", rows=3, placeholder='格式: [{"t_h": 0, "od": 0.8}, {"t_h": 2, "od": 0.4}]'), width=9)], className="mb-4"),
            
            # 时序图展示区
            html.Hr(),
            html.H6([html.I(className="bi bi-graph-up me-2"), "溶菌曲线 (OD600)"], style={"fontWeight": "600"}),
            html.Div(id="la-od-chart", className="mt-3 mb-4"),

            html.Div([
                html.Button("关闭", id="btn-la-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存修改"], id="btn-la-save", className="btn-primary-custom"),
                html.Button([html.I(className="bi bi-shield-check me-1"), "QC 审核"], id="btn-la-qc", className="btn-outline-custom ms-2", style={"color": "var(--c-secondary)"}),
                html.Button([html.I(className="bi bi-trash me-1"), "删除"], id="btn-la-delete", className="btn-danger-custom ms-2", style={"display": "none"}),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="la-form-feedback", className="mt-3"),
        ])]),
        
    # 删除确认
    dcc.Store(id="store-la-delete-id"),
    dbc.Modal(
        id="modal-la-delete", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody("确定要删除这条裂解实验记录吗？"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-la-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-la-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    )
])

# ============================================================
# 加载列表
# ============================================================
@callback(
    Output("la-grid", "rowData"),
    Output("la-count-label", "children"),
    Input("btn-la-refresh", "n_clicks"),
    Input("la-search", "value"),
    Input("btn-la-save", "n_clicks"),
    Input("btn-la-del-confirm", "n_clicks"),
    Input("btn-la-qc", "n_clicks"),
)
def cb_load(_, search, __, ___, ____):
    try:
        with get_driver().session() as s:
            q = """
            MATCH (a:LysisAssay)
            WHERE ($kw = '' OR toLower(a.assay_id) CONTAINS toLower($kw))
            OPTIONAL MATCH (ph:Phage)-[:USED_IN]->(a)
            OPTIONAL MATCH (a)-[:TESTED_AGAINST]->(h:HostStrain)
            RETURN a.assay_id AS id, a.assay_type AS assay_type, a.result AS result,
                   a.eop_value AS eop_value, a.host_mucoid AS host_mucoid,
                   a.evidence_level AS evidence_level, a.qc_status AS qc_status,
                   a.od_timeseries AS od_timeseries, a.pathogen_id AS pathogen_id,
                   ph.phage_id AS phage_id, ph.name AS phage_name, h.host_strain_id AS host_id, h.strain_label AS host_label
            ORDER BY a.created_at DESC LIMIT 100
            """
            rows = [dict(r) for r in s.run(q, kw=search or "")]
            
            for r in rows:
                qc = str(r.get("qc_status") or "pending").strip().lower()
                r["qc_status_cn"] = QC_MAP.get(qc, qc)
                
                atype = str(r.get("assay_type") or "lysis_assay").strip().lower()
                r["assay_type_cn"] = ASSAY_TYPE_MAP.get(atype, atype)
                
                r["host_mucoid_cn"] = "是" if r.get("host_mucoid") else "否"
                r["actions"] = "🔍 查看 / 编辑"
                
            return rows, f"共 {len(rows)} 条"
    except Exception as e:
        return [], "加载失败"

# ============================================================
# 抽屉交互
# ============================================================
@callback(
    Output("la-offcanvas", "is_open"),
    Output("la-offcanvas", "title"),
    Output("la-form-phage", "options"),
    Output("la-form-host", "options"),
    Output("store-la-edit-id", "data"),
    Output("btn-la-delete", "style"),
    Input("btn-la-new", "n_clicks"),
    Input("btn-la-cancel", "n_clicks"),
    Input("la-grid", "cellClicked"),
    State("la-grid", "rowData"),
    prevent_initial_call=True,
)
def toggle_la_offcanvas(new_n, cancel_n, cell, data):
    trigger = ctx.triggered_id
    if trigger == "btn-la-cancel":
        return False, no_update, no_update, no_update, no_update, no_update

    phages = _get_phage_options()
    hosts = _get_host_options()

    if trigger == "btn-la-new":
        return True, "新增裂解实验", phages, hosts, None, {"display": "none"}

    if trigger == "la-grid" and cell and cell.get("colId") == "actions":
        rowIndex = cell.get("rowIndex")
        if rowIndex is not None and data and rowIndex < len(data):
            return True, "编辑裂解实验", phages, hosts, data[rowIndex]["id"], {"display": "inline-block"}

    return False, no_update, no_update, no_update, no_update, no_update

@callback(
    Output("la-form-phage", "value"),
    Output("la-form-host", "value"),
    Output("la-form-pathogen", "value"),
    Output("la-form-type", "value"),
    Output("la-form-result", "value"),
    Output("la-form-eop", "value"),
    Output("la-form-mucoid", "value"),
    Output("la-form-evidence", "value"),
    Output("la-form-qc", "value"),
    Output("la-form-od", "value"),
    Output("la-od-chart", "children"),
    Input("store-la-edit-id", "data"),
    State("la-grid", "rowData"),
    State("la-grid", "cellClicked"),
    prevent_initial_call=True,
)
def fill_la_form(edit_id, data, cell):
    if not edit_id:
        return None, None, None, "spot", "Lytic", None, "false", "L2", "pending", "", _render_od_curve(None)

    if cell and data:
        rowIndex = cell.get("rowIndex")
        if rowIndex is not None and rowIndex < len(data):
            row = data[rowIndex]
            od_data = row.get("od_timeseries")
            od_str = str(od_data) if od_data else ""
            
            return (
                row.get("phage_id"),
                row.get("host_id"),
                row.get("pathogen_id"),
                row.get("assay_type", "spot"),
                row.get("result", "Lytic"),
                row.get("eop_value"),
                "true" if row.get("host_mucoid") else "false",
                row.get("evidence_level", "L2"),
                row.get("qc_status", "pending"),
                od_str,
                _render_od_curve(od_str)
            )
    return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update

# 实时渲染输入框的 JSON
@callback(
    Output("la-od-chart", "children", allow_duplicate=True),
    Input("la-form-od", "value"),
    prevent_initial_call=True,
)
def update_chart_live(json_str):
    return _render_od_curve(json_str)

# ============================================================
# 保存 / 删除
# ============================================================
@callback(
    Output("la-form-feedback", "children"),
    Output("la-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-la-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-la-save", "n_clicks"),
    State("store-la-edit-id", "data"),
    State("la-form-phage", "value"),
    State("la-form-host", "value"),
    State("la-form-pathogen", "value"),
    State("la-form-type", "value"),
    State("la-form-result", "value"),
    State("la-form-eop", "value"),
    State("la-form-mucoid", "value"),
    State("la-form-evidence", "value"),
    State("la-form-qc", "value"),
    State("la-form-od", "value"),
    prevent_initial_call=True,
)
def save_la(_, edit_id, phage_id, host_id, pathogen_species, atype, result, eop, mucoid, evidence, qc, od_str):
    if not phage_id or not host_id or not pathogen_species:
        return dbc.Alert("噬菌体、宿主、病原为必填项", color="danger"), no_update, no_update
    if od_str:
        try: json.loads(od_str)
        except: return dbc.Alert("OD 时序数据不是合法的 JSON 格式", color="danger"), no_update, no_update

    try:
        pathogen_id = get_or_create_pathogen(get_driver(), species=pathogen_species, actor_id="dash_frontend")
        is_mucoid = (mucoid == "true")

        with get_driver().session() as s:
            if edit_id:
                s.run("""
                    MATCH (a:LysisAssay {assay_id: $aid})
                    SET a.assay_type = $atype, a.result = $result, a.eop_value = $eop,
                        a.host_mucoid = $mucoid, a.evidence_level = $level, a.qc_status = $qc,
                        a.od_timeseries = $od, a.updated_at = datetime()
                    WITH a
                    OPTIONAL MATCH (ph:Phage)-[r1:USED_IN]->(a) DELETE r1
                    WITH a
                    OPTIONAL MATCH (a)-[r2:TESTED_AGAINST]->() DELETE r2
                """, aid=edit_id, atype=atype, result=result, eop=float(eop) if eop else None,
                     mucoid=is_mucoid, level=evidence, qc=qc, od=od_str)
                aid = edit_id
                msg = f"已更新实验 {aid}"
            else:
                aid = f"ASSAY-{uuid.uuid4().hex[:8].upper()}"
                s.run("""
                    CREATE (a:LysisAssay {
                        assay_id: $aid, pathogen_id: $pathid,
                        assay_type: $atype, result: $result, eop_value: $eop,
                        host_mucoid: $mucoid, evidence_level: $level, qc_status: $qc,
                        od_timeseries: $od, validation_status: 'unreviewed',
                        created_at: datetime(), updated_at: datetime()
                    })
                """, aid=aid, pathid=pathogen_id, atype=atype, result=result,
                     eop=float(eop) if eop else None, mucoid=is_mucoid,
                     level=evidence, qc=qc, od=od_str)
                msg = f"已创建实验 {aid}"

            s.run("""
                MATCH (a:LysisAssay {assay_id: $aid})
                MATCH (ph:Phage {phage_id: $pid}) MERGE (ph)-[:USED_IN]->(a)
                WITH a
                MATCH (h:HostStrain {host_strain_id: $hid}) MERGE (a)-[:TESTED_AGAINST]->(h)
                WITH h
                MATCH (p:Pathogen {pathogen_id: $pathid}) MERGE (h)-[:IS_STRAIN_OF]->(p)
            """, aid=aid, pid=phage_id, hid=host_id, pathid=pathogen_id)

        audit("CREATE" if not edit_id else "UPDATE", "LysisAssay", aid, reason=f"保存裂解实验: {aid}")
        return dbc.Alert(msg, color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update

# 快捷 QC 审核
@callback(
    Output("la-form-feedback", "children", allow_duplicate=True),
    Output("btn-la-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-la-qc", "n_clicks"),
    State("store-la-edit-id", "data"),
    prevent_initial_call=True,
)
def do_qc(n, edit_id):
    if not n or not edit_id:
        return no_update, no_update
    try:
        with get_driver().session() as s:
            s.run("MATCH (a:LysisAssay {assay_id: $aid}) SET a.qc_status = 'passed', a.updated_at = datetime()", aid=edit_id)
        return dbc.Alert("已快速通过 QC 审核", color="success"), 1
    except Exception as e:
        return dbc.Alert(f"审核失败: {e}", color="danger"), no_update

# 删除逻辑
@callback(
    Output("modal-la-delete", "is_open"),
    Output("store-la-delete-id", "data"),
    Input("btn-la-delete", "n_clicks"),
    State("store-la-edit-id", "data"),
    prevent_initial_call=True,
)
def trigger_la_delete(n, edit_id):
    if not n or not edit_id: return no_update, no_update
    return True, edit_id

@callback(
    Output("modal-la-delete", "is_open", allow_duplicate=True),
    Output("la-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-la-refresh", "n_clicks", allow_duplicate=True),
    Output("la-form-feedback", "children", allow_duplicate=True),
    Input("btn-la-del-confirm", "n_clicks"),
    Input("btn-la-del-cancel", "n_clicks"),
    State("store-la-delete-id", "data"),
    prevent_initial_call=True,
)
def confirm_la_delete(confirm_n, cancel_n, delete_id):
    if ctx.triggered_id == "btn-la-del-cancel" or not delete_id:
        return False, no_update, no_update, no_update
    try:
        with get_driver().session() as s:
            s.run("MATCH (a:LysisAssay {assay_id: $id}) DETACH DELETE a", id=delete_id)
        return False, False, 1, dbc.Alert(f"记录 {delete_id} 已删除", color="success", dismissable=True)
    except Exception as e:
        return False, no_update, no_update, dbc.Alert(f"删除失败: {e}", color="danger")