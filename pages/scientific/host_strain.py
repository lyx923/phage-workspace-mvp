# pages/scientific/host_strain.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_host_strains
from data_access.audit import audit
from config import get_driver

dash.register_page(__name__, path="/scientific/host-strain", name="宿主菌株")

SPECIES_OPTIONS = [
    {"label": "Klebsiella pneumoniae",  "value": "Klebsiella pneumoniae"},
    {"label": "Escherichia coli",       "value": "Escherichia coli"},
    {"label": "Pseudomonas aeruginosa", "value": "Pseudomonas aeruginosa"},
    {"label": "Acinetobacter baumannii","value": "Acinetobacter baumannii"},
    {"label": "Staphylococcus aureus",  "value": "Staphylococcus aureus"},
]

COLUMNS = [
    {"field": "id", "headerName": "菌株 ID", "width": 260,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "label", "headerName": "菌株标签", "flex": 1},
    {"field": "species", "headerName": "物种", "flex": 1},
]

layout = html.Div([
    html.Div(id="hs-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("宿主菌株", className="page-title"),
            html.Div("管理所有 HostStrain · 关联病原物种",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-hs-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "录入菌株"],
                        id="btn-hs-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="hs-search", type="text", debounce=True, value="",
                  placeholder="搜索菌株标签…", className="filter-search"),
        dcc.Dropdown(id="hs-species-filter",
                     options=[{"label": "全部物种", "value": ""}] + SPECIES_OPTIONS,
                     value="", clearable=False, style={"width": "240px"}),
        html.Div(id="hs-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="hs-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    dbc.Offcanvas(
        id="hs-offcanvas", title="录入宿主菌株",
        placement="end", is_open=False, style={"width": "480px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("菌株标签 *", width=3),
                     dbc.Col(dbc.Input(id="hs-form-label",
                                       placeholder="如 B-KP11"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("物种 *", width=3),
                     dbc.Col(dbc.Select(id="hs-form-species",
                                        options=SPECIES_OPTIONS,
                                        value="Klebsiella pneumoniae"), width=9)],
                    className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-hs-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-hs-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="hs-form-feedback", className="mt-3"),
        ])]),
])


@callback(
    Output("hs-grid", "rowData"),
    Output("hs-count-label", "children"),
    Output("hs-error-banner", "children"),
    Input("btn-hs-refresh", "n_clicks"),
    Input("hs-search", "value"),
    Input("hs-species-filter", "value"),
)
def cb_load(_, search, species):
    try:
        rows = list_host_strains(keyword=search or "", species=species or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("hs-offcanvas", "is_open"),
    Input("btn-hs-new", "n_clicks"),
    Input("btn-hs-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    from dash import ctx
    return ctx.triggered_id == "btn-hs-new"


@callback(
    Output("hs-form-feedback", "children"),
    Output("hs-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-hs-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-hs-save", "n_clicks"),
    State("hs-form-label", "value"),
    State("hs-form-species", "value"),
    prevent_initial_call=True,
)
def cb_save(_, label, species):
    if not label or not label.strip():
        return dbc.Alert("菌株标签不能为空", color="danger"), no_update, no_update
    try:
        # HostStrain 没有专门的 service，直接用后端已有函数
        from src.shared.evidence_source import get_or_create_pathogen
        import uuid
        label = label.strip()
        host_strain_id = f"HS-{uuid.uuid4().hex[:8].upper()}"

        pathogen_id = get_or_create_pathogen(
            get_driver(), species=species, pathogen_type="bacteria",
            actor_id="dash_frontend",
        )

        with get_driver().session() as s:
            s.run("""
                MERGE (h:HostStrain {strain_label: $label})
                ON CREATE SET h.host_strain_id = $hid,
                              h.created_at = datetime()
                WITH h
                MATCH (p:Pathogen {pathogen_id: $pid})
                MERGE (h)-[:IS_STRAIN_OF]->(p)
            """, label=label, hid=host_strain_id, pid=pathogen_id)

        audit("CREATE", "HostStrain", host_strain_id,
              delta={"label": label, "species": species},
              reason=f"录入宿主菌株 {label}")
        return dbc.Alert(f"已创建 {label}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update