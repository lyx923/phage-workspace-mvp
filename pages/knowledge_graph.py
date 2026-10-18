# pages/knowledge_graph.py
import dash
import dash_cytoscape as cyto
from dash import (html, dcc, Input, Output, State,
                  callback, clientside_callback, no_update)
import dash_bootstrap_components as dbc

from data_access.queries import _run

cyto.load_extra_layouts()
dash.register_page(__name__, path="/knowledge-graph", name="知识图谱")

# ============================================================
# 节点配色
# ============================================================
NODE_COLORS = {
    "Phage":                    "#1B6CA8",
    "Pathogen":                 "#DC2626",
    "HostStrain":               "#0D9373",
    "LysisAssay":               "#8B5CF6",
    "ClinicalCase":             "#F59E0B",
    "ScientificEvidencePackage":"#0891B2",
    "KnowledgeReuseEvent":      "#EC4899",
    "IntelligenceEvent":        "#6366F1",
    "IntelligenceProduct":      "#7C3AED",
    "DecisionRecord":           "#D97706",
    "AuditEvent":               "#64748B",
    "Organization":             "#374151",
    "SourceArtifact":           "#94A3B8",
    "OntologyModule":           "#4B5563",
    "Review":                   "#8B5CF6",
    "EngineeringStrategy":      "#059669",
    "EngineeredPhageConstruct": "#0EA5E9",
}


# ============================================================
# 静态 Ontology 结构图
# ============================================================
ONTOLOGY_ELEMENTS = [
    # Foundation 层
    {"data": {"id": "Pathogen",       "label": "Pathogen",       "layer": "Foundation"}},
    {"data": {"id": "Organization",   "label": "Organization",   "layer": "Foundation"}},
    {"data": {"id": "SourceArtifact", "label": "SourceArtifact", "layer": "Foundation"}},
    {"data": {"id": "Review",         "label": "Review",         "layer": "Foundation"}},
    {"data": {"id": "AuditEvent",     "label": "AuditEvent",     "layer": "Foundation"}},
    {"data": {"id": "OntologyModule", "label": "OntologyModule", "layer": "Foundation"}},
    # Scientific 层
    {"data": {"id": "Phage",                     "label": "Phage",             "layer": "Scientific"}},
    {"data": {"id": "HostStrain",                "label": "HostStrain",        "layer": "Scientific"}},
    {"data": {"id": "LysisAssay",                "label": "LysisAssay",        "layer": "Scientific"}},
    {"data": {"id": "ClinicalCase",              "label": "ClinicalCase",      "layer": "Scientific"}},
    {"data": {"id": "ScientificEvidencePackage", "label": "EvidencePackage",   "layer": "Scientific"}},
    {"data": {"id": "KnowledgeReuseEvent",       "label": "KnowledgeReuseEvent","layer": "Scientific"}},
    # CI 层
    {"data": {"id": "DevelopmentProgram",       "label": "DevelopmentProgram",   "layer": "CI"}},
    {"data": {"id": "IntelligenceEvent",        "label": "IntelligenceEvent",    "layer": "CI"}},
    {"data": {"id": "EngineeringStrategy",      "label": "EngineeringStrategy",  "layer": "CI"}},
    {"data": {"id": "EngineeredPhageConstruct", "label": "Construct",            "layer": "CI"}},
    {"data": {"id": "IntelligenceProduct",      "label": "IntelligenceProduct",  "layer": "CI"}},
    {"data": {"id": "DecisionRecord",           "label": "DecisionRecord",       "layer": "CI"}},
    # 关系
    {"data": {"source": "Phage",                    "target": "LysisAssay",       "label": "USED_IN"}},
    {"data": {"source": "LysisAssay",               "target": "HostStrain",       "label": "TESTED_AGAINST"}},
    {"data": {"source": "HostStrain",               "target": "Pathogen",         "label": "IS_STRAIN_OF"}},
    {"data": {"source": "ClinicalCase",             "target": "Pathogen",         "label": "INVOLVES_PATHOGEN"}},
    {"data": {"source": "ClinicalCase",             "target": "Phage",            "label": "TREATED_WITH"}},
    {"data": {"source": "ScientificEvidencePackage","target": "LysisAssay",       "label": "USES_ASSAY"}},
    {"data": {"source": "ScientificEvidencePackage","target": "ClinicalCase",     "label": "REFERENCES_CASE"}},
    {"data": {"source": "KnowledgeReuseEvent",      "target": "ClinicalCase",     "label": "SOURCE_CASE"}},
    {"data": {"source": "KnowledgeReuseEvent",      "target": "ScientificEvidencePackage", "label": "TARGETS_PACKAGE"}},
    {"data": {"source": "Organization",             "target": "DevelopmentProgram","label": "DEVELOPS"}},
    {"data": {"source": "DevelopmentProgram",       "target": "Pathogen",         "label": "TARGETS_PATHOGEN"}},
    {"data": {"source": "DevelopmentProgram",       "target": "EngineeringStrategy","label": "USES_STRATEGY"}},
    {"data": {"source": "EngineeredPhageConstruct", "target": "EngineeringStrategy","label": "IMPLEMENTS"}},
    {"data": {"source": "EngineeredPhageConstruct", "target": "Pathogen",         "label": "TARGETS"}},
    {"data": {"source": "IntelligenceEvent",        "target": "Organization",     "label": "INVOLVES"}},
    {"data": {"source": "IntelligenceEvent",        "target": "SourceArtifact",   "label": "HAS_SOURCE"}},
    {"data": {"source": "DecisionRecord",           "target": "IntelligenceProduct","label": "BASED_ON"}},
]


