# pages/scientific/lysis_assay.py
import uuid
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_lysis_assays, list_phages, list_host_strains, _run
from data_access.audit import audit
from config import get_driver
from src.shared.evidence_source import get_or_create_pathogen

dash.register_page(__name__, path="/scientific/lysis-assay", name="裂解实验")

RESULT_OPTIONS = [
    {"label": "阳性（Lytic）",     "value": "Lytic"},
    {"label": "阴性（Non-lytic）", "value": "Non-lytic"},
]

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

QC_MAP = {
    "pending": "📝 待审核",
    "passed": "✅ 已通过",
    "failed": "❌ 未通过"
}

COLUMNS = [
    {"field": "id", "headerName": "实验 ID",
     "width": 220, "minWidth": 180,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "phage_name", "headerName": "噬菌体", "flex": 1, "minWidth": 130},
    {"field": "host_label", "headerName": "宿主菌株", "flex": 1, "minWidth": 130},
    {"field": "result", "headerName": "结果", "width": 100, "minWidth": 90},
    {"field": "result_value", "headerName": "数值", "width": 90, "minWidth": 80},
    {"field": "evidence_level", "headerName": "证据等级", "width": 110, "minWidth": 100},
    {"field": "qc_status_cn", "headerName": "QC 状态", "width": 110},
    {"field": "actions", "headerName": "QC 审核", "width": 100,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]


def _list_pathogen_options():
    try:
        rows = _run("MATCH (p:Pathogen) RETURN p.species AS species ORDER BY species")
        return [{"label": r["species"], "value": r["species"]}
                for r in rows if r.get("species")]
    except Exception:
        return []


def _format_rows(rows):
    for r in rows:
        qc = str(r.get("qc_status", "pending")).strip().lower()
        r["qc_status_cn"] = QC_MAP.get(qc, qc)
        if qc == "pending":
            r["actions"] = "去审核"
        else:
            r["actions"] = "已处理"
    return rows


layout = html.Div([
    html.Div(id="la-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("裂解实验", className="page-title"),
            html.Div("管理所有 LysisAssay · 噬菌体 × 宿主菌株互作",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-la-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增实验"],
                        id="btn-la-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="la-search", type="text", debounce=True, value="",
                  placeholder="搜索实验 ID…", className="filter-search"),
        dcc.Dropdown(id="la-result-filter",
                     options=[{"label": "全部结果", "value": ""}] + RESULT_OPTIONS,
                     value="", clearable=False, style={"width": "200px"}),
        html.Div(id="la-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="la-grid",
            columnDefs=COLUMNS,
            rowData=[],
            defaultColDef={
                "flex": 1,
                "minWidth": 100,
                "resizable": True,
                "sortable": True,
            },
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 20,
                "paginationPageSizeSelector": [10, 20, 50, 100],
                "domLayout": "autoHeight",
            },
            style={"height": None, "width": "100%", "minHeight": "500px"},
        ),
    ]),

    # 新增实验表单
    dbc.Offcanvas(
        id="la-offcanvas", title="新增裂解实验",
        placement="end", is_open=False, style={"width": "540px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("噬菌体 *", width=3),
                     dbc.Col(dcc.Dropdown(id="la-form-phage",
                                          placeholder="选择噬菌体",
                                          options=[], clearable=False),
                             width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("宿主菌株 *", width=3),
                     dbc.Col(dcc.Dropdown(id="la-form-host",
                                          placeholder="选择宿主菌株",
                                          options=[], clearable=False),
                             width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("病原 *", width=3),
                     dbc.Col(dcc.Dropdown(id="la-form-pathogen",
                                          placeholder="选择病原物种",
                                          options=_list_pathogen_options(),
                                          clearable=False),
                             width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("结果", width=3),
                     dbc.Col(dbc.Select(id="la-form-result",
                                        options=RESULT_OPTIONS,
                                        value="Lytic"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("数值", width=3),
                     dbc.Col(dbc.Input(id="la-form-value", type="number",
                                       step="0.01", min="0", max="1",
                                       value=1.0), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("证据等级", width=3),
                     dbc.Col(dbc.Select(id="la-form-evidence",
                                        options=EVIDENCE_OPTIONS,
                                        value="L2"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("QC 状态", width=3),
                     dbc.Col(dbc.Select(id="la-form-qc",
                                        options=QC_OPTIONS,
                                        value="pending"), width=9)],
                    className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-la-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-la-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="la-form-feedback", className="mt-3"),
        ])]),

    # QC 审核弹窗
    dcc.Store(id="store-active-assay"),
    dbc.Modal(
        id="modal-qc",
        is_open=False,
        centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("裂解实验 QC 审核")),
            dbc.ModalBody(id="modal-qc-body", children="请选择审核结果："),
            dbc.ModalFooter([
                html.Button("取消", id="btn-qc-cancel", className="btn-outline-custom me-2"),
                html.Button("❌ 未通过", id="btn-qc-fail", className="btn-danger-custom me-2"),
                html.Button("✅ 通过", id="btn-qc-pass", className="btn-primary-custom"),
            ]),
        ]
    )
])


@callback(
    Output("la-grid", "rowData"),
    Output("la-count-label", "children"),
    Output("la-error-banner", "children"),
    Input("btn-la-refresh", "n_clicks"),
    Input("la-search", "value"),
    Input("la-result-filter", "value"),
)
def cb_load(_, search, result):
    try:
        rows = list_lysis_assays(keyword=search or "", result=result or "")
        rows = _format_rows(rows)
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("la-offcanvas", "is_open"),
    Input("btn-la-new", "n_clicks"),
    Input("btn-la-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-la-new"


@callback(
    Output("la-form-phage", "options"),
    Output("la-form-host", "options"),
    Output("la-form-pathogen", "options"),
    Input("btn-la-new", "n_clicks"),
    prevent_initial_call=True,
)
def cb_load_options(_):
    try:
        phages = list_phages()
        phage_opts = [{"label": f"{p['name']} ({p['id']})", "value": p["id"]}
                      for p in phages if p.get("id")]
    except Exception:
        phage_opts = []
    try:
        hosts = list_host_strains()
        host_opts = [{"label": f"{h['label']} ({h['id']})", "value": h["id"]}
                     for h in hosts if h.get("id")]
    except Exception:
        host_opts = []
    return phage_opts, host_opts, _list_pathogen_options()


@callback(
    Output("la-form-feedback", "children"),
    Output("la-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-la-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-la-save", "n_clicks"),
    State("la-form-phage", "value"),
    State("la-form-host", "value"),
    State("la-form-pathogen", "value"),
    State("la-form-result", "value"),
    State("la-form-value", "value"),
    State("la-form-evidence", "value"),
    State("la-form-qc", "value"),
    prevent_initial_call=True,
)
def cb_save(_, phage_id, host_id, pathogen_species, result, value, evidence, qc):
    if not phage_id or not host_id or not pathogen_species:
        return (dbc.Alert("噬菌体、宿主菌株、病原均为必填", color="danger"),
                no_update, no_update)

    try:
        pathogen_id = get_or_create_pathogen(
            get_driver(), species=pathogen_species, actor_id="dash_frontend")

        assay_id = f"ASSAY-{uuid.uuid4().hex[:8].upper()}"
        with get_driver().session() as s:
            s.run("""
                MATCH (ph:Phage {phage_id: $pid})
                CREATE (a:LysisAssay {
                    assay_id: $aid, pathogen_id: $pathid,
                    assay_type: 'lysis_assay',
                    result: $result, result_value: $value,
                    result_unit: 'probability',
                    evidence_level: $level,
                    qc_status: $qc,
                    validation_status: 'unreviewed',
                    evidence_policy_version: 'v1.0',
                    source_domain: 'scientific',
                    created_at: datetime(), updated_at: datetime(),
                    version: 1
                })
                CREATE (ph)-[:USED_IN]->(a)
                WITH a
                MATCH (h:HostStrain {host_strain_id: $hid})
                CREATE (a)-[:TESTED_AGAINST]->(h)
                WITH h
                MATCH (p:Pathogen {pathogen_id: $pathid})
                MERGE (h)-[:IS_STRAIN_OF]->(p)
            """, pid=phage_id, aid=assay_id, pathid=pathogen_id,
                 result=result, value=float(value or 0),
                 level=evidence, qc=qc, hid=host_id)

        audit("CREATE", "LysisAssay", assay_id,
              delta={"phage_id": phage_id, "host_id": host_id,
                     "result": result, "evidence_level": evidence},
              reason=f"录入裂解实验 {assay_id}")
        return dbc.Alert(f"已创建 {assay_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update


# ★ 1. 监听点击单元格，提取数据并打开弹窗
@callback(
    Output("store-active-assay", "data"),
    Output("modal-qc", "is_open", allow_duplicate=True),
    Output("modal-qc-body", "children"),
    Input("la-grid", "cellClicked"),
    State("la-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_qc_modal(cell, rowData):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or rowData is None or len(rowData) <= rowIndex:
        return no_update, no_update, no_update

    row_data = rowData[rowIndex]
    
    if str(row_data.get("qc_status", "pending")).strip().lower() != "pending":
        return no_update, no_update, no_update

    assay_id = row_data.get("id")
    body_text = f"请对裂解实验 {assay_id} 进行 QC 审核："
    return assay_id, True, body_text


# ★ 2. 弹窗内点击通过/未通过：直接更新 Cypher，彻底绕开 service 报错
@callback(
    Output("modal-qc", "is_open", allow_duplicate=True),
    Output("btn-la-refresh", "n_clicks", allow_duplicate=True),
    Output("la-error-banner", "children", allow_duplicate=True),
    Input("btn-qc-pass", "n_clicks"),
    Input("btn-qc-fail", "n_clicks"),
    Input("btn-qc-cancel", "n_clicks"),
    State("store-active-assay", "data"),
    prevent_initial_call=True,
)
def cb_execute_qc(pass_n, fail_n, cancel_n, assay_id):
    trigger = ctx.triggered_id
    if trigger == "btn-qc-cancel" or not assay_id:
        return False, no_update, no_update

    decision = "passed" if trigger == "btn-qc-pass" else "failed"
    
    try:
        with get_driver().session() as s:
            # 1. 更新状态（防御性设置，忽略原本可能缺失的字段）
            res = s.run("""
                MATCH (a:LysisAssay {assay_id: $aid})
                SET a.qc_status = $decision, 
                    a.validation_status = 'reviewed',
                    a.updated_at = datetime()
                RETURN a.assay_id AS id
            """, aid=assay_id, decision=decision).single()
            
            if not res:
                return False, no_update, dbc.Alert(f"未找到实验 {assay_id}", color="danger")

            # 2. 写入 Review 记录
            rid = f"REV-{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (a:LysisAssay {assay_id: $aid})
                CREATE (r:Review {
                    review_id: $rid, review_type: 'assay_qc',
                    target_object_type: 'LysisAssay',
                    target_object_id: $aid, reviewer_id: 'dashboard_admin',
                    decision: $decision, created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(a)
            """, aid=assay_id, decision=decision, rid=rid)

        status_str = "已通过" if decision == "passed" else "未通过"
        msg = dbc.Alert(f"操作成功：{assay_id} QC 状态已标记为【{status_str}】", color="success", dismissable=True, duration=3000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"执行失败：{e}", color="danger", dismissable=True)