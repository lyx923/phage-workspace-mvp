# pages/scientific/clinical_cases.py
import dash
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_clinical_cases

dash.register_page(__name__, path="/scientific/clinical-cases", name="临床病例")

OUTCOME_OPTIONS = [
    {"label": "治愈",  "value": "cured"},
    {"label": "好转",  "value": "improved"},
    {"label": "未愈",  "value": "unchanged"},
]

COLUMNS = [
    {"field": "id", "headerName": "病例 ID", "width": 140,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "infection_type", "headerName": "感染类型", "width": 130},
    {"field": "pathogen_species", "headerName": "病原物种", "flex": 1},
    {"field": "host_strain", "headerName": "宿主菌株", "width": 160},
    {"field": "phage_treatment", "headerName": "噬菌体治疗", "flex": 1},
    {"field": "clinical_outcome", "headerName": "临床结局", "flex": 1},
]

layout = html.Div([
    html.Div(id="cc-error-banner"),

    # 合规声明
    html.Div(
        [html.I(className="bi bi-shield-lock-fill me-2"),
         "所有病例数据已通过去标识化处理，不含 PHI/PII，仅限沙箱环境使用。"],
        style={"background": "#EFF6FF", "color": "#1E40AF",
               "border": "1px solid #BFDBFE", "borderRadius": "8px",
               "padding": "12px 16px", "marginBottom": "16px",
               "fontSize": "13px"},
    ),

    html.Div(className="page-header", children=[
        html.Div([
            html.Div("临床病例", className="page-title"),
            html.Div("管理所有 ClinicalCase · 感染类型 · 治疗结局",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-cc-refresh", className="btn-outline-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="cc-search", type="text", debounce=True, value="",
                  placeholder="搜索病例 ID 或病原物种…", className="filter-search"),
        dcc.Dropdown(id="cc-outcome-filter",
                     options=[{"label": "全部结局", "value": ""}] + OUTCOME_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        html.Div(id="cc-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="cc-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 20,
                "domLayout": "autoHeight",
            },
            style={"height": None, "minHeight": "500px"},
        ),
    ]),
])


@callback(
    Output("cc-grid", "rowData"),
    Output("cc-count-label", "children"),
    Output("cc-error-banner", "children"),
    Input("btn-cc-refresh", "n_clicks"),
    Input("cc-search", "value"),
    Input("cc-outcome-filter", "value"),
)
def cb_load(_, search, outcome):
    try:
        rows = list_clinical_cases(keyword=search or "", outcome=outcome or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")