def _build_stylesheet():
    styles = [
        {
            "selector": "node",
            "style": {
                "label": "data(label)",
                "font-size": "10px",
                "font-family": "Inter, PingFang SC, sans-serif",
                "font-weight": "600",
                "color": "#1E293B",
                "text-valign": "center",
                "text-halign": "center",
                "text-wrap": "wrap",
                "text-max-width": "70px",
                "width": "52px",
                "height": "52px",
                "border-width": "2px",
                "border-color": "#E2E8F0",
                "background-color": "#94A3B8",
            },
        },
        {
            "selector": "node:selected",
            "style": {
                "border-width": "3px",
                "border-color": "#1B6CA8",
                "box-shadow": "0 0 0 4px rgba(27,108,168,0.2)",
            },
        },
        {
            "selector": "edge",
            "style": {
                "width": 1.5,
                "line-color": "#CBD5E1",
                "target-arrow-color": "#CBD5E1",
                "target-arrow-shape": "triangle",
                "curve-style": "bezier",
                "label": "data(label)",
                "font-size": "8px",
                "color": "#94A3B8",
                "text-rotation": "autorotate",
                "text-background-color": "white",
                "text-background-opacity": 0.8,
                "text-background-padding": "2px",
            },
        },
        {
            "selector": "edge:selected",
            "style": {"line-color": "#1B6CA8",
                      "target-arrow-color": "#1B6CA8",
                      "width": 2.5},
        },
    ]
    for ntype, color in NODE_COLORS.items():
        styles.append({
            "selector": f'node[id="{ntype}"]',
            "style": {
                "background-color": color,
                "color": "#FFFFFF",
                "border-color": color,
            },
        })
    return styles


