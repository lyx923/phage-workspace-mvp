# pages/admin/schema_registry.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag
from config import get_driver
import os
import re
from pathlib import Path

dash.register_page(__name__, path="/admin/schema-registry", name="Schema版本")

# ============================================================
# 1. 迁移配置项
# ============================================================
MIGRATIONS = [
    {
        "version": "1.0.0",
        "description": "初始 Foundation 基础节点与约束",
        "up": [
            "CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE",
            "CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:ClinicalCase) REQUIRE c.case_id IS UNIQUE",
            "CREATE CONSTRAINT phage_id_unique IF NOT EXISTS FOR (p:Phage) REQUIRE p.phage_id IS UNIQUE",
        ]
    },
    {
        "version": "2.0.0",
        "description": "v0.7-EXP 实验集成扩展（酶基因/批次/生物膜）",
        "up": [
            "CREATE CONSTRAINT enzyme_id_unique IF NOT EXISTS FOR (e:EnzymeGene) REQUIRE e.id IS UNIQUE",
            "CREATE CONSTRAINT batch_id_unique IF NOT EXISTS FOR (b:ExperimentBatch) REQUIRE b.id IS UNIQUE",
            "CREATE CONSTRAINT biofilm_id_unique IF NOT EXISTS FOR (b:BiofilmAssay) REQUIRE b.id IS UNIQUE",
            "CREATE INDEX phage_engineered_idx IF NOT EXISTS FOR (p:Phage) ON (p.is_engineered)",
            "MATCH (p:Phage) WHERE p.is_engineered IS NULL SET p.is_engineered = false, p.regulatory_status = 'research_only'"
        ]
    },
    {
        "version": "0.8.0",
        "description": "v0.8-EXP 清理与基线修复",
        "up": [
            "DROP CONSTRAINT interaction_id_unique IF EXISTS",
            "CREATE INDEX IF NOT EXISTS FOR (a:AuditEvent) ON (a.reason)"
        ]
    }
]

def get_applied_versions() -> set:
    try:
        with get_driver().session() as session:
            result = session.run("MATCH (s:SchemaVersion) RETURN s.version AS v")
            return {record["v"] for record in result}
    except Exception:
        return set()

# ============================================================
# 2. 页面布局
# ============================================================
COLUMNS = [
    {"field": "version", "headerName": "版本", "width": 120, "cellStyle": {"fontWeight": "bold"}},
    {"field": "applied_at", "headerName": "应用时间", "width": 180},
    {"field": "description", "headerName": "描述", "flex": 1},
    {"field": "reversible", "headerName": "可回滚", "width": 100},
    {"field": "status", "headerName": "健康状态", "width": 180, 
     "cellStyle": {"fontWeight": "bold", "fontSize": "12px", "cursor": "pointer", "color": "var(--c-primary)", "textDecoration": "underline"}},
    {"field": "actions", "headerName": "操作", "width": 120, "sortable": False, "filter": False, 
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "textAlign": "center", "fontWeight": "bold"}},
]

layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("Schema 版本管理", className="page-title"),
            html.Div("追踪数据模型迭代历史 · 运行健康检查", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-cloud-arrow-up me-1"), "执行增量迁移"], id="btn-sr-migrate", className="btn-primary-custom me-2"),
            html.Button([html.I(className="bi bi-code-square me-1"), "代码一致性检查"], id="btn-sr-code-check", className="btn-outline-custom me-2"),
            html.Button([html.I(className="bi bi-activity me-1"), "一键全局检查"], id="btn-sr-check-all", className="btn-outline-custom"),
        ]),
    ]),
    html.Div(id="sr-migrate-result", className="mb-3"),
    html.Div(id="sr-code-check-result", className="mb-3"), # 用于显示代码检查结果
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="sr-grid", columnDefs=COLUMNS, rowData=[], 
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"}, 
            style={"height": None, "minHeight": "300px"}
        ),
    ]),

    dbc.Offcanvas(
        id="sr-detail-drawer",
        title="迁移详情",
        placement="end",
        is_open=False,
        style={"width": "600px"},
        children=[html.Div(id="sr-detail-content")]
    )
])

# ============================================================
# 3. 回调逻辑
# ============================================================
def _fetch_rows():
    with get_driver().session() as s:
        rows = [dict(r) for r in s.run("MATCH (s:SchemaVersion) RETURN s.version AS version, toString(s.applied_at) AS applied_at, s.description AS description, s.reversible AS reversible ORDER BY s.applied_at DESC")]
        for r in rows:
            if r.get("applied_at"): r["applied_at"] = r["applied_at"].replace("T", " ")[:19]
            r["reversible"] = "是" if r.get("reversible") else "否"
            if "status" not in r:
                r["status"] = "🔍 点击检查"
            r["actions"] = "🔍 查看语句"
        return rows

