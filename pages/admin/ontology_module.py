# pages/admin/ontology_module.py
import dash
from dash import html, dcc, Input, Output, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_ontology_modules

dash.register_page(__name__, path="/admin/ontology-module", name="Ontology")


PRESET_MODULES = [
    {"id": "OM-FOUNDATION-001", "module_name": "Foundation 基础模块",
     "domain": "Foundation", "version": "0.6", "status": "active",
     "owner_team": "Platform",
     "node_types": ["Pathogen", "Organization", "SourceArtifact",
                    "Review", "AuditEvent", "OntologyModule"]},
    {"id": "OM-SCIENTIFIC-001", "module_name": "Scientific 科学域模块",
     "domain": "Scientific", "version": "0.6", "status": "active",
     "owner_team": "Scientific",
     "node_types": ["Phage", "HostStrain", "LysisAssay",
                    "ClinicalCase", "ScientificEvidencePackage",
                    "KnowledgeReuseEvent"]},
    {"id": "OM-CI-001", "module_name": "CI 竞争情报模块",
     "domain": "CI", "version": "0.6", "status": "active",
     "owner_team": "CI",
     "node_types": ["Organization", "DevelopmentProgram",
                    "IntelligenceEvent", "EngineeringStrategy",
                    "EngineeredPhageConstruct", "TechnologyAssessment",
                    "DecisionRecord", "IntelligenceProduct"]},
    {"id": "OM-IPD-001", "module_name": "IPD 产品开发模块",
     "domain": "IPD", "version": "0.1", "status": "pending",
     "owner_team": "Product", "node_types": []},
]


COLUMNS = [
    {"field": "module_name", "headerName": "模块名", "flex": 1},
    {"field": "version",     "headerName": "版本",   "width": 100},
    {"field": "status",      "headerName": "状态",   "width": 130},
    {"field": "owner_team",  "headerName": "负责团队", "width": 180},
    {"field": "id",          "headerName": "模块 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
]


layout = html.Div([
    html.Div(id="om-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("Ontology 模块", className="page-title"),
            html.Div("已注册的 OntologyModule · 版本与依赖关系",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"),
                         "刷新"],
                        id="btn-om-refresh",
                        className="btn-outline-custom", n_clicks=0),
            html.Button([html.I(className="bi bi-cloud-upload me-1"),
                         "同步预置模块"],
                        id="btn-om-sync",
                        className="btn-primary-custom", n_clicks=0),
        ]),
    ]),

    html.Div(id="om-sync-result", className="mb-3"),

    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="om-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={"pagination": True,
                             "paginationPageSize": 20,
                             "domLayout": "autoHeight"},
            style={"height": None, "minHeight": "400px"},
        ),
    ]),
])


@callback(
    Output("om-grid", "rowData"),
    Output("om-error-banner", "children"),
    Input("btn-om-refresh", "n_clicks"),
    Input("interval-global", "n_intervals"),
)
def cb_load(_, __):
    try:
        rows = list_ontology_modules()
        return rows, None
    except Exception as e:
        return [], dbc.Alert(f"Neo4j 连接失败：{e}",
                              color="danger", className="mb-3")


@callback(
    Output("om-sync-result", "children"),
    Output("btn-om-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-om-sync", "n_clicks"),
    prevent_initial_call=True,
)
def cb_om_sync(_):
    from datetime import datetime
    ts = datetime.now().isoformat()
    synced = []
    try:
        from config import get_driver
        with get_driver().session() as s:
            for m in PRESET_MODULES:
                s.run("""
                    MERGE (om:OntologyModule {module_id: $id})
                    SET om.module_name = $name,
                        om.domain = $domain,
                        om.version = $version,
                        om.status = $status,
                        om.owner_team = $owner,
                        om.node_types = $node_types,
                        om.updated_at = $ts
                """, id=m["id"], name=m["module_name"],
                     domain=m["domain"], version=m["version"],
                     status=m["status"], owner=m["owner_team"],
                     node_types=m["node_types"], ts=ts)
                synced.append(m["id"])
        try:
            from data_access.audit import audit
            audit("MIGRATION", "OntologyModule", "sync",
                  delta={"synced": synced},
                  reason=f"同步预置模块：{', '.join(synced)}")
        except Exception:
            pass
        return (dbc.Alert(
            [html.I(className="bi bi-check-circle-fill me-2"),
             f"已同步 {len(synced)} 个模块：{', '.join(synced)}"],
            color="success", dismissable=True,
            style={"fontSize": "13px"}), 1)
    except Exception as e:
        return (dbc.Alert(f"同步失败：{e}", color="danger",
                          dismissable=True,
                          style={"fontSize": "13px"}), 0)