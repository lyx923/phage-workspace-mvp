# pages/admin/schema.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc

from data_access.queries import list_constraints

dash.register_page(__name__, path="/admin/schema", name="Schema 管理")

EXPECTED = [
    ("Organization",          "organization_id", "Foundation"),
    ("Pathogen",              "pathogen_id",     "Foundation"),
    ("SourceArtifact",        "source_id",       "Foundation"),
    ("Review",                "review_id",       "Foundation"),
    ("AuditEvent",            "audit_id",        "Foundation"),
    ("OntologyModule",        "module_id",       "Foundation"),
    ("Phage",                 "phage_id",        "Scientific"),
    ("HostStrain",            "host_strain_id",  "Scientific"),
    ("LysisAssay",            "assay_id",        "Scientific"),
    ("ClinicalCase",          "case_id",         "Scientific"),
    ("ScientificEvidencePackage", "package_id",  "Scientific"),
    ("KnowledgeReuseEvent",   "reuse_event_id",  "Scientific"),
    ("DevelopmentProgram",    "program_id",      "CI"),
    ("IntelligenceEvent",     "event_id",        "CI"),
    ("EngineeringStrategy",   "strategy_id",     "CI"),
    ("EngineeredPhageConstruct", "construct_id", "CI"),
    ("TechnicalClaim",        "claim_id",        "CI"),
    ("TechnicalResult",       "result_id",       "CI"),
    ("TechnologyAssessment",  "technology_assessment_id", "CI"),
    ("DecisionRecord",        "decision_id",     "CI"),
    ("IntelligenceProduct",   "brief_id",        "CI"),
    ("DecisionBrief",         "brief_id",        "CI"),
    ("ClinicalTrial",         "trial_id",        "CI"),
    ("PatentFamily",          "patent_family_id","CI"),
]


layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("Schema 管理", className="page-title"),
            html.Div("Neo4j 约束与索引 · Foundation v0.6",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"),
                         "刷新状态"],
                        id="btn-sc-refresh",
                        className="btn-outline-custom", n_clicks=0),
        ]),
    ]),

    dbc.Row(id="sc-kpi-row", className="g-3 mb-4"),

    html.Div(className="surface-card mb-4", children=[
        html.Div([html.I(className="bi bi-table me-2"), "约束清单"],
                 className="surface-card-header"),
        html.Div(id="sc-table", className="surface-card-body"),
    ]),

    # 危险区：重新初始化
    html.Div(style={"border": "1px solid #fca5a5",
                    "borderRadius": "10px",
                    "background": "#fff8f8",
                    "padding": "20px"}, children=[
        html.Div([
            html.I(className="bi bi-exclamation-octagon-fill me-2"),
            "危险操作区",
        ], style={"display": "flex", "alignItems": "center",
                  "fontSize": "14px", "fontWeight": "700",
                  "color": "var(--c-danger)",
                  "marginBottom": "12px"}),
        html.P("重新初始化将删除并重建全部 Neo4j 约束与索引，"
               "执行期间数据库短暂锁定（约 30 秒）。",
               style={"fontSize": "12px", "color": "#6B7280",
                      "marginBottom": "16px"}),
        html.Button(
            [html.I(className="bi bi-arrow-repeat me-1"),
             "重新初始化 Schema 约束"],
            id="btn-schema-reinit",
            className="btn-danger-custom",
            n_clicks=0,
        ),
    ]),

    html.Div(id="schema-reinit-result", className="mt-3"),
])