@callback(Output("sr-grid", "rowData"), Input("btn-sr-migrate", "n_clicks"))
def load_schema(_):
    try:
        return _fetch_rows()
    except Exception: 
        return []

# 执行增量迁移
@callback(
    Output("sr-migrate-result", "children"),
    Output("sr-grid", "rowData", allow_duplicate=True),
    Input("btn-sr-migrate", "n_clicks"),
    prevent_initial_call=True,
)
def run_migration(n):
    if not n: return no_update, no_update
    driver = get_driver()
    applied_versions = get_applied_versions()
    newly_applied = []

    try:
        for m in MIGRATIONS:
            if m["version"] not in applied_versions:
                with driver.session() as session:
                    for stmt in m["up"]: session.run(stmt)
                    session.run("""
                        MERGE (v:SchemaVersion {version: $ver})
                        SET v.applied_at = datetime(), v.description = $desc, v.reversible = true
                    """, ver=m["version"], desc=m["description"])
                newly_applied.append(m["version"])
        
        if not newly_applied:
            alert = dbc.Alert("所有已知迁移均已应用，数据库处于最新状态。", color="info", dismissable=True)
        else:
            alert = dbc.Alert(f"成功应用了 {len(newly_applied)} 个增量迁移：{', '.join(newly_applied)}", color="success", dismissable=True)
        return alert, _fetch_rows()
    except Exception as e:
        return dbc.Alert(f"迁移失败: {str(e)}", color="danger", dismissable=True), no_update

# 单行点击检查
@callback(
    Output("sr-grid", "rowData", allow_duplicate=True),
    Input("sr-grid", "cellClicked"),
    State("sr-grid", "rowData"),
    prevent_initial_call=True,
)
def check_single_version(cell, row_data):
    if not cell or cell.get("colId") != "status": return no_update
    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or rowIndex >= len(row_data): return no_update
    row = row_data[rowIndex]
    if "✅" in row.get("status", ""): return no_update
    _check_version_status(row["version"], row, get_driver())
    return row_data

# 一键全局检查（只查未通过的）
@callback(
    Output("sr-grid", "rowData", allow_duplicate=True),
    Input("btn-sr-check-all", "n_clicks"),
    State("sr-grid", "rowData"),
    prevent_initial_call=True,
)
def check_all_versions(n, row_data):
    if not n or not row_data: return no_update
    driver = get_driver()
    for row in row_data:
        if "✅" not in row.get("status", ""):
            _check_version_status(row["version"], row, driver)
    return row_data

# 内部核心检查函数
def _check_version_status(ver, row, driver):
    missing = []
    with driver.session() as s:
        def has_constraint(label, prop):
            q = "SHOW CONSTRAINTS YIELD labelsOrTypes, properties WHERE $label IN labelsOrTypes AND $prop IN properties"
            return len(s.run(q, label=label, prop=prop).data()) > 0
        def has_index(label, prop):
            q = "SHOW INDEXES YIELD labelsOrTypes, properties WHERE $label IN labelsOrTypes AND $prop IN properties"
            return len(s.run(q, label=label, prop=prop).data()) > 0
            
        if ver == "1.0.0":
            if not has_constraint("Pathogen", "pathogen_id"): missing.append("Pathogen ID 约束")
            if not has_constraint("ClinicalCase", "case_id"): missing.append("Case ID 约束")
            if not has_constraint("Phage", "phage_id"): missing.append("Phage ID 约束")
        elif ver == "2.0.0":
            if not has_constraint("EnzymeGene", "id"): missing.append("EnzymeGene 约束")
            if not has_constraint("ExperimentBatch", "id"): missing.append("Batch 约束")
            if not has_constraint("BiofilmAssay", "id"): missing.append("Biofilm 约束")
            if not has_index("Phage", "is_engineered"): missing.append("Phage 索引")
        elif ver == "0.8.0":
            if has_constraint("PhageHostInteraction", "interaction_id"): missing.append("废弃约束未清理")
            if not has_index("AuditEvent", "reason"): missing.append("AuditEvent 索引")
                
    row["status"] = f"❌ 异常 ({len(missing)}项缺失)" if missing else "✅ 健康"

