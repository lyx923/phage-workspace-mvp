# pages/scientific/evidence_packages.py
import dash
from dash import html, dcc, Input, Output, callback
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_evidence_packages

dash.register_page(__name__, path="/scientific/evidence-packages", name="证据包")

STATUS_OPTIONS = [
    {"label": "草稿",   "value": "draft"},
    {"label": "已审核", "value": "approved"},
    {"label": "已拒绝", "value": "rejected"},
]

COLUMNS = [
    {"field": "id", "headerName": "包 ID", "width": 180,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "package_type", "headerName": "类型", "width": 160},
    {"field": "status", "headerName": "状态", "width": 110},
    {"field": "review_status", "headerName": "审核状态", "width": 110},
    {"field": "generated_by", "headerName": "生成者", "width": 140},
    {"field": "created_at", "headerName": "创建时间", "flex": 1},
]

layout = html.Div([
    html.Div(id="ep-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("证据包", className="page-title"),
            html.Div("管理所有 ScientificEvidencePackage · 证据组织与审核",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ep-refresh", className="btn-outline-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ep-search", type="text", debounce=True, value="",
                  placeholder="搜索包 ID…", className="filter-search"),
        dcc.Dropdown(id="ep-status-filter",
                     options=[{"label": "全部状态", "value": ""}] + STATUS_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        html.Div(id="ep-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="ep-grid", columnDefs=COLUMNS, rowData=[],
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
    Output("ep-grid", "rowData"),
    Output("ep-count-label", "children"),
    Output("ep-error-banner", "children"),
    Input("btn-ep-refresh", "n_clicks"),
    Input("ep-search", "value"),
    Input("ep-status-filter", "value"),
)
def cb_load(_, search, status):
    try:
        rows = list_evidence_packages(keyword=search or "", status=status or "")
        # created_at 是 neo4j DateTime，转字符串
        for r in rows:
            v = r.get("created_at")
            if v is not None:
                try:
                    if hasattr(v, "to_native"):
                        v = v.to_native()
                    if hasattr(v, "strftime"):
                        r["created_at"] = v.strftime("%Y-%m-%d %H:%M")
                    else:
                        r["created_at"] = str(v)[:19]
                except Exception:
                    r["created_at"] = str(v)
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")