# pages/ci/tech_assessment.py
import dash
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_tech_assessments

dash.register_page(__name__, path="/ci/tech-assessment", name="技术评估")

COLUMNS = [
    {"field": "id", "headerName": "评估 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "subject_type", "headerName": "评估对象类型", "width": 130},
    {"field": "subject_id", "headerName": "被评估对象 ID", "width": 220,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "evidence_maturity", "headerName": "证据成熟度", "width": 130},
    {"field": "technical_relevance", "headerName": "技术相关性", "width": 110},
    {"field": "translational_potential", "headerName": "转化潜力", "width": 110},
    {"field": "summary", "headerName": "评估摘要", "flex": 2},
]

layout = html.Div([
    html.Div(id="ta-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("技术评估", className="page-title"),
            html.Div("管理所有 TechnologyAssessment · 六维评估",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ta-refresh", className="btn-outline-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ta-search", type="text", debounce=True, value="",
                  placeholder="搜索对象 ID…", className="filter-search"),
        html.Div(id="ta-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="ta-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),
    html.Div(
        "💡 技术评估为只读视图。新建评估请通过后端服务或 Notebook 完成。",
        style={"marginTop": "16px", "fontSize": "12px",
               "color": "var(--c-text-muted)", "textAlign": "center"},
    ),
])


@callback(
    Output("ta-grid", "rowData"),
    Output("ta-count-label", "children"),
    Output("ta-error-banner", "children"),
    Input("btn-ta-refresh", "n_clicks"),
    Input("ta-search", "value"),
)
def cb_load(_, search):
    try:
        rows = list_tech_assessments(keyword=search or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")