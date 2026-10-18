# pages/scientific/evidence_packages.py
import uuid
import json
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import _run
from config import get_driver

dash.register_page(__name__, path="/scientific/evidence-packages", name="证据包")

STATUS_OPTIONS = [
    {"label": "草稿",   "value": "draft"},
    {"label": "已审核", "value": "approved"},
    {"label": "已拒绝", "value": "rejected"},
]

STATUS_MAP = {
    "draft": "📝 草稿",
    "approved": "✅ 已通过",
    "rejected": "❌ 已拒绝"
}

COLUMNS = [
    {"field": "id", "headerName": "包 ID", "width": 140,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "species", "headerName": "目标病原", "width": 150},
    {"field": "infection_type", "headerName": "感染类型", "width": 110},
    {"field": "phages", "headerName": "候选噬菌体", "width": 150},
    {"field": "summary", "headerName": "LLM 摘要 / 结论", "flex": 1, "minWidth": 200,
     "cellStyle": {"fontSize": "12px", "color": "var(--c-text-secondary)"}},
    {"field": "status_cn", "headerName": "状态", "width": 100},
    {"field": "created_at", "headerName": "创建时间", "width": 130,
     "cellStyle": {"fontSize": "12px", "color": "var(--c-text-muted)"}},
    
    # ★ 修复：加宽操作列，并强制不换行
    {"field": "actions", "headerName": "操作", "width": 150, "minWidth": 140,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", 
                   "fontWeight": "bold", "textAlign": "center", "whiteSpace": "nowrap"}},
]


def _list_pathogen_options():
    try:
        rows = _run("MATCH (p:Pathogen) RETURN p.species AS species ORDER BY species")
        return [{"label": r["species"], "value": r["species"]}
                for r in rows if r.get("species")]
    except Exception:
        return []


def _fetch_packages(keyword="", status=""):
    with get_driver().session() as s:
        query = """
            MATCH (p:ScientificEvidencePackage)
            WHERE ($status = '' OR p.status = $status)
              AND ($kw = '' OR p.package_id CONTAINS $kw)
            OPTIONAL MATCH (p)-[:INCLUDES_CANDIDATE]->(ph:Phage)
            WITH p, collect(DISTINCT ph.name) AS phages
            RETURN p.package_id AS id,
                   p.status AS status,
                   p.query_context AS query_context,
                   p.summary AS summary,
                   p.created_at AS created_at,
                   phages
            ORDER BY p.created_at DESC
        """
        records = list(s.run(query, status=status, kw=keyword))
    
    rows = []
    for r in records:
        ctx_data = {}
        if r.get("query_context"):
            try:
                ctx_data = json.loads(r["query_context"]) if isinstance(r["query_context"], str) else r["query_context"]
            except Exception:
                pass
        
        t = r.get("created_at")
        t_str = ""
        if t:
            try:
                if hasattr(t, "to_native"): t = t.to_native()
                t_str = t.strftime("%Y-%m-%d %H:%M") if hasattr(t, "strftime") else str(t)[:16]
            except Exception:
                t_str = str(t)

        st_raw = str(r.get("status", "draft")).strip().lower()

        row = {
            "id": r["id"],
            "species": ctx_data.get("species", "—"),
            "infection_type": ctx_data.get("infection_type", "—"),
            "phages": ", ".join([x for x in r["phages"] if x]) if r["phages"] else "无",
            "summary": (r.get("summary") or "无")[:60] + "..." if r.get("summary") and len(r.get("summary")) > 60 else (r.get("summary") or "无"),
            "status": st_raw,
            "status_cn": STATUS_MAP.get(st_raw, st_raw),
            "created_at": t_str,
        }
        
        if row["status"] == "draft":
            row["actions"] = "🔍 查看 / 审核"
        else:
            row["actions"] = "🔍 查看"
            
        rows.append(row)
    return rows


