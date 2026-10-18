# pages/ci/decision_records.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
import json

from data_access.queries import list_decision_records, _run
from data_access.mutations import add_decision_record
from config import get_driver

dash.register_page(__name__, path="/ci/decision-records", name="决策记录")

DECISION_TYPE_OPTIONS = [
    {"label": "监控",       "value": "monitor"},
    {"label": "评估",       "value": "evaluate"},
    {"label": "合作",       "value": "partner"},
    {"label": "降低优先级", "value": "deprioritize"},
    {"label": "IP 审查",    "value": "IP_review"},
]

OUTCOME_OPTIONS = [
    {"label": "⏳ 待定 (pending)", "value": "pending"},
    {"label": "✅ 成功 (successful)", "value": "successful"},
    {"label": "❌ 失败 (unsuccessful)", "value": "unsuccessful"},
    {"label": "🤔 部分成功 (mixed)", "value": "mixed"},
]

TYPE_MAP = {
    "monitor": "👀 监控",
    "evaluate": "🔍 评估",
    "partner": "🤝 合作",
    "deprioritize": "📉 降级",
    "IP_review": "⚖️ IP审查"
}

OUTCOME_MAP = {
    "pending": "⏳ 待定",
    "successful": "✅ 成功",
    "unsuccessful": "❌ 失败",
    "mixed": "🤔 部分成功"
}

