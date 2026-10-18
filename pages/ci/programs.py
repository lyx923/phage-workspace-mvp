# pages/ci/programs.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_programs
from data_access.mutations import add_program
from config import get_driver

dash.register_page(__name__, path="/ci/programs", name="开发项目")

STAGE_OPTIONS = [
    {"label": "发现阶段", "value": "discovery"},
    {"label": "临床前",   "value": "preclinical"},
    {"label": "I 期",     "value": "phase_1"},
    {"label": "I/II 期",  "value": "phase_1_2"},
    {"label": "II 期",    "value": "phase_2"},
    {"label": "IIb 期",   "value": "phase_2b"},
    {"label": "III 期",   "value": "phase_3"},
    {"label": "已上市",   "value": "commercial"},
]

STATUS_OPTIONS = [
    {"label": "进行中", "value": "active"},
    {"label": "暂停",   "value": "paused"},
    {"label": "已终止", "value": "discontinued"},
]

PROGRAM_TYPE_OPTIONS = [
    {"label": "治疗性",   "value": "therapeutic"},
    {"label": "诊断性",   "value": "diagnostic"},
    {"label": "平台技术", "value": "platform"},
    {"label": "研究",     "value": "research"},
]

# ============================================================
# ★ 中英文映射字典
# ============================================================
STAGE_MAP = {opt["value"]: opt["label"] for opt in STAGE_OPTIONS}
STATUS_MAP = {
    "active": "🟢 进行中",
    "paused": "🟡 暂停",
    "discontinued": "🔴 已终止",
}
MODALITY_MAP = {
    "natural_phage": "🦠 天然噬菌体",
    "engineered_phage": "🧬 工程化噬菌体",
    "cocktail": "🧪 鸡尾酒",
    "software": "💻 软件/算法",
    "platform": "⚙️ 平台技术",
}

