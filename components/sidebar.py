# components/sidebar.py
from dash import html, Input, Output, callback

SIDEBAR_STRUCTURE = [
    {"section": "科学域", "items": [
        ("bi bi-virus",            "噬菌体库",   "/scientific/phage-library"),
        ("bi bi-diagram-3",        "宿主菌株",   "/scientific/host-strain"),
        ("bi bi-dna",              "酶基因库",   "/scientific/enzyme-gene"),
        ("bi bi-eyedropper",       "裂解实验",   "/scientific/lysis-assay"),
        ("bi bi-bounding-box",     "生物膜实验", "/scientific/biofilm-assay"),
        ("bi bi-journal-medical",  "临床病例",   "/scientific/clinical-cases"),
        ("bi bi-folder2-open",     "证据包",     "/scientific/evidence-packages"),
    ]},
    {"section": "情报域", "items": [
        ("bi bi-bar-chart-line",   "情报概览",   "/ci/intelligence-board"),
        ("bi bi-building",         "开发项目",   "/ci/programs"),
        ("bi bi-broadcast",        "情报事件",   "/ci/events"),
        ("bi bi-cpu",              "工程策略",   "/ci/strategies"),
        ("bi bi-graph-up-arrow",   "技术评估",   "/ci/tech-assessment"),
        ("bi bi-file-earmark-check","决策记录",  "/ci/decision-records"),
    ]},
    {"section": "可视化", "items": [
        ("bi bi-share",            "知识图谱",   "/knowledge-graph"),
    ]},
    {"section": "系统管理", "items": [
        ("bi bi-layers",           "实验批次",   "/admin/experiment-batch"),
        ("bi bi-cloud-upload",     "数据导入",   "/admin/data-import"),
        ("bi bi-database-gear",    "Schema",     "/admin/schema"),
        ("bi bi-code-square",      "Schema版本", "/admin/schema-registry"),
        ("bi bi-shield-check",     "审计日志",   "/admin/audit-log"),
        ("bi bi-puzzle",           "Ontology",   "/admin/ontology-module"),
    ]},
]

_ALL_ITEMS = []
for _g in SIDEBAR_STRUCTURE:
    for _icon, _label, _href in _g["items"]:
        _id = "si-" + _href.strip("/").replace("/", "-")
        _ALL_ITEMS.append((_id, _href))


def create_sidebar():
    sections = []
    for group in SIDEBAR_STRUCTURE:
        sections.append(html.Div(group["section"], className="sidebar-section-title"))
        for icon_cls, label, href in group["items"]:
            sections.append(html.A(
                [html.I(className=f"{icon_cls} si-icon"), html.Span(label)],
                href=href,
                className="sidebar-item",
                id="si-" + href.strip("/").replace("/", "-"),
            ))
        sections.append(html.Div(className="sidebar-divider"))
    return html.Aside(
        id="sidebar-panel",
        className="sidebar-panel collapsed",   # 默认折叠
        children=[html.Div(sections, className="sidebar-inner")],
    )


@callback(
    [Output(item_id, "className") for item_id, _ in _ALL_ITEMS],
    Input("url", "pathname"),
)
def cb_sidebar_active(pathname):
    out = []
    for _id, href in _ALL_ITEMS:
        active = pathname == href or (href != "/" and pathname.startswith(href))
        out.append("sidebar-item active" if active else "sidebar-item")
    return out