def _fetch_live_elements(view):
    """从 Neo4j 拉取实时图谱；不可达时返回静态。"""
    if view == "attribution":
        rows = _run("""
            MATCH (e:IntelligenceEvent)-[:INVOLVES]->(o:Organization)
            OPTIONAL MATCH (e)-[:HAS_SOURCE]->(s:SourceArtifact)
            OPTIONAL MATCH (b:IntelligenceProduct)-[:COVERS]->(o)
            OPTIONAL MATCH (d:DecisionRecord)-[:BASED_ON]->(b)
            RETURN e.event_id AS eid, e.title AS etitle, e.event_type AS etype,
                   o.organization_id AS oid, o.canonical_name AS oname,
                   s.source_id AS sid, s.title AS stitle,
                   b.brief_id AS bid, b.title AS btitle,
                   d.decision_id AS did, d.decision_summary AS dsummary
            LIMIT 40
        """)
    elif view == "reuse":
        rows = _run("""
            MATCH (k:KnowledgeReuseEvent)-[:SOURCE_CASE]->(c:ClinicalCase)
            OPTIONAL MATCH (k)-[:TARGETS_PACKAGE]->(p:ScientificEvidencePackage)
            RETURN k.reuse_event_id AS kid, k.reuse_type AS ktype,
                   c.case_id AS cid, c.infection_type AS ctype,
                   p.package_id AS pid
            LIMIT 40
        """)
    else:
        return ONTOLOGY_ELEMENTS

    nodes = {}
    edges = []

    def add_node(nid, label, layer):
        if nid and nid not in nodes:
            nodes[nid] = {"data": {"id": nid, "label": label or nid,
                                    "layer": layer}}

    def add_edge(a, b, rel):
        if a and b and a in nodes and b in nodes:
            edges.append({"data": {"source": a, "target": b, "label": rel}})

    if view == "attribution":
        for r in rows:
            add_node(r["eid"], r["etitle"], "IntelligenceEvent")
            add_node(r["oid"], r["oname"], "Organization")
            add_node(r["sid"], r["stitle"], "SourceArtifact")
            add_node(r["bid"], r["btitle"], "IntelligenceProduct")
            add_node(r["did"], (r["dsummary"] or "")[:30], "DecisionRecord")
        for r in rows:
            add_edge(r["eid"], r["oid"], "INVOLVES")
            add_edge(r["eid"], r["sid"], "HAS_SOURCE")
            add_edge(r["bid"], r["oid"], "COVERS")
            add_edge(r["did"], r["bid"], "BASED_ON")
    elif view == "reuse":
        for r in rows:
            add_node(r["kid"], r["ktype"], "KnowledgeReuseEvent")
            add_node(r["cid"], r["ctype"], "ClinicalCase")
            add_node(r["pid"], r["pid"], "ScientificEvidencePackage")
        for r in rows:
            add_edge(r["kid"], r["cid"], "SOURCE_CASE")
            add_edge(r["kid"], r["pid"], "TARGETS_PACKAGE")

    return list(nodes.values()) + edges


# ============================================================
# 页面骨架（移除了底部表格，全屏留给图谱）
# ============================================================
layout = html.Div([
    # 页头
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("知识图谱", className="page-title"),
            html.Div("Ontology 链路可视化 · 归因溯源 · 跨病例复用",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-fullscreen me-1"), "全屏"],
                        id="btn-kg-fullscreen",
                        className="btn-outline-custom", n_clicks=0),
            html.Button([html.I(className="bi bi-arrow-repeat me-1"),
                         "重新布局"],
                        id="btn-kg-relayout",
                        className="btn-outline-custom", n_clicks=0),
        ]),
    ]),

    # 工具栏
    html.Div(className="surface-card mb-3",
             style={"padding": "12px 16px"},
             children=[
        html.Div(style={"display": "flex", "alignItems": "center",
                        "gap": "16px", "flexWrap": "wrap"}, children=[
            dbc.RadioItems(
                id="kg-view-mode",
                options=[
                    {"label": " Ontology 结构图", "value": "ontology"},
                    {"label": " 归因溯源图",       "value": "attribution"},
                    {"label": " 跨病例复用图",     "value": "reuse"},
                ],
                value="ontology",
                inline=True,
                inputStyle={"marginRight": "4px"},
                labelStyle={"marginRight": "16px", "fontSize": "13px",
                            "cursor": "pointer"},
            ),
            html.Div(style={"flex": "1"}),
            html.Span("布局：", style={"fontSize": "13px",
                                       "color": "var(--c-text-secondary)"}),
            dcc.Dropdown(
                id="kg-layout-algo",
                options=[
                    {"label": "力导向 (cose)",       "value": "cose"},
                    {"label": "层次 (dagre)",        "value": "dagre"},
                    {"label": "同心圆 (concentric)", "value": "concentric"},
                    {"label": "网格 (grid)",         "value": "grid"},
                    {"label": "圆形 (circle)",       "value": "circle"},
                ],
                value="cose", clearable=False,
                style={"width": "200px", "fontSize": "13px"},
            ),
        ]),
    ]),

    dbc.Row(className="g-3", children=[
        dbc.Col(md=8, children=[
            html.Div(id="kg-cyto-wrap", className="surface-card",
                     children=[
                cyto.Cytoscape(
                    id="kg-cyto",
                    elements=ONTOLOGY_ELEMENTS,
                    stylesheet=_build_stylesheet(),
                    layout={"name": "cose", "animate": True,
                            "animationDuration": 500},
                    style={"width": "100%", "height": "720px",
                           "background": "#FAFBFC"},
                    minZoom=0.3, maxZoom=2.5,
                ),
            ]),
        ]),
        dbc.Col(md=4, children=[
            html.Div(className="surface-card",
                     style={"height": "100%"}, children=[
                html.Div([html.I(className="bi bi-info-circle me-2"),
                          "节点详情"],
                         className="surface-card-header"),
                html.Div(id="kg-detail", className="surface-card-body",
                         children=[
                             html.Div("点击图谱中的节点查看详情",
                                      style={"color": "var(--c-text-muted)",
                                             "fontSize": "13px",
                                             "textAlign": "center",
                                             "padding": "60px 0"}),
                         ]),
            ]),
        ]),
    ]),

    dcc.Store(id="store-kg-fullscreen", data=0),
])