layout = html.Div([
    html.Div(id="ep-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("证据包", className="page-title"),
            html.Div("管理 ScientificEvidencePackage · 专家评分与审核", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-ep-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-lightning-charge me-1"), "生成证据包"],
                        id="btn-ep-generate", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ep-search", type="text", debounce=True, value="",
                  placeholder="搜索包 ID…", className="filter-search"),
        dcc.Dropdown(id="ep-status-filter",
                     options=[{"label": "全部状态", "value": ""}] + STATUS_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        html.Div(id="ep-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="ep-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={
                "pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight",
            },
            style={"height": None, "minHeight": "500px"},
        ),
    ]),

    # 生成证据包表单
    dbc.Offcanvas(
        id="ep-offcanvas", title="生成证据包", placement="end", is_open=False, style={"width": "500px"},
        children=[dbc.Form([
            html.P("选择病原和感染类型，系统将检索并生成草稿态证据包。", style={"fontSize": "12px", "color": "var(--c-text-muted)", "marginBottom": "16px"}),
            dbc.Row([dbc.Label("病原 *", width=3), dbc.Col(dcc.Dropdown(id="ep-form-pathogen", placeholder="选择病原物种", options=_list_pathogen_options(), clearable=False), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("感染类型", width=3), dbc.Col(dbc.Input(id="ep-form-infection-type", placeholder="如 Pneumonia"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("耐药机制", width=3), dbc.Col(dbc.Input(id="ep-form-resistance", placeholder="如 Carbapenem-resistant"), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-ep-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "生成"], id="btn-ep-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ep-form-feedback", className="mt-3"),
        ])]),

    # 详情与审核抽屉
    dcc.Store(id="store-active-pkg"),
    dbc.Offcanvas(
        id="ep-detail-drawer", title="证据包详情与审核", placement="end", is_open=False, style={"width": "600px"},
        children=[
            html.Div(id="ep-detail-content"),
            html.Hr(),
            # 评分与审核表单
            html.Div(id="ep-review-form", children=[
                html.H6("专家评审", style={"fontWeight": "600", "marginBottom": "12px"}),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("专家评分 (1-5)"),
                        dcc.Slider(id="ep-review-score", min=1, max=5, step=1, value=4, marks={1:"1",2:"2",3:"3",4:"4",5:"5"})
                    ], width=12)
                ], className="mb-3"),
                dbc.Row([
                    dbc.Col([
                        dbc.Label("评审意见"),
                        dbc.Textarea(id="ep-review-comment", placeholder="填写评审意见...", rows=3)
                    ], width=12)
                ], className="mb-4"),
                html.Div([
                    html.Button("❌ 拒绝", id="btn-ep-reject", className="btn-danger-custom me-2"),
                    html.Button("✅ 通过并签字", id="btn-ep-approve", className="btn-primary-custom"),
                ], style={"display": "flex", "justifyContent": "flex-end"}),
            ])
        ]
    )
])


@callback(
    Output("ep-grid", "rowData"),
    Output("ep-count-label", "children"),
    Output("ep-error-banner", "children"),
    Input("btn-ep-refresh", "n_clicks"),
    Input("ep-search", "value"),
    Input("ep-status-filter", "value"),
)
def cb_load(_, search, status):
    try:
        rows = _fetch_packages(keyword=search or "", status=status or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"查询失败：{e}", color="danger", className="mb-3")

