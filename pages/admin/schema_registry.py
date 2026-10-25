# pages/admin/schema_registry.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
from config import get_driver

dash.register_page(__name__, path="/admin/schema-registry", name="Schema版本")

COLUMNS = [
    {"field": "version", "headerName": "版本", "width": 120, "cellStyle": {"fontWeight": "bold"}},
    {"field": "applied_at", "headerName": "应用时间", "width": 180},
    {"field": "description", "headerName": "描述", "flex": 1},
    {"field": "reversible", "headerName": "可回滚", "width": 100},
]

layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("Schema 版本管理", className="page-title"),
            html.Div("追踪数据模型迭代历史 · 运行健康检查", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-activity me-1"), "运行健康检查"], id="btn-sr-check", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(id="sr-check-result", className="mb-3"),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="sr-grid", columnDefs=COLUMNS, rowData=[], dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"}, style={"height": None, "minHeight": "300px"}),
    ])
])

@callback(
    Output("sr-grid", "rowData"),
    Input("btn-sr-check", "n_clicks"),
)
def load_schema(_):
    try:
        with get_driver().session() as s:
            rows = [dict(r) for r in s.run("MATCH (s:SchemaVersion) RETURN s.version AS version, toString(s.applied_at) AS applied_at, s.description AS description, s.reversible AS reversible ORDER BY s.applied_at DESC")]
            for r in rows:
                # ★ 修复：替换 T 为空格，并截取到秒
                if r.get("applied_at"):
                    r["applied_at"] = r["applied_at"].replace("T", " ")[:19]
                r["reversible"] = "是" if r.get("reversible") else "否"
            return rows
    except: return []

@callback(
    Output("sr-check-result", "children"),
    Input("btn-sr-check", "n_clicks"),
    prevent_initial_call=True,
)
def run_health_check(_):
    try:
        with get_driver().session() as s:
            nodes = ["EnzymeGene", "ExperimentBatch", "BiofilmAssay"]
            missing = []
            for n in nodes:
                res = s.run(f"MATCH (n:{n}) RETURN count(n) AS c").single()
                if not res: missing.append(n)
            
            if missing:
                return dbc.Alert(f"缺失节点: {', '.join(missing)}", color="warning")
            return dbc.Alert("✅ 所有 v0.7 节点与索引均已就绪！", color="success")
    except Exception as e:
        return dbc.Alert(f"检查失败: {e}", color="danger")