# ============================================================
# 回调 1：视图/布局/重布局 → 更新图
# ============================================================
@callback(
    Output("kg-cyto", "elements"),
    Output("kg-cyto", "layout"),
    Input("kg-view-mode", "value"),
    Input("kg-layout-algo", "value"),
    Input("btn-kg-relayout", "n_clicks"),
)
def cb_update_graph(view_mode, layout_algo, _relayout):
    try:
        elements = _fetch_live_elements(view_mode)
    except Exception as e:
        print(f"[kg] fetch error: {e}")
        elements = ONTOLOGY_ELEMENTS

    layout_cfg = {"name": layout_algo, "animate": True,
                  "animationDuration": 500}
    if layout_algo == "cose":
        layout_cfg.update({"nodeRepulsion": 8000, "idealEdgeLength": 120})
    return elements, layout_cfg


# ============================================================
# 回调 2：点击节点 → 详情
# ============================================================
@callback(
    Output("kg-detail", "children"),
    Input("kg-cyto", "tapNodeData"),
    prevent_initial_call=True,
)
def cb_node_detail(node_data):
    if not node_data:
        return "点击节点查看详情"

    node_id = node_data.get("id", "")
    node_label = node_data.get("label", node_id)
    node_layer = node_data.get("layer", "—")
    color = NODE_COLORS.get(node_id, "#64748B")

    props = {}
    try:
        rows = _run(f"MATCH (n:{node_id}) "
                    f"RETURN properties(n) AS props LIMIT 1")
        if rows:
            props = rows[0].get("props") or {}
    except Exception:
        pass

    prop_rows = []
    for k, v in list(props.items())[:8]:
        prop_rows.append(html.Div([
            html.Span(str(k), style={"color": "var(--c-text-muted)",
                                     "fontWeight": "500"}),
            html.Span(str(v)[:60], style={"fontFamily": "monospace",
                                           "textAlign": "right",
                                           "wordBreak": "break-all"}),
        ], style={"display": "flex", "justifyContent": "space-between",
                  "padding": "6px 0",
                  "borderBottom": "1px solid var(--c-border)",
                  "fontSize": "12px", "gap": "8px"}))

    if not prop_rows:
        prop_rows = [html.Div("（静态 Ontology 节点，无实例属性）",
                              style={"color": "var(--c-text-muted)",
                                     "fontSize": "12px",
                                     "padding": "12px 0",
                                     "textAlign": "center"})]

    return [
        html.Div(style={"background": color, "borderRadius": "8px",
                        "padding": "12px 16px", "marginBottom": "16px"},
                 children=[
                     html.Div(node_label, style={"color": "#fff",
                                                  "fontWeight": "700",
                                                  "fontSize": "16px"}),
                     html.Div(f"层：{node_layer}",
                              style={"color": "rgba(255,255,255,0.75)",
                                     "fontSize": "12px",
                                     "marginTop": "3px"}),
                 ]),
        html.Div(prop_rows),
    ]


# ============================================================
# 回调 3：全屏（clientside）
# ============================================================
clientside_callback(
    """
    function(n){
        if (n) {
            var el = document.getElementById('kg-cyto-wrap');
            if (el && el.requestFullscreen) {
                el.requestFullscreen();
            }
        }
        return (new Date()).getTime();
    }
    """,
    Output("store-kg-fullscreen", "data"),
    Input("btn-kg-fullscreen", "n_clicks"),
    prevent_initial_call=True,
)