@callback(
    Output("ep-offcanvas", "is_open"),
    Input("btn-ep-generate", "n_clicks"),
    Input("btn-ep-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-ep-generate"

@callback(
    Output("ep-form-feedback", "children"),
    Output("ep-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ep-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ep-save", "n_clicks"),
    State("ep-form-pathogen", "value"),
    State("ep-form-infection-type", "value"),
    State("ep-form-resistance", "value"),
    prevent_initial_call=True,
)
def cb_generate(_, species, infection_type, resistance):
    if not species:
        return dbc.Alert("病原物种必填", color="danger"), no_update, no_update

    try:
        from src.scientific.evidence_package_service import build_evidence_package_from_db
        result = build_evidence_package_from_db(
            species=species,
            resistance=resistance or None,
            infection_type=infection_type or None,
        )
        pkg_id = result.get("_package_id", "unknown")

        # 顺手生成复用事件，挂到知识图谱上
        if pkg_id != "unknown":
            reuse_id = f"REUSE-{uuid.uuid4().hex[:8].upper()}"
            with get_driver().session() as s:
                case_res = s.run("MATCH (c:ClinicalCase) RETURN c.case_id AS cid LIMIT 1").single()
                cid = case_res["cid"] if case_res else None
                
                s.run("""
                    MATCH (pkg:ScientificEvidencePackage {package_id: $pkg_id})
                    MERGE (k:KnowledgeReuseEvent {reuse_event_id: $rid})
                    SET k.reuse_type = 'auto_generated',
                        k.status = 'detected',
                        k.retrieval_reason = '生成证据包时自动提取的相似病例',
                        k.created_at = datetime()
                    MERGE (k)-[:TARGETS_PACKAGE]->(pkg)
                """, pkg_id=pkg_id, rid=reuse_id)
                
                if cid:
                    s.run("""
                        MATCH (k:KnowledgeReuseEvent {reuse_event_id: $rid})
                        MATCH (c:ClinicalCase {case_id: $cid})
                        MERGE (k)-[:SOURCE_CASE]->(c)
                    """, rid=reuse_id, cid=cid)

        if result.get("_api_error"):
            return (dbc.Alert(f"已生成 {pkg_id}（LLM 调用失败）", color="warning"), False, 1)

        return (dbc.Alert(f"已生成证据包 {pkg_id}", color="success"), False, 1)
    except Exception as e:
        return dbc.Alert(f"生成失败：{e}", color="danger"), no_update, no_update


# ============================================================
# 核心改造：点击查看详情
# ============================================================
@callback(
    Output("store-active-pkg", "data"),
    Output("ep-detail-drawer", "is_open"),
    Output("ep-detail-content", "children"),
    Output("ep-review-form", "style"),
    Input("ep-grid", "cellClicked"),
    State("ep-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_detail(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update, no_update

    row = row_data[rowIndex]
    pkg_id = row["id"]
    st_raw = str(row.get("status", "")).strip().lower()
    form_style = {"display": "block"} if st_raw == "draft" else {"display": "none"}

    # 从图谱拉取详细的关联证据
    with get_driver().session() as s:
        details = s.run("""
            MATCH (pkg:ScientificEvidencePackage {package_id: $pid})
            OPTIONAL MATCH (pkg)-[:INCLUDES_CANDIDATE]->(ph:Phage)
            OPTIONAL MATCH (pkg)-[:REFERENCES_CASE]->(c:ClinicalCase)
            RETURN pkg.summary AS summary, 
                   pkg.query_context AS context,
                   collect(DISTINCT ph.name) AS phages,
                   collect(DISTINCT c.case_id) AS cases
        """, pid=pkg_id).single()

    ctx_data = {}
    if details.get("context"):
        try:
            ctx_data = json.loads(details["context"]) if isinstance(details["context"], str) else details["context"]
        except: pass

    # 构造抽屉内的展示内容
    content = [
        html.H5(f"包 ID: {pkg_id}", style={"fontFamily": "monospace", "color": "var(--c-primary)"}),
        html.Div([
            dbc.Badge(f"病原: {ctx_data.get('species', '—')}", color="info", className="me-2"),
            dbc.Badge(f"感染类型: {ctx_data.get('infection_type', '—')}", color="warning", className="text-dark me-2"),
            dbc.Badge(f"状态: {STATUS_MAP.get(st_raw, st_raw)}", color="success" if st_raw=="approved" else "secondary"),
        ], className="mb-4"),
        
        html.H6([html.I(className="bi bi-stars me-2"), "LLM 组织结论"], style={"fontWeight": "600"}),
        html.Div(details.get("summary") or "无", style={
            "background": "var(--c-bg)", "padding": "12px", "borderRadius": "8px",
            "fontSize": "13px", "lineHeight": "1.6", "marginBottom": "20px"
        }),
        
        html.H6([html.I(className="bi bi-virus me-2"), "匹配候选噬菌体"], style={"fontWeight": "600"}),
        html.Div(", ".join([p for p in details.get("phages", []) if p]) or "无", 
                 style={"fontFamily": "monospace", "fontSize": "13px", "marginBottom": "20px"}),
                 
        html.H6([html.I(className="bi bi-journal-medical me-2"), "参考相似病例"], style={"fontWeight": "600"}),
        html.Div(", ".join([c for c in details.get("cases", []) if c]) or "无", 
                 style={"fontFamily": "monospace", "fontSize": "13px", "marginBottom": "20px"}),
    ]

    return pkg_id, True, content, form_style


# ============================================================
# 执行审核与打分
# ============================================================
@callback(
    Output("ep-detail-drawer", "is_open", allow_duplicate=True),
    Output("btn-ep-refresh", "n_clicks", allow_duplicate=True),
    Output("ep-error-banner", "children", allow_duplicate=True),
    Input("btn-ep-approve", "n_clicks"),
    Input("btn-ep-reject", "n_clicks"),
    State("store-active-pkg", "data"),
    State("ep-review-score", "value"),
    State("ep-review-comment", "value"),
    prevent_initial_call=True,
)
def cb_submit_review(approve_n, reject_n, pkg_id, score, comment):
    trigger = ctx.triggered_id
    if not pkg_id:
        return no_update, no_update, no_update

    decision = "approved" if trigger == "btn-ep-approve" else "rejected"
    
    try:
        with get_driver().session() as s:
            # 1. 更新证据包状态
            s.run("""
                MATCH (pkg:ScientificEvidencePackage {package_id: $pid})
                SET pkg.status = $decision, pkg.review_status = $decision, pkg.updated_at = datetime()
            """, pid=pkg_id, decision=decision)
            
            # 2. 写入包含打分的 Review 记录
            rid = f"REV-{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (pkg:ScientificEvidencePackage {package_id: $pid})
                CREATE (r:Review {
                    review_id: $rid, review_type: 'scientific_package_review',
                    target_object_type: 'ScientificEvidencePackage',
                    target_object_id: $pid, reviewer_id: 'dashboard_expert',
                    decision: $decision, score: $score, comment: $comment,
                    created_at: datetime()
                })
                CREATE (r)-[:REVIEWS]->(pkg)
            """, pid=pkg_id, decision=decision, rid=rid, score=score, comment=comment or "")

            # 3. 顺带把底层的 KnowledgeReuseEvent 确认掉（实现业务闭环）
            s.run("""
                MATCH (k:KnowledgeReuseEvent)-[:TARGETS_PACKAGE]->(pkg:ScientificEvidencePackage {package_id: $pid})
                WHERE k.status = 'detected'
                SET k.status = 'confirmed', k.expert_assessment = 'confirmed', k.updated_at = datetime()
            """, pid=pkg_id)

        msg = dbc.Alert(f"操作成功：{pkg_id} 已被标记为【{STATUS_MAP[decision]}】，评分 {score} 分。", color="success", dismissable=True, duration=4000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"执行失败：{e}", color="danger", dismissable=True)