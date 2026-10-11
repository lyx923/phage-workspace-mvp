# pages/ci/events.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_intelligence_events
from data_access.mutations import add_event

dash.register_page(__name__, path="/ci/events", name="情报事件")

EVENT_TYPE_OPTIONS = [
    {"label": "管线更新", "value": "pipeline_update"},
    {"label": "临床试验更新", "value": "clinical_trial_update"},
    {"label": "监管事件", "value": "regulatory_update"},
    {"label": "论文发表", "value": "publication"},
    {"label": "专利事件", "value": "patent_event"},
    {"label": "合作事件", "value": "partnership"},
    {"label": "融资事件", "value": "funding"},
    {"label": "并购事件", "value": "acquisition"},
]

COLUMNS = [
    {"field": "id", "headerName": "事件 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "title", "headerName": "标题", "flex": 2},
    {"field": "event_type", "headerName": "类型", "width": 160},
    {"field": "org_name", "headerName": "归因组织", "width": 200},
    {"field": "event_date", "headerName": "日期", "width": 120, "sort": "desc"},
    {"field": "source_id", "headerName": "来源 SRC", "width": 160,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
]

layout = html.Div([
    html.Div(id="ie-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("情报事件", className="page-title"),
            html.Div("管理所有 IntelligenceEvent · 归因组织 · SourceArtifact 溯源",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ie-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增事件"],
                        id="btn-ie-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ie-search", type="text", debounce=True, value="",
                  placeholder="搜索 ID、标题或组织名…", className="filter-search"),
        dcc.Dropdown(id="ie-type-filter",
                     options=[{"label": "全部类型", "value": ""}] + EVENT_TYPE_OPTIONS,
                     value="", clearable=False, style={"width": "180px"}),
        html.Div(id="ie-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="ie-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    dbc.Offcanvas(
        id="ie-offcanvas", title="新增情报事件",
        placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("标题 *", width=3),
                     dbc.Col(dbc.Input(id="ie-form-title"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("事件类型", width=3),
                     dbc.Col(dbc.Select(id="ie-form-type",
                                        options=EVENT_TYPE_OPTIONS,
                                        value="publication"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("组织 ID *", width=3),
                     dbc.Col(dbc.Input(id="ie-form-org",
                                       placeholder="CI:ORG:XXXXXXXX"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("事件日期", width=3),
                     dbc.Col(dbc.Input(id="ie-form-date", type="date"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("来源 URL", width=3),
                     dbc.Col(dbc.Input(id="ie-form-src-url"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("摘要", width=3),
                     dbc.Col(dbc.Textarea(id="ie-form-summary", rows=4), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-ie-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-ie-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ie-form-feedback", className="mt-3"),
        ])]),
])


@callback(
    Output("ie-grid", "rowData"),
    Output("ie-count-label", "children"),
    Output("ie-error-banner", "children"),
    Input("btn-ie-refresh", "n_clicks"),
    Input("ie-search", "value"),
    Input("ie-type-filter", "value"),
)
def cb_load(_, search, etype):
    try:
        rows = list_intelligence_events(keyword=search or "", event_type=etype or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("ie-offcanvas", "is_open"),
    Input("btn-ie-new", "n_clicks"),
    Input("btn-ie-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    from dash import ctx
    return ctx.triggered_id == "btn-ie-new"


@callback(
    Output("ie-form-feedback", "children"),
    Output("ie-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ie-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ie-save", "n_clicks"),
    State("ie-form-title", "value"),
    State("ie-form-type", "value"),
    State("ie-form-org", "value"),
    State("ie-form-date", "value"),
    State("ie-form-src-url", "value"),
    State("ie-form-summary", "value"),
    prevent_initial_call=True,
)
def cb_save(_, title, etype, org_id, event_date, src_url, summary):
    if not title or not (org_id or "").strip():
        return dbc.Alert("标题和组织 ID 不能为空", color="danger"), no_update, no_update
    try:
        event_id = add_event(
            event_type=etype, title=title,
            factual_summary=summary or "",
            organization_id=org_id.strip(),
            event_date=event_date, source_url=src_url,
        )
        return dbc.Alert(f"已创建 {event_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update