# ★ 新增：代码一致性检查（R-11）集成
@callback(
    Output("sr-code-check-result", "children"),
    Input("btn-sr-code-check", "n_clicks"),
    prevent_initial_call=True,
)
def run_code_consistency_check(n):
    if not n: return no_update

    ROOT = Path(".").resolve()
    SRC_DIR = ROOT / "src"
    PAGES_DIR = ROOT / "pages"

    def _iter_py_files(*dirs):
        for d in dirs:
            if not d.exists(): continue
            for p in d.rglob("*.py"):
                if any(part.startswith(".") for part in p.parts): continue
                yield p

    def _search_term(term):
        hits = 0
        for p in _iter_py_files(SRC_DIR, PAGES_DIR):
            try:
                if term in p.read_text(encoding="utf-8"): hits += 1
            except: pass
        return hits

    V2_NODES = ["EnzymeGene", "ExperimentBatch", "BiofilmAssay", "SchemaVersion"]
    V2_RELATIONS = ["ENGINEERED_FROM", "DISPLAYS", "DEGRADES", "BELONGS_TO_BATCH", "PRECEDED_BY"]
    PHAGE_V2_FIELDS = ["is_engineered", "engineering_status", "engineering_method", "parent_phage_id", "regulatory_status"]
    ENZYME_V2_FIELDS = ["gene_symbol", "enzyme_class", "target_polysaccharide", "specific_activity", "activity_assay_date", "sequence_verified", "expression_vector", "purification_method"]

    results = []
    def check_list(title, terms):
        for t in terms:
            hits = _search_term(t)
            if hits > 0:
                results.append(html.Li([html.Span("✅ ", style={"color": "green"}), f"{t}: 命中 {hits} 个文件"]))
            else:
                results.append(html.Li([html.Span("❌ ", style={"color": "red"}), f"{t}: 零命中 (请确认是否已废弃或未实现)"]))

    check_list("v2 节点", V2_NODES)
    check_list("v2 关系", V2_RELATIONS)
    check_list("Phage 字段", PHAGE_V2_FIELDS)
    check_list("Enzyme 字段", ENZYME_V2_FIELDS)

    return dbc.Alert([
        html.H6([html.I(className="bi bi-search me-2"), "代码一致性检查报告 (v2 语法扫描)"], style={"fontWeight": "700"}),
        html.Div("扫描了 src/ 和 pages/ 目录，检查代码中是否真实使用了声明的节点、关系和字段：", style={"fontSize": "12px", "marginBottom": "10px"}),
        html.Ul(results, style={"listStyle": "none", "paddingLeft": 0, "marginBottom": 0, "fontSize": "13px", "fontFamily": "monospace", "columns": "2"})
    ], color="info", dismissable=True)

# 点击操作列展示迁移详情
@callback(
    Output("sr-detail-drawer", "is_open"),
    Output("sr-detail-content", "children"),
    Input("sr-grid", "cellClicked"),
    State("sr-grid", "rowData"),
    prevent_initial_call=True,
)
def show_migration_detail(cell, row_data):
    if not cell or cell.get("colId") != "actions": return no_update, no_update
    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or rowIndex >= len(row_data): return no_update, no_update
    
    row = row_data[rowIndex]
    version = row["version"]
    mig = next((m for m in MIGRATIONS if m["version"] == version), None)
    if not mig: return True, dbc.Alert(f"未找到版本 {version} 的定义。", color="warning")
        
    content = [
        html.H5(f"版本: {version}", style={"color": "var(--c-primary)", "fontWeight": "bold", "marginBottom": "8px"}),
        html.Div(f"描述: {mig['description']}", style={"fontSize": "14px", "color": "var(--c-text-secondary)", "marginBottom": "20px"}),
    ]
    if "❌" in row.get("status", ""):
        content.append(dbc.Alert("⚠️ 当前版本存在缺失项，请尝试重新执行增量迁移补全。", color="warning", style={"fontSize": "13px"}))
        
    content.extend([
        html.Hr(),
        html.H6([html.I(className="bi bi-code-slash me-2"), "执行的 Cypher 语句："], style={"fontWeight": "600", "marginBottom": "16px"}),
    ])
    for i, stmt in enumerate(mig["up"]):
        content.append(
            html.Div([
                html.Div(f"Step {i+1}", style={"fontSize": "11px", "color": "var(--c-text-muted)", "marginBottom": "4px", "fontWeight": "600"}),
                html.Pre(stmt, style={
                    "background": "var(--c-bg)", "padding": "12px", "borderRadius": "6px", 
                    "fontSize": "12px", "overflowX": "auto", "border": "1px solid var(--c-border)",
                    "fontFamily": "Consolas, monospace", "whiteSpace": "pre-wrap", "wordBreak": "break-all"
                })
            ], style={"marginBottom": "16px"})
        )
    return True, content