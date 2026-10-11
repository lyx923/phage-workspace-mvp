# pages/scientific/lysis_assay.py
import dash
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_lysis_assays

dash.register_page(__name__, path="/scientific/lysis-assay", name="裂解实验")

RESULT_OPTIONS = [
    {"label": "阳性（Lytic）",     "value": "Lytic"},
    {"label": "阴性（Non-lytic）", "value": "Non-lytic"},
]

# ★ 关键修复：长文本列用 flex，短文本列保留 width
COLUMNS = [
    {"field": "id", "headerName": "实验 ID",
     "width": 320, "minWidth": 240,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "phage_name", "headerName": "噬菌体",
     "flex": 1, "minWidth": 130},
    {"field": "host_label", "headerName": "宿主菌株",
     "flex": 1, "minWidth": 130},
    {"field": "result", "headerName": "结果",
     "width": 100, "minWidth": 90},
    {"field": "result_value", "headerName": "数值",
     "width": 90, "minWidth": 80},
    {"field": "evidence_level", "headerName": "证据等级",
     "width": 110, "minWidth": 100},
    {"field": "qc_status", "headerName": "QC",
     "width": 100, "minWidth": 90},
]

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
                "paginationPageSizeSelector": [10, 20, 50, 100],  # ★ 分页大小选项
                "domLayout": "autoHeight",
            },
            style={"height": None, "width": "100%", "minHeight": "500px"},
        ),
    ]),
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
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")