COLUMNS = [
    {"field": "id", "headerName": "决策 ID", "width": 160,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "type_cn", "headerName": "类型", "width": 120},
    {"field": "summary", "headerName": "决策摘要", "flex": 2},
    {"field": "owner", "headerName": "负责人", "width": 120},
    # 这列现在可以点击了
    {"field": "brief_id", "headerName": "基于简报", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px", "color": "var(--c-primary)", "cursor": "pointer", "textDecoration": "underline"}},
    {"field": "outcome_cn", "headerName": "结果", "width": 120},
    {"field": "actions", "headerName": "复盘", "width": 100,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]


def _get_org_options():
    try:
        rows = _run("MATCH (o:Organization) RETURN o.organization_id AS id, o.canonical_name AS name ORDER BY name")
        return [{"label": r["name"], "value": r["id"]} for r in rows]
    except Exception:
        return []


layout = html.Div([
    html.Div(id="dr-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("决策记录", className="page-title"),
            html.Div("管理所有 DecisionRecord · 基于情报简报的决策闭环",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-dr-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-magic me-1"), "生成简报并决策"],
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

    # 智能录入表单
    dbc.Offcanvas(
        id="dr-offcanvas", title="生成简报并记录决策",
        placement="end", is_open=False, style={"width": "650px"},
        children=[
            html.Div(id="dr-step-1", children=[
                html.H6("第一步：选择竞争对手生成简报", style={"fontWeight": "600", "marginBottom": "16px"}),
                dbc.Row([
                    dbc.Col([dcc.Dropdown(id="dr-form-org", placeholder="请选择要分析的组织", options=_get_org_options())], width=8),
                    dbc.Col([html.Button([html.I(className="bi bi-search me-1"), "提取情报"], id="btn-dr-analyze", className="btn-primary-custom w-100")], width=4)
                ], className="mb-4"),
            ]),
            html.Div(id="dr-step-2", style={"display": "none"}, children=[
                html.Hr(),
                html.Div(id="dr-brief-content", style={"background": "#F8FAFC", "padding": "20px", "borderRadius": "8px", "border": "1px solid #E2E8F0", "marginBottom": "24px", "maxHeight": "400px", "overflowY": "auto"}),
                html.H6("第二步：填写决策内容", style={"fontWeight": "600", "marginBottom": "16px"}),
                dbc.Form([
                    dbc.Row([dbc.Label("决策类型", width=3), dbc.Col(dbc.Select(id="dr-form-type", options=DECISION_TYPE_OPTIONS, value="monitor"), width=9)], className="mb-3"),
                    dbc.Row([dbc.Label("决策摘要 *", width=3), dbc.Col(dbc.Textarea(id="dr-form-summary", rows=3, placeholder="如：将该组织列入重点监控名单..."), width=9)], className="mb-3"),
                    dbc.Row([dbc.Label("决策理由 *", width=3), dbc.Col(dbc.Textarea(id="dr-form-rationale", rows=2, value="基于最新竞争情报简报分析。"), width=9)], className="mb-3"),
                    dbc.Row([dbc.Label("决策人 *", width=3), dbc.Col(dbc.Input(id="dr-form-owner", value="VP_Strategy"), width=9)], className="mb-4"),
                    html.Div([html.Button([html.I(className="bi bi-check2-circle me-1"), "确认保存决策"], id="btn-dr-save", className="btn-primary-custom w-100")]),
                    html.Div(id="dr-form-feedback", className="mt-3"),
                ])
            ]),
            dcc.Store(id="store-dr-brief-id")
        ]),
        
    # 复盘抽屉
    dcc.Store(id="store-review-decision-id"),
    dbc.Offcanvas(
        id="dr-review-offcanvas", title="复盘决策结果", placement="end", is_open=False, style={"width": "400px"},
        children=[
            html.Div(id="dr-review-info", style={"marginBottom": "20px", "background": "#F8FAFC", "padding": "16px", "borderRadius": "8px"}),
            dbc.Form([
                dbc.Row([dbc.Label("修改结果", width=4), dbc.Col(dbc.Select(id="dr-review-outcome", options=OUTCOME_OPTIONS, value="pending"), width=8)], className="mb-4"),
                html.Button([html.I(className="bi bi-check2-circle me-1"), "保存复盘结果"], id="btn-dr-review-save", className="btn-primary-custom w-100"),
                html.Div(id="dr-review-feedback", className="mt-3")
            ])
        ]
    ),

    # 查看简报抽屉
    dbc.Offcanvas(
        id="dr-view-brief", title="原始简报内容", placement="end", is_open=False, style={"width": "600px"},
        children=[html.Div(id="dr-view-brief-content")]
    )
])


@callback(
    Output("dr-grid", "rowData"),
    Output("dr-count-label", "children"),
    Output("dr-error-banner", "children"),
    Input("btn-dr-refresh", "n_clicks"),
    Input("dr-search", "value"),
    Input("dr-type-filter", "value"),
    Input("btn-dr-save", "n_clicks"),
    Input("btn-dr-review-save", "n_clicks"),
)
def cb_load(_, search, dtype, __, ___):
    try:
        rows = list_decision_records(keyword=search or "", decision_type=dtype or "")
        for r in rows:
            r["type_cn"] = TYPE_MAP.get(r.get("decision_type", ""), r.get("decision_type", ""))
            r["outcome_cn"] = OUTCOME_MAP.get(r.get("outcome_status", ""), r.get("outcome_status", ""))
            r["actions"] = "👉 复盘"
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}", color="danger", className="mb-3")


@callback(
    Output("dr-offcanvas", "is_open"),
    Output("dr-step-1", "style"),
    Output("dr-step-2", "style"),
    Output("store-dr-brief-id", "data"),
    Input("btn-dr-new", "n_clicks"),
    prevent_initial_call=True,
)
def cb_open_offcanvas(new_n):
    return True, {"display": "block"}, {"display": "none"}, None


@callback(
    Output("dr-brief-content", "children"),
    Output("store-dr-brief-id", "data"),
    Output("dr-step-2", "style"),
    Input("btn-dr-analyze", "n_clicks"),
    State("dr-form-org", "value"),
    prevent_initial_call=True,
)
def cb_analyze_org(n, org_id):
    if not org_id:
        return dbc.Alert("请先选择组织", color="warning"), None, {"display": "none"}

    try:
        from src.ci.competitor_brief import generate_competitor_brief
        brief = generate_competitor_brief(get_driver(), org_id, days_back=365, persist=True)
        if "error" in brief:
            return dbc.Alert(f"生成失败：{brief['error']}", color="danger"), None, {"display": "none"}

        ca = brief.get("competitive_assessment", {})
        threats = [t.get("signal_text") for t in ca.get("threats", [])]
        opps = [o.get("signal_text") for o in ca.get("opportunities", [])]
        uncertainties = [u.get("signal_text") for u in ca.get("uncertainties", [])]
        next_steps = brief.get("recommended_next_steps", [])
        org = brief.get("organization", {})

        ui = [
            html.H4(org.get("name"), style={"marginBottom": "8px"}),
            html.Div([dbc.Badge(f"类型: {org.get('type') or '未知'}", color="info", className="me-2"),
                      dbc.Badge(f"国家: {org.get('country') or '未知'}", color="secondary")], className="mb-4"),
            html.H6([html.I(className="bi bi-exclamation-triangle me-2 text-danger"), "威胁 (Threats)"], style={"fontWeight": "600"}),
            html.Ul([html.Li(t) for t in threats] if threats else [html.Li("暂无明确威胁")], style={"fontSize": "13px", "marginBottom": "20px"}),
            html.H6([html.I(className="bi bi-lightbulb me-2 text-success"), "机会 (Opportunities)"], style={"fontWeight": "600"}),
            html.Ul([html.Li(o) for o in opps] if opps else [html.Li("暂无明确机会")], style={"fontSize": "13px", "marginBottom": "20px"}),
            html.H6([html.I(className="bi bi-question-circle me-2 text-warning"), "不确定性 (Uncertainties)"], style={"fontWeight": "600"}),
            html.Ul([html.Li(u) for u in uncertainties] if uncertainties else [html.Li("暂无")], style={"fontSize": "13px", "marginBottom": "20px"}),
            html.H6([html.I(className="bi bi-arrow-right-circle me-2 text-primary"), "建议下一步"], style={"fontWeight": "600"}),
            html.Ul([html.Li(s) for s in next_steps] if next_steps else [html.Li("暂无建议")], style={"fontSize": "13px"}),
        ]
        return ui, brief.get("brief_id"), {"display": "block"}
    except Exception as e:
        return dbc.Alert(f"系统异常：{e}", color="danger"), None, {"display": "none"}


@callback(
    Output("dr-form-feedback", "children"),
    Output("btn-dr-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-dr-save", "n_clicks"),
    State("store-dr-brief-id", "data"),
    State("dr-form-type", "value"),
    State("dr-form-summary", "value"),
    State("dr-form-rationale", "value"),
    State("dr-form-owner", "value"),
    prevent_initial_call=True,
)
def cb_save(_, brief_id, dtype, summary, rationale, owner):
    if not brief_id or not (summary or "").strip():
        return dbc.Alert("简报未生成或摘要为空", color="danger"), no_update
    try:
        dec_id = add_decision_record(
            brief_id=brief_id, decision_type=dtype, decision_summary=summary.strip(),
            rationale=(rationale or "").strip(), decision_owner=(owner or "VP_Strategy").strip(), review_date=None,
        )
        return dbc.Alert(f"已成功创建决策 {dec_id}", color="success"), 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update


@callback(
    Output("store-review-decision-id", "data"),
    Output("dr-review-offcanvas", "is_open"),
    Output("dr-review-info", "children"),
    Output("dr-review-outcome", "value"),
    Input("dr-grid", "cellClicked"),
    State("dr-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_review(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update, no_update

    row = row_data[rowIndex]
    dec_id = row["id"]
    summary = row.get("summary", "无摘要")
    current_outcome = row.get("outcome_status", "pending")

    info_ui = [
        html.Div([html.Span("决策 ID: ", style={"fontWeight": "600"}), html.Span(dec_id, style={"fontFamily": "monospace"})], className="mb-2"),
        html.Div([html.Span("决策摘要: ", style={"fontWeight": "600"}), html.Span(summary)], className="mb-2"),
        html.Div([html.Span("当前结果: ", style={"fontWeight": "600"}), html.Span(OUTCOME_MAP.get(current_outcome, current_outcome))])
    ]
    return dec_id, True, info_ui, current_outcome


@callback(
    Output("dr-review-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-dr-refresh", "n_clicks", allow_duplicate=True),
    Output("dr-review-feedback", "children"),
    Input("btn-dr-review-save", "n_clicks"),
    State("store-review-decision-id", "data"),
    State("dr-review-outcome", "value"),
    prevent_initial_call=True,
)
def cb_save_review(n, dec_id, new_outcome):
    if not dec_id or not new_outcome:
        return no_update, no_update, dbc.Alert("数据缺失", color="danger")
    try:
        with get_driver().session() as s:
            s.run("MATCH (dr:DecisionRecord {decision_id: $did}) SET dr.outcome_status = $status, dr.updated_at = datetime()", did=dec_id, status=new_outcome)
        return False, 1, dbc.Alert(f"复盘结果已更新为：{OUTCOME_MAP.get(new_outcome)}", color="success", dismissable=True, duration=3000)
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"修改失败：{e}", color="danger")


# ★ 新增：点击 brief_id 查看原始简报
@callback(
    Output("dr-view-brief", "is_open"),
    Output("dr-view-brief-content", "children"),
    Input("dr-grid", "cellClicked"),
    State("dr-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_view_brief(cell, row_data):
    if not cell or cell.get("colId") != "brief_id":
        return no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update

    brief_id = row_data[rowIndex].get("brief_id")
    if not brief_id:
        return False, "无关联简报"

    try:
        with get_driver().session() as s:
            row = s.run("""
                MATCH (b:IntelligenceProduct {brief_id: $bid})
                OPTIONAL MATCH (b)-[:COVERS]->(o:Organization)
                RETURN b.executive_summary AS summary, 
                       b.competitive_assessment AS ca, 
                       o.canonical_name AS org_name
            """, bid=brief_id).single()
            
        if not row:
            return True, dbc.Alert("数据库中未找到该简报。", color="warning")

        ca = {}
        if row.get("ca"):
            try:
                ca = json.loads(row["ca"]) if isinstance(row["ca"], str) else row["ca"]
            except:
                pass

        threats = [t.get("signal_text") for t in ca.get("threats", [])]
        opps = [o.get("signal_text") for o in ca.get("opportunities", [])]

        ui = [
            html.H5(f"简报: {brief_id}", style={"fontFamily": "monospace", "color": "var(--c-primary)"}),
            html.H6(f"关联组织: {row.get('org_name') or '未知'}", style={"marginBottom": "20px"}),
            html.H6([html.I(className="bi bi-stars me-2"), "执行摘要"]),
            html.Div(row.get("summary") or "无摘要", style={"background": "#F8FAFC", "padding": "12px", "borderRadius": "6px", "marginBottom": "20px", "fontSize": "13px"}),
            html.H6([html.I(className="bi bi-exclamation-triangle me-2 text-danger"), "威胁"]),
            html.Ul([html.Li(t) for t in threats] if threats else [html.Li("无")], style={"fontSize": "13px"}),
            html.H6([html.I(className="bi bi-lightbulb me-2 text-success"), "机会"]),
            html.Ul([html.Li(o) for o in opps] if opps else [html.Li("无")], style={"fontSize": "13px"}),
        ]
        return True, ui
    except Exception as e:
        return True, dbc.Alert(f"读取简报失败：{e}", color="danger")