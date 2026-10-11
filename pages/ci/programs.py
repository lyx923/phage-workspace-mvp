# pages/ci/programs.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_programs
from data_access.mutations import add_program

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

COLUMNS = [
    {"field": "id", "headerName": "项目 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "name", "headerName": "项目名称", "flex": 2},
    {"field": "org_name", "headerName": "所属组织", "width": 200},
    {"field": "stage", "headerName": "阶段", "width": 130},
    {"field": "status", "headerName": "状态", "width": 100},
    {"field": "modality", "headerName": "模态", "width": 130},
    {"field": "pathogens", "headerName": "靶向病原", "flex": 1},
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
])


@callback(
    Output("dp-grid", "rowData"),
    Output("dp-count-label", "children"),
    Output("dp-error-banner", "children"),
    Input("btn-dp-refresh", "n_clicks"),
    Input("dp-search", "value"),
    Input("dp-stage-filter", "value"),
    Input("dp-status-filter", "value"),
)
def cb_load(_, search, stage, status):
    try:
        rows = list_programs(keyword=search or "", stage=stage or "", status=status or "")
        # pathogens 是 list，展平成字符串
        for r in rows:
            if isinstance(r.get("pathogens"), list):
                r["pathogens"] = ", ".join(r["pathogens"]) if r["pathogens"] else ""
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
    from dash import ctx
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