# 表格列定义修改
COLUMNS = [
    {"field": "id", "headerName": "项目 ID", "width": 180,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "name", "headerName": "项目名称", "flex": 2},
    {"field": "org_name", "headerName": "所属组织", "width": 180},
    {"field": "stage_cn", "headerName": "阶段", "width": 110},
    {"field": "status_cn", "headerName": "状态", "width": 110},
    {"field": "modality_cn", "headerName": "模态", "width": 150},
    {"field": "pathogens", "headerName": "靶向病原", "flex": 1},
    # ★ 新增操作列
    {"field": "actions", "headerName": "操作", "width": 110,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]

layout = html.Div([
    html.Div(id="dp-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("开发项目", className="page-title"),
            html.Div("管理所有 DevelopmentProgram · 靶向病原 · 研发阶段",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-dp-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新建项目"],
                        id="btn-dp-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="dp-search", type="text", debounce=True, value="",
                  placeholder="搜索项目名或组织名…", className="filter-search"),
        dcc.Dropdown(id="dp-stage-filter",
                     options=[{"label": "全部阶段", "value": ""}] + STAGE_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        dcc.Dropdown(id="dp-status-filter",
                     options=[{"label": "全部状态", "value": ""}] + STATUS_OPTIONS,
                     value="", clearable=False, style={"width": "140px"}),
        html.Div(id="dp-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="dp-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    # 新建项目表单
    dbc.Offcanvas(
        id="dp-offcanvas", title="新建开发项目",
        placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("项目名称 *", width=3),
                     dbc.Col(dbc.Input(id="dp-form-name"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("所属组织 ID *", width=3),
                     dbc.Col(dbc.Input(id="dp-form-org",
                                       placeholder="CI:ORG:XXXXXXXX"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("项目类型", width=3),
                     dbc.Col(dbc.Select(id="dp-form-type",
                                        options=PROGRAM_TYPE_OPTIONS,
                                        value="therapeutic"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("研发阶段", width=3),
                     dbc.Col(dbc.Select(id="dp-form-stage",
                                        options=STAGE_OPTIONS,
                                        value="discovery"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("模态", width=3),
                     dbc.Col(dbc.Input(id="dp-form-modality",
                                       placeholder="如：engineered_phage / cocktail"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("靶向病原", width=3),
                     dbc.Col(dbc.Input(id="dp-form-pathogens",
                                       placeholder="如：Klebsiella pneumoniae, Staphylococcus aureus"), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-dp-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-dp-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="dp-form-feedback", className="mt-3"),
        ])]),

    # ★ 新增：修改状态弹窗
    dcc.Store(id="store-active-program"),
    dbc.Modal(
        id="modal-dp-status", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("修改项目状态")),
            dbc.ModalBody([
                html.Div(id="dp-status-info", style={"marginBottom": "20px", "background": "#F8FAFC", "padding": "16px", "borderRadius": "8px"}),
                dbc.Row([
                    dbc.Label("新状态", width=3),
                    dbc.Col(dbc.Select(id="dp-status-select", options=STATUS_OPTIONS, value="active"), width=9)
                ])
            ]),
            dbc.ModalFooter([
                html.Button("取消", id="btn-dp-status-cancel", className="btn-outline-custom me-2"),
                html.Button("确认修改", id="btn-dp-status-save", className="btn-primary-custom"),
            ]),
        ]
    )
])


# ============================================================
# 列表加载与中文化
# ============================================================
@callback(
    Output("dp-grid", "rowData"),
    Output("dp-count-label", "children"),
    Output("dp-error-banner", "children"),
    Input("btn-dp-refresh", "n_clicks"),
    Input("dp-search", "value"),
    Input("dp-stage-filter", "value"),
    Input("dp-status-filter", "value"),
    Input("btn-dp-status-save", "n_clicks"), # 修改状态后刷新
)
def cb_load(_, search, stage, status, __):
    try:
        rows = list_programs(keyword=search or "", stage=stage or "", status=status or "")
        
        for r in rows:
            # 展平病原体列表
            if isinstance(r.get("pathogens"), list):
                r["pathogens"] = ", ".join(r["pathogens"]) if r["pathogens"] else ""
            
            # 映射中文字段
            st = r.get("stage", "")
            stat = r.get("status", "")
            mod = r.get("modality", "")
            
            r["stage_cn"] = STAGE_MAP.get(st, st)
            r["status_cn"] = STATUS_MAP.get(stat, stat)
            r["modality_cn"] = MODALITY_MAP.get(mod, mod)
            
            # 注入操作文字
            r["actions"] = "⚙️ 修改"
            
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("dp-offcanvas", "is_open"),
    Input("btn-dp-new", "n_clicks"),
    Input("btn-dp-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-dp-new"


@callback(
    Output("dp-form-feedback", "children"),
    Output("dp-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-dp-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-dp-save", "n_clicks"),
    State("dp-form-name", "value"),
    State("dp-form-org", "value"),
    State("dp-form-type", "value"),
    State("dp-form-stage", "value"),
    State("dp-form-modality", "value"),
    State("dp-form-pathogens", "value"),
    prevent_initial_call=True,
)
def cb_save(_, name, org_id, ptype, stage, modality, pathogens):
    if not name or not (org_id or "").strip():
        return dbc.Alert("项目名称和组织 ID 不能为空", color="danger"), no_update, no_update
    try:
        pathogen_list = [x.strip() for x in (pathogens or "").split(",") if x.strip()]
        prog_id = add_program(
            organization_id=org_id.strip(),
            canonical_name=name,
            program_type=ptype,
            development_stage=stage,
            modality=modality or None,
            target_pathogen_species=pathogen_list,
        )
        return dbc.Alert(f"已创建 {prog_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update


# ============================================================
# ★ 修改项目状态逻辑
# ============================================================
# 1. 点击表格操作列，打开弹窗
@callback(
    Output("store-active-program", "data"),
    Output("modal-dp-status", "is_open"),
    Output("dp-status-info", "children"),
    Output("dp-status-select", "value"),
    Input("dp-grid", "cellClicked"),
    State("dp-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_status_modal(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update, no_update

    row = row_data[rowIndex]
    prog_id = row["id"]
    name = row.get("name", "未知项目")
    current_status = row.get("status", "active")

    info_ui = [
        html.Div([html.Span("项目名称: ", style={"fontWeight": "600"}), html.Span(name)], className="mb-2"),
        html.Div([html.Span("当前状态: ", style={"fontWeight": "600"}), html.Span(STATUS_MAP.get(current_status, current_status))])
    ]
    
    return prog_id, True, info_ui, current_status


# 2. 保存修改
@callback(
    Output("modal-dp-status", "is_open", allow_duplicate=True),
    Output("btn-dp-refresh", "n_clicks", allow_duplicate=True),
    Output("dp-error-banner", "children", allow_duplicate=True),
    Input("btn-dp-status-save", "n_clicks"),
    Input("btn-dp-status-cancel", "n_clicks"),
    State("store-active-program", "data"),
    State("dp-status-select", "value"),
    prevent_initial_call=True,
)
def cb_save_status(save_n, cancel_n, prog_id, new_status):
    trigger = ctx.triggered_id
    if trigger == "btn-dp-status-cancel" or not prog_id:
        return False, no_update, no_update

    try:
        with get_driver().session() as s:
            s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                SET d.program_status = $status, d.updated_at = datetime()
            """, pid=prog_id, status=new_status)
            
        msg = dbc.Alert(f"项目 {prog_id} 状态已更新为【{STATUS_MAP.get(new_status)}】", color="success", dismissable=True, duration=3000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"修改失败：{e}", color="danger", dismissable=True)