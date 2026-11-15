# components/sidebar.py
from dash import html, Input, Output, callback
from flask import session
from config import get_driver

# 左侧菜单结构，绑定对应的查看权限 (read)
SIDEBAR_STRUCTURE = [
    {"section": "Agent 域", "items": [
        ("bi bi-robot", "任务中心", "/agent/task-center", "AgentTask:read"),
    ]},
    {"section": "科学域", "items": [
        ("bi bi-virus", "噬菌体库", "/scientific/phage-library", "Phage:read"),
        ("bi bi-diagram-3", "宿主菌株", "/scientific/host-strain", "Phage:read"),
        ("bi bi-bezier2", "酶基因库", "/scientific/enzyme-gene", "Phage:read"),
        ("bi bi-eyedropper", "裂解实验", "/scientific/lysis-assay", "LysisAssay:read"),
        ("bi bi-bounding-box", "生物膜实验", "/scientific/biofilm-assay", "LysisAssay:read"),
        ("bi bi-journal-medical", "临床病例", "/scientific/clinical-cases", "ClinicalCase:read"),
        ("bi bi-folder2-open", "证据包", "/scientific/evidence-packages", "EvidencePackage:read"),
    ]},
    {"section": "情报域", "items": [
        ("bi bi-bar-chart-line", "情报概览", "/ci/intelligence-board", "IntelligenceEvent:read"),
        ("bi bi-building", "开发项目", "/ci/programs", "DevelopmentProgram:read"),
        ("bi bi-broadcast", "情报事件", "/ci/events", "IntelligenceEvent:read"),
        ("bi bi-cpu", "工程策略", "/ci/strategies", "EngineeringStrategy:read"),
        ("bi bi-graph-up-arrow", "技术评估", "/ci/tech-assessment", "EngineeringStrategy:read"),
        ("bi bi-file-earmark-check","决策记录", "/ci/decision-records", "DecisionRecord:read"),
    ]},
    {"section": "可视化", "items": [
        ("bi bi-share", "知识图谱", "/knowledge-graph", "Phage:read"),
    ]},
    {"section": "系统管理", "items": [
        ("bi bi-people", "用户管理", "/admin/user-manage", "system:user:read"),
        ("bi bi-person-badge", "角色管理", "/admin/role-manage", "system:role:read"),
        ("bi bi-layers", "实验批次", "/admin/experiment-batch", "system:user:read"),
        ("bi bi-cloud-upload", "数据导入", "/admin/data-import", "system:user:read"),
        ("bi bi-database-gear", "Schema", "/admin/schema", "system:user:read"),
        ("bi bi-code-square", "Schema版本", "/admin/schema-registry", "system:user:read"),
        ("bi bi-shield-check", "审计日志", "/admin/audit-log", "system:user:read"),
        ("bi bi-puzzle", "Ontology", "/admin/ontology-module", "system:user:read"),
    ]},
]

def create_sidebar():
    return html.Aside(
        id="sidebar-panel",
        className="sidebar-panel collapsed",
        children=[html.Div(id="sidebar-content", className="sidebar-inner")],
    )

def _get_user_perms():
    user = session.get("user")
    if not user: return set()
    if user.get("role") == "admin": return {"system:admin:all"}
    try:
        with get_driver().session() as s:
            res = s.run("""
                MATCH (u:User {username: $uname})-[:HAS_ROLE]->(:Role)-[:HAS_PERMISSION]->(p:Permission)
                RETURN collect(p.perm_key) AS perms
            """, uname=user["username"]).single()
            return set(res["perms"]) if res and res["perms"] else set()
    except Exception:
        return set()

@callback(
    Output("sidebar-content", "children"),
    Input("url", "pathname"),
)
def render_sidebar(pathname):
    perms = _get_user_perms()
    is_admin = "system:admin:all" in perms

    sections_ui = []
    for group in SIDEBAR_STRUCTURE:
        allowed_items = []
        for icon_cls, label, href, perm in group["items"]:
            if is_admin or perm in perms:
                allowed_items.append((icon_cls, label, href))

        if not allowed_items:
            continue

        sections_ui.append(html.Div(group["section"], className="sidebar-section-title"))
        for icon_cls, label, href in allowed_items:
            item_id = "si-" + href.strip("/").replace("/", "-")
            is_active = pathname == href or (href != "/" and pathname and pathname.startswith(href))
            sections_ui.append(html.A(
                [html.I(className=f"{icon_cls} si-icon"), html.Span(label)],
                href=href,
                className="sidebar-item active" if is_active else "sidebar-item",
                id=item_id,
            ))
        sections_ui.append(html.Div(className="sidebar-divider"))

    return sections_ui