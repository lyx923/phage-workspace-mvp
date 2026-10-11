# pages/ci/strategies.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_strategies
from data_access.mutations import add_strategy

dash.register_page(__name__, path="/ci/strategies", name="工程策略")

STRATEGY_TYPE_OPTIONS = [
    {"label": "宿主范围扩展",   "value": "host_range_expansion"},
    {"label": "尾纤维工程",     "value": "tail_fiber_engineering"},
    {"label": "受体结合工程",   "value": "receptor_binding_engineering"},
    {"label": "裂解能力增强",   "value": "lysis_enhancement"},
    {"label": "溶原性去除",     "value": "lysogeny_removal"},
    {"label": "生物膜破坏",     "value": "biofilm_disruption"},
    {"label": "递送载荷",       "value": "payload_delivery"},
    {"label": "抗耐药载荷",     "value": "anti_resistance_payload"},
    {"label": "抗毒力载荷",     "value": "anti_virulence_payload"},
    {"label": "免疫调节",       "value": "immune_modulation"},
    {"label": "噬菌体展示",     "value": "phage_display"},
    {"label": "基因组精简",     "value": "genome_minimization"},
    {"label": "其他",           "value": "other"},
]

MATURITY_OPTIONS = [
    {"label": "概念阶段", "value": "conceptual"},
    {"label": "体外验证", "value": "in_vitro"},
    {"label": "体内验证", "value": "in_vivo"},
    {"label": "临床",     "value": "clinical"},
]

COLUMNS = [
    {"field": "id", "headerName": "策略 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "strategy_type", "headerName": "策略类型", "width": 200},
    {"field": "description", "headerName": "描述", "flex": 2},
    {"field": "evidence_maturity", "headerName": "证据成熟度", "width": 130},
    {"field": "construct_count", "headerName": "构建体数", "width": 100},
    {"field": "review_status", "headerName": "审核状态", "width": 110},
]

layout = html.Div([
    html.Div(id="st-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("工程策略", className="page-title"),
            html.Div("管理所有 EngineeringStrategy · 策略类型 · 证据成熟度",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-st-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新建策略"],
                        id="btn-st-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="st-search", type="text", debounce=True, value="",
                  placeholder="搜索策略类型…", className="filter-search"),
        dcc.Dropdown(id="st-type-filter",
                     options=[{"label": "全部类型", "value": ""}] + STRATEGY_TYPE_OPTIONS,
                     value="", clearable=False, style={"width": "200px"}),
        html.Div(id="st-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="st-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    dbc.Offcanvas(
        id="st-offcanvas", title="新建工程策略",
        placement="end", is_open=False, style={"width": "480px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("策略类型 *", width=3),
                     dbc.Col(dbc.Select(id="st-form-type",
                                        options=STRATEGY_TYPE_OPTIONS,
                                        value="host_range_expansion"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("证据成熟度", width=3),
                     dbc.Col(dbc.Select(id="st-form-maturity",
                                        options=MATURITY_OPTIONS,
                                        value="conceptual"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("描述", width=3),
                     dbc.Col(dbc.Textarea(id="st-form-desc", rows=4), width=9)],
                    className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-st-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-st-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="st-form-feedback", className="mt-3"),
        ])]),
])


@callback(
    Output("st-grid", "rowData"),
    Output("st-count-label", "children"),
    Output("st-error-banner", "children"),
    Input("btn-st-refresh", "n_clicks"),
    Input("st-search", "value"),
    Input("st-type-filter", "value"),
)
def cb_load(_, search, stype):
    try:
        rows = list_strategies(keyword=search or "", strategy_type=stype or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("st-offcanvas", "is_open"),
    Input("btn-st-new", "n_clicks"),
    Input("btn-st-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    from dash import ctx
    return ctx.triggered_id == "btn-st-new"


@callback(
    Output("st-form-feedback", "children"),
    Output("st-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-st-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-st-save", "n_clicks"),
    State("st-form-type", "value"),
    State("st-form-maturity", "value"),
    State("st-form-desc", "value"),
    prevent_initial_call=True,
)
def cb_save(_, stype, maturity, desc):
    if not stype:
        return dbc.Alert("策略类型不能为空", color="danger"), no_update, no_update
    try:
        sid = add_strategy(
            strategy_type=stype,
            description=desc or "",
            evidence_maturity=maturity,
        )
        return dbc.Alert(f"已创建/复用策略 {sid}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update