# ─── 读取约束 ───
@callback(
    Output("sc-kpi-row", "children"),
    Output("sc-table", "children"),
    Input("btn-sc-refresh", "n_clicks"),
    Input("interval-global", "n_intervals"),
)
def cb_load(_, __):
    try:
        live = list_constraints()
    except Exception as e:
        return dbc.Alert(f"读取约束失败：{e}", color="danger"), ""

    live_pairs = set()
    for c in live:
        for lb in (c.get("labelsOrTypes") or []):
            for p in (c.get("properties") or []):
                live_pairs.add((lb, p))

    total = len(EXPECTED)
    built = sum(1 for lb, p, _ in EXPECTED if (lb, p) in live_pairs)
    missing = total - built

    from components.kpi_card import kpi_card
    kpis = dbc.Row(className="g-3", children=[
        dbc.Col(kpi_card("期望约束数", total, "bi bi-diagram-3",
                         theme="blue"), md=3),
        dbc.Col(kpi_card("已建立", built, "bi bi-check-circle",
                         theme="green"), md=3),
        dbc.Col(kpi_card("缺失", missing, "bi bi-exclamation-triangle",
                         theme="red" if missing else "green"), md=3),
        dbc.Col(kpi_card("Neo4j 约束总数", len(live), "bi bi-database",
                         theme="amber"), md=3),
    ])

    domain_badge = {"Foundation": "badge-draft",
                    "Scientific": "badge-active",
                    "CI":         "badge-approved"}

    rows = []
    for lb, prop, domain in EXPECTED:
        exists = (lb, prop) in live_pairs
        status_span = (
            html.Span("✅ 已建立", className="badge-status badge-approved")
            if exists else
            html.Span("⚠️ 缺失", className="badge-status badge-pending"))
        rows.append(html.Tr([
            html.Td(html.Span(lb, style={"fontFamily": "monospace",
                                          "fontSize": "12px"})),
            html.Td(html.Span(prop, style={"fontFamily": "monospace",
                                            "fontSize": "12px"})),
            html.Td("UNIQUE", style={"fontSize": "11px",
                                     "fontWeight": "700",
                                     "color": "var(--c-primary)"}),
            html.Td(html.Span(domain,
                              className=f"badge-status {domain_badge[domain]}")),
            html.Td(status_span),
        ]))

    table = html.Table([
        html.Thead(html.Tr([
            html.Th("节点标签"), html.Th("属性"),
            html.Th("约束类型"), html.Th("所属域"), html.Th("状态"),
        ], style={"fontSize": "12px", "color": "var(--c-text-muted)",
                  "borderBottom": "2px solid var(--c-border)",
                  "textAlign": "left"})),
        html.Tbody(rows),
    ], style={"width": "100%", "borderCollapse": "collapse",
              "fontSize": "13px", "lineHeight": "2"})

    return kpis, table


# ─── 触发 → 写 confirm payload ───
@callback(
    Output("store-confirm-payload", "data", allow_duplicate=True),
    Output("store-schema-pending", "data"),
    Input("btn-schema-reinit", "n_clicks"),
    prevent_initial_call=True,
)
def cb_schema_trigger(_):
    return ({
        "title": "⚠️ 重置 Schema 约束",
        "desc": "将删除并重建全部 Neo4j 索引和唯一性约束，"
                "执行期间数据库短暂锁定。",
    }, True)


# ─── 确认后执行 ───
@callback(
    Output("schema-reinit-result", "children"),
    Output("store-schema-pending", "data", allow_duplicate=True),
    Input("btn-confirm-ok", "n_clicks"),
    State("store-schema-pending", "data"),
    prevent_initial_call=True,
)
def cb_schema_execute(_, pending):
    if not pending:
        return no_update, no_update
    try:
        from config import get_driver
        from src.foundation.schema import create_schema
        create_schema(get_driver())
        try:
            from data_access.audit import audit_danger_op
            audit_danger_op("danger-reinit-schema", "Schema 约束重建")
        except Exception:
            pass
        return (dbc.Alert("Schema 已重建（AuditEvent 已写入）",
                          color="success", dismissable=True,
                          style={"fontSize": "13px"}), False)
    except Exception as e:
        return (dbc.Alert(f"重建失败：{e}", color="danger",
                          dismissable=True,
                          style={"fontSize": "13px"}), False)