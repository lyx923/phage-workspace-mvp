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
            checks = []
            
            # 1. 检查核心节点
            core_nodes = [
                "EnzymeGene", "ExperimentBatch", "BiofilmAssay", "KnowledgeReuseEvent",
                "Phage", "HostStrain", "LysisAssay", "ClinicalCase", 
                "ScientificEvidencePackage", "Organization", "DevelopmentProgram", 
                "IntelligenceEvent", "EngineeringStrategy", "EngineeredPhageConstruct", 
                "DecisionRecord", "IntelligenceProduct", "Pathogen", "SourceArtifact", 
                "Review", "AuditEvent", "OntologyModule"
            ]
            missing_nodes = []
            for n in core_nodes:
                res = s.run(f"MATCH (n:{n}) RETURN count(n) AS c").single()
                if not res or res["c"] == 0: 
                    missing_nodes.append(n)
            
            node_ok = len(missing_nodes) == 0
            checks.append(("核心节点存在性", node_ok, f"共检查 {len(core_nodes)} 个节点，缺失: {missing_nodes}" if missing_nodes else f"共 {len(core_nodes)} 个节点全部存在"))
            
            # 2. 检查 v0.7 关系类型
            rels = ["ENGINEERED_FROM", "DISPLAYS", "BELONGS_TO_BATCH", "PRECEDED_BY"]
            missing_rels = []
            for r in rels:
                res = s.run(f"MATCH ()-[r:{r}]->() RETURN count(r) AS c").single()
                if not res or res["c"] == 0: 
                    missing_rels.append(r)
            
            rel_ok = len(missing_rels) == 0
            checks.append(("v0.7 关系类型", rel_ok, f"缺失: {missing_rels}" if missing_rels else "全部存在"))
            
            # 3. 检查 SchemaVersion
            res = s.run("MATCH (s:SchemaVersion) RETURN count(s) AS c").single()
            sv_ok = res["c"] > 0
            checks.append(("SchemaVersion 节点", sv_ok, "正常" if sv_ok else "缺失 (请重新初始化)"))
            
            # 4. 检查关键约束/索引
            constraints = s.run("SHOW CONSTRAINTS").data()
            has_enzyme = any("EnzymeGene" in (c.get("labelsOrTypes") or []) and "id" in (c.get("properties") or []) for c in constraints)
            has_batch = any("ExperimentBatch" in (c.get("labelsOrTypes") or []) and "id" in (c.get("properties") or []) for c in constraints)
            has_biofilm = any("BiofilmAssay" in (c.get("labelsOrTypes") or []) and "id" in (c.get("properties") or []) for c in constraints)
            
            indexes = s.run("SHOW INDEXES").data()
            has_phage_idx = any("Phage" in (i.get("labelsOrTypes") or []) and "is_engineered" in (i.get("properties") or []) for i in indexes)
            
            missing_idx = []
            if not has_enzyme: missing_idx.append("EnzymeGene(id)")
            if not has_batch: missing_idx.append("ExperimentBatch(id)")
            if not has_biofilm: missing_idx.append("BiofilmAssay(id)")
            if not has_phage_idx: missing_idx.append("Phage(is_engineered)")
            
            idx_ok = len(missing_idx) == 0
            checks.append(("v0.7 关键索引/约束", idx_ok, f"缺失: {missing_idx}" if missing_idx else "全部存在"))

            # 渲染 UI
            items = []
            all_ok = True
            for name, ok, msg in checks:
                if not ok: all_ok = False
                icon = "✅" if ok else "❌"
                color = "success" if ok else "danger"
                items.append(html.Li([
                    html.Span(f"{icon} {name}：", style={"fontWeight": "600", "color": f"var(--c-{color})"}),
                    html.Span(msg, style={"fontSize": "13px"})
                ], style={"marginBottom": "8px"}))
                
            alert_color = "success" if all_ok else "warning"
            header_msg = "🎉 所有检查项均通过！" if all_ok else "⚠️ 部分检查项未通过，请检查数据库"
            
            return dbc.Alert([
                html.H6(header_msg, style={"fontWeight": "700", "marginBottom": "12px"}),
                html.Ul(items, style={"listStyle": "none", "paddingLeft": 0, "marginBottom": 0})
            ], color=alert_color)
            
    except Exception as e:
        return dbc.Alert(f"健康检查执行失败: {e}", color="danger")