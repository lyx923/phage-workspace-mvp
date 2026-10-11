# pages/scientific/phage_library.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_phages
from data_access.audit import audit
from config import get_driver

dash.register_page(__name__, path="/scientific/phage-library", name="噬菌体库")

FAMILY_OPTIONS = [
    {"label": "Myoviridae",     "value": "Myoviridae"},
    {"label": "Siphoviridae",   "value": "Siphoviridae"},
    {"label": "Podoviridae",    "value": "Podoviridae"},
    {"label": "Microviridae",   "value": "Microviridae"},
    {"label": "Inoviridae",     "value": "Inoviridae"},
    {"label": "其他",           "value": "other"},
]

COLUMNS = [
    {"field": "id", "headerName": "噬菌体 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "name", "headerName": "名称", "flex": 1},
    {"field": "family", "headerName": "科", "width": 140},
    {"field": "receptor_target", "headerName": "受体靶点", "flex": 1},
]

layout = html.Div([
    html.Div(id="ph-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("噬菌体库", className="page-title"),
            html.Div("管理所有 Phage 节点 · 支持科属筛选与受体靶点检索",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ph-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "录入噬菌体"],
                        id="btn-ph-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ph-search", type="text", debounce=True, value="",
                  placeholder="搜索噬菌体名称或 ID…", className="filter-search"),
        dcc.Dropdown(id="ph-family-filter",
                     options=[{"label": "全部科", "value": ""}] + FAMILY_OPTIONS,
                     value="", clearable=False, style={"width": "180px"}),
        html.Div(id="ph-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="ph-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    dbc.Offcanvas(
        id="ph-offcanvas", title="录入噬菌体",
        placement="end", is_open=False, style={"width": "480px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("名称 *", width=3),
                     dbc.Col(dbc.Input(id="ph-form-name",
                                       placeholder="如 PKP014"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("科", width=3),
                     dbc.Col(dbc.Select(id="ph-form-family",
                                        options=FAMILY_OPTIONS,
                                        value="Myoviridae"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("受体靶点", width=3),
                     dbc.Col(dbc.Input(id="ph-form-receptor",
                                       placeholder="如 LPS / OmpA"), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-ph-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-ph-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ph-form-feedback", className="mt-3"),
        ])]),
])


@callback(
    Output("ph-grid", "rowData"),
    Output("ph-count-label", "children"),
    Output("ph-error-banner", "children"),
    Input("btn-ph-refresh", "n_clicks"),
    Input("ph-search", "value"),
    Input("ph-family-filter", "value"),
)
def cb_load(_, search, family):
    try:
        rows = list_phages(keyword=search or "", family=family or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("ph-offcanvas", "is_open"),
    Input("btn-ph-new", "n_clicks"),
    Input("btn-ph-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    from dash import ctx
    return ctx.triggered_id == "btn-ph-new"


@callback(
    Output("ph-form-feedback", "children"),
    Output("ph-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ph-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ph-save", "n_clicks"),
    State("ph-form-name", "value"),
    State("ph-form-family", "value"),
    State("ph-form-receptor", "value"),
    prevent_initial_call=True,
)
def cb_save(_, name, family, receptor):
    if not name or not name.strip():
        return dbc.Alert("名称不能为空", color="danger"), no_update, no_update
    try:
        import uuid
        phage_id = f"PHAGE-{name.strip()}"
        with get_driver().session() as s:
            s.run("""
                MERGE (p:Phage {phage_id: $pid})
                SET p.name = $name, p.family = $family,
                    p.receptor_target = $rec,
                    p.created_at = COALESCE(p.created_at, datetime())
            """, pid=phage_id, name=name.strip(),
                 family=family or "", rec=receptor or "")
        # 手动审计（Phage 没有 service，直接 audit）
        audit("CREATE", "Phage", phage_id,
              delta={"name": name, "family": family, "receptor": receptor},
              reason=f"录入噬菌体 {name}")
        return dbc.Alert(f"已创建 {phage_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update