# pages/ci/decision_records.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_decision_records
from data_access.mutations import add_decision_record

dash.register_page(__name__, path="/ci/decision-records", name="决策记录")

DECISION_TYPE_OPTIONS = [
    {"label": "监控",       "value": "monitor"},
    {"label": "评估",       "value": "evaluate"},
    {"label": "合作",       "value": "partner"},
    {"label": "降低优先级", "value": "deprioritize"},
    {"label": "IP 审查",    "value": "IP_review"},
]

COLUMNS = [
    {"field": "id", "headerName": "决策 ID", "width": 180,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "decision_type", "headerName": "类型", "width": 120},
    {"field": "summary", "headerName": "决策摘要", "flex": 2},
    {"field": "owner", "headerName": "负责人", "width": 130},
    {"field": "brief_id", "headerName": "基于简报", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "outcome_status", "headerName": "结果", "width": 110},
]

layout = html.Div([
    html.Div(id="dr-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("决策记录", className="page-title"),
            html.Div("管理所有 DecisionRecord · 基于 IntelligenceProduct",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-dr-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "记录决策"],
                        id="btn-dr-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="dr-search", type="text", debounce=True, value="",
                  placeholder="搜索决策摘要…", className="filter-search"),
        dcc.Dropdown(id="dr-type-filter",
                     options=[{"label": "全部类型", "value": ""}] + DECISION_TYPE_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        html.Div(id="dr-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="dr-grid", columnDefs=COLUMNS, rowData=[],
                   dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                   style={"height": None, "minHeight": "420px"}),
    ]),

    dbc.Offcanvas(
        id="dr-offcanvas", title="记录决策",
        placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("简报 ID *", width=3),
                     dbc.Col(dbc.Input(id="dr-form-brief",
                                       placeholder="CI:BRIEF:XXXXXXXX"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("决策类型", width=3),
                     dbc.Col(dbc.Select(id="dr-form-type",
                                        options=DECISION_TYPE_OPTIONS,
                                        value="monitor"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("决策摘要 *", width=3),
                     dbc.Col(dbc.Textarea(id="dr-form-summary", rows=3), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("决策理由 *", width=3),
                     dbc.Col(dbc.Textarea(id="dr-form-rationale", rows=3), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("决策人 *", width=3),
                     dbc.Col(dbc.Input(id="dr-form-owner",
                                       value="VP_Strategy"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("复盘日期", width=3),
                     dbc.Col(dbc.Input(id="dr-form-review-date",
                                       type="date"), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-dr-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-dr-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="dr-form-feedback", className="mt-3"),
        ])]),
])


@callback(
    Output("dr-grid", "rowData"),
    Output("dr-count-label", "children"),
    Output("dr-error-banner", "children"),
    Input("btn-dr-refresh", "n_clicks"),
    Input("dr-search", "value"),
    Input("dr-type-filter", "value"),
)
def cb_load(_, search, dtype):
    try:
        rows = list_decision_records(keyword=search or "", decision_type=dtype or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


@callback(
    Output("dr-offcanvas", "is_open"),
    Input("btn-dr-new", "n_clicks"),
    Input("btn-dr-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    from dash import ctx
    return ctx.triggered_id == "btn-dr-new"


@callback(
    Output("dr-form-feedback", "children"),
    Output("dr-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-dr-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-dr-save", "n_clicks"),
    State("dr-form-brief", "value"),
    State("dr-form-type", "value"),
    State("dr-form-summary", "value"),
    State("dr-form-rationale", "value"),
    State("dr-form-owner", "value"),
    State("dr-form-review-date", "value"),
    prevent_initial_call=True,
)
def cb_save(_, brief_id, dtype, summary, rationale, owner, review_date):
    if not (brief_id or "").strip() or not (summary or "").strip():
        return dbc.Alert("简报 ID 和决策摘要不能为空", color="danger"), no_update, no_update
    try:
        dec_id = add_decision_record(
            brief_id=brief_id.strip(),
            decision_type=dtype,
            decision_summary=summary.strip(),
            rationale=(rationale or "").strip(),
            decision_owner=(owner or "VP_Strategy").strip(),
            review_date=review_date or None,
        )
        return dbc.Alert(f"已创建 {dec_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update