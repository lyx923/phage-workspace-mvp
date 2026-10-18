# pages/ci/tech_assessment.py
import uuid
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_tech_assessments, _run
from data_access.mutations import add_decision_record
from config import get_driver

dash.register_page(__name__, path="/ci/tech-assessment", name="技术情报")

# ============================================================
# 字典
# ============================================================
SUBJECT_TYPE_MAP = {"construct": "🧬 构建体", "strategy": "⚙️ 工程策略", "claim": "📝 技术主张"}
MATURITY_MAP = {"conceptual": "💡 概念阶段", "in_vitro": "🧪 体外验证", "in_vivo": "🐭 体内验证", "clinical": "🏥 临床阶段"}
LEVEL_MAP = {"high": "高", "medium": "中", "low": "低", "unknown": "未知"}
GLOBAL_TYPE_MAP = {
    "efficacy": "有效性", "host_range": "宿主范围", "safety": "安全性", "manufacturability": "可制造性", "mechanism": "作用机制",
    "lysis": "裂解活性", "biofilm": "生物膜", "in_vivo": "体内实验", "computational": "计算预测"
}
METRIC_MAP = {"relative_improvement": "相对改善率", "lysis_ratio": "裂解率", "host_count": "宿主数量", "eop": "效率析出 (EOP)", "moi": "感染复数 (MOI)", "clearance_rate": "清除率"}
CONTEXT_MAP = {"in_vitro": "体外", "animal": "动物", "clinical": "临床", "computational": "计算"}

# ============================================================
# 表格列定义
# ============================================================
COLUMNS = [
    {"field": "id", "headerName": "评估 ID", "width": 180, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "subject_type_cn", "headerName": "评估对象类型", "width": 130},
    {"field": "subject_id", "headerName": "被评估对象 ID", "width": 180, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "maturity_cn", "headerName": "证据成熟度", "width": 120},
    {"field": "relevance_cn", "headerName": "技术相关性", "width": 110},
    {"field": "potential_cn", "headerName": "转化潜力", "width": 110},
    {"field": "summary", "headerName": "评估摘要", "flex": 2},
]

CLAIM_COLUMNS = [
    {"field": "type_cn", "headerName": "类型", "width": 120},
    {"field": "id", "headerName": "ID", "width": 150, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "text", "headerName": "内容 / 主张文本", "flex": 2},
    {"field": "source_cn", "headerName": "来源 / 上下文", "width": 150},
]

DECISION_TYPE_OPTIONS = [
    {"label": "启动评估", "value": "evaluate"},
    {"label": "持续监控", "value": "monitor"},
    {"label": "寻求合作", "value": "partner"},
    {"label": "降低优先级", "value": "deprioritize"},
]


def _get_strategies():
    try:
        rows = _run("MATCH (es:EngineeringStrategy) RETURN es.strategy_id AS id, es.strategy_type AS type")
        return [{"label": f"{r['type']} ({r['id']})", "value": r['id']} for r in rows]
    except: return []

def _get_constructs():
    try:
        rows = _run("MATCH (ec:EngineeredPhageConstruct) RETURN ec.construct_id AS id, ec.public_name AS name")
        return [{"label": f"{r['name'] or r['id']}", "value": r['id']} for r in rows]
    except: return []


layout = html.Div([
    html.Div(id="ta-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("技术情报与评估", className="page-title"),
            html.Div("管理六维技术评估 · 生成技术简报 · 分离主张与结果", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-ta-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-file-earmark-text me-1"), "生成技术简报"], id="btn-ta-brief", className="btn-primary-custom"),
        ]),
    ]),
    
    # 标签页
    dbc.Tabs([
        dbc.Tab(label="技术评估 (Technology Assessment)", tab_id="tab-assess", children=[
            html.Div(className="filter-bar mt-3", children=[
                dcc.Input(id="ta-search", type="text", debounce=True, value="", placeholder="搜索对象 ID…", className="filter-search"),
                html.Div(id="ta-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
            ]),
            html.Div(className="surface-card", children=[
                dag.AgGrid(id="ta-grid", columnDefs=COLUMNS, rowData=[], dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"}, style={"height": None, "minHeight": "400px"}),
            ]),
        ]),
        
        dbc.Tab(label="主张与结果分离验证 (Claim vs Result)", tab_id="tab-claims", children=[
            html.Div(className="mt-3 mb-3", children=[
                html.P("根据 PRD 规定：主张（Claim）是来源声称什么；结果（Result）是来源实际报告了什么数据。系统严格分开存储。", style={"fontSize": "13px", "color": "var(--c-text-secondary)"})
            ]),
            html.Div(className="surface-card", children=[
                dag.AgGrid(id="claim-grid", columnDefs=CLAIM_COLUMNS, rowData=[], dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"}, style={"height": None, "minHeight": "400px"}),
            ]),
        ])
    ], id="ta-tabs", active_tab="tab-assess"),

    # 生成技术简报抽屉
    dbc.Offcanvas(
        id="ta-brief-drawer", title="生成技术简报", placement="end", is_open=False, style={"width": "600px"},
        children=[
            dbc.Form([
                html.P("选择技术策略或构建体，系统将提取已审核的构建体、技术主张、技术结果和证据成熟度，生成技术简报。", style={"fontSize": "13px", "marginBottom": "16px"}),
                dbc.Row([dbc.Label("按策略生成", width=3), dbc.Col(dcc.Dropdown(id="ta-brief-strategy", options=_get_strategies(), placeholder="选择策略"), width=9)], className="mb-3"),
                dbc.Row([dbc.Label("按构建体生成", width=3), dbc.Col(dcc.Dropdown(id="ta-brief-construct", options=_get_constructs(), placeholder="选择构建体"), width=9)], className="mb-4"),
                html.Button([html.I(className="bi bi-magic me-1"), "立即生成"], id="btn-ta-do-brief", className="btn-primary-custom w-100"),
            ]),
            html.Hr(),
            html.Div(id="ta-brief-result", style={"fontSize": "13px"}),
            
            # ★ 新增：转决策按钮
            dcc.Store(id="store-ta-brief-id"),
            html.Div(id="ta-brief-action-container", style={"display": "none", "marginTop": "20px"}, children=[
                html.Button([html.I(className="bi bi-journal-check me-1"), "基于此技术简报发起内部决策"], id="btn-ta-to-decision", className="btn-primary-custom w-100")
            ])
        ]
    ),

    # ★ 新增：技术决策弹窗
    dbc.Modal(
        id="modal-ta-decision", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("基于技术简报记录决策")),
            dbc.ModalBody([
                dbc.Row([dbc.Label("决策类型", width=3), dbc.Col(dbc.Select(id="ta-dec-type", options=DECISION_TYPE_OPTIONS, value="evaluate"), width=9)], className="mb-3"),
                dbc.Row([dbc.Label("决策摘要 *", width=3), dbc.Col(dbc.Textarea(id="ta-dec-summary", rows=3, placeholder="如：启动尾纤维工程内部可行性评估..."), width=9)], className="mb-3"),
                dbc.Row([dbc.Label("决策人 *", width=3), dbc.Col(dbc.Input(id="ta-dec-owner", value="VP_RD"), width=9)], className="mb-4"),
                html.Div(id="ta-dec-feedback")
            ]),
            dbc.ModalFooter([
                html.Button("取消", id="btn-ta-dec-cancel", className="btn-outline-custom me-2"),
                html.Button("确认保存", id="btn-ta-dec-save", className="btn-primary-custom"),
            ])
        ]
    )
])


# ============================================================
# 加载列表
# ============================================================
@callback(
    Output("ta-grid", "rowData"),
    Output("ta-count-label", "children"),
    Output("ta-error-banner", "children"),
    Input("btn-ta-refresh", "n_clicks"),
    Input("ta-search", "value"),
)
def cb_load(_, search):
    try:
        rows = list_tech_assessments(keyword=search or "")
        for r in rows:
            st, mat = r.get("subject_type", ""), r.get("evidence_maturity", "")
            rel, pot = r.get("technical_relevance", ""), r.get("translational_potential", "")
            r["subject_type_cn"] = SUBJECT_TYPE_MAP.get(st, st)
            r["maturity_cn"] = MATURITY_MAP.get(mat, mat)
            r["relevance_cn"] = LEVEL_MAP.get(rel, rel)
            r["potential_cn"] = LEVEL_MAP.get(pot, pot)
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}", color="danger", className="mb-3")


@callback(
    Output("claim-grid", "rowData"),
    Input("ta-tabs", "active_tab"),
    Input("btn-ta-refresh", "n_clicks"),
)
def cb_load_claims(active_tab, n):
    if active_tab != "tab-claims": return no_update
    data = []
    try:
        with get_driver().session() as s:
            claims = s.run("MATCH (tc:TechnicalClaim) RETURN tc.claim_id AS id, tc.claim_text AS text, tc.claim_type AS type, tc.claimant_type AS source LIMIT 50")
            for r in claims:
                d = dict(r)
                d["type_cn"] = f"📝 {GLOBAL_TYPE_MAP.get(d.get('type', ''), d.get('type', ''))}"
                d["source_cn"] = f"主张方: {d.get('source', '')}"
                data.append(d)
            results = s.run("MATCH (tr:TechnicalResult) RETURN tr.result_id AS id, tr.metric_name AS text, tr.result_type AS type, tr.study_context AS source LIMIT 50")
            for r in results:
                d = dict(r)
                d["type_cn"] = f"🔬 {GLOBAL_TYPE_MAP.get(d.get('type', ''), d.get('type', ''))}"
                d["text"] = METRIC_MAP.get(d.get("text", ""), d.get("text", ""))
                d["source_cn"] = f"上下文: {CONTEXT_MAP.get(d.get('source', ''), d.get('source', ''))}"
                data.append(d)
    except Exception: pass
    return data


# ============================================================
# 生成技术简报
# ============================================================
@callback(
    Output("ta-brief-drawer", "is_open"),
    Input("btn-ta-brief", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_brief_drawer(n):
    return True


@callback(
    Output("ta-brief-result", "children"),
    Output("store-ta-brief-id", "data"),
    Output("ta-brief-action-container", "style"),
    Input("btn-ta-do-brief", "n_clicks"),
    State("ta-brief-strategy", "value"),
    State("ta-brief-construct", "value"),
    prevent_initial_call=True,
)
def cb_gen_tech_brief(n, strat_id, construct_id):
    if not strat_id and not construct_id:
        return dbc.Alert("请至少选择一个策略或构建体", color="warning"), None, {"display": "none"}

    try:
        from src.engineering_intelligence.technology_brief import generate_technology_brief
        brief = generate_technology_brief(get_driver(), strategy_id=strat_id, construct_id=construct_id, technology_question="分析当前技术的成熟度与转化潜力", persist=True)
        
        facts = brief.get("recommended_next_steps", [])
        maturity = brief.get("evidence_maturity", {}).get("highest_maturity", "unknown")
        constructs = len(brief.get("known_constructs", []))
        claims = len(brief.get("technical_claims", []))
        results = len(brief.get("technical_results", []))

        ui = [
            html.H5("📄 技术简报生成成功", className="text-success"),
            html.Div(f"简报 ID: {brief.get('brief_id')}", style={"fontFamily": "monospace", "marginBottom": "16px", "color": "var(--c-text-muted)"}),
            html.H6("核心指标", style={"fontWeight": "600"}),
            html.Ul([
                html.Li(f"最高证据成熟度: {MATURITY_MAP.get(maturity, maturity)}"),
                html.Li(f"公开构建体数: {constructs}"),
                html.Li(f"技术主张数: {claims}"),
                html.Li(f"技术结果数: {results}"),
            ]),
            html.H6("建议下一步", style={"fontWeight": "600", "marginTop": "16px"}),
            html.Ul([html.Li(f) for f in facts] if facts else [html.Li("暂无建议")]),
        ]
        # 返回：UI展示，简报ID（存入Store），显示转决策按钮
        return ui, brief.get("brief_id"), {"display": "block", "marginTop": "20px"}
    except Exception as e:
        return dbc.Alert(f"生成失败：{e}", color="danger"), None, {"display": "none"}


# ============================================================
# 技术简报转决策
# ============================================================
@callback(
    Output("modal-ta-decision", "is_open"),
    Input("btn-ta-to-decision", "n_clicks"),
    Input("btn-ta-dec-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_ta_dec_modal(open_n, cancel_n):
    return ctx.triggered_id == "btn-ta-to-decision"


@callback(
    Output("modal-ta-decision", "is_open", allow_duplicate=True),
    Output("ta-dec-feedback", "children"),
    Input("btn-ta-dec-save", "n_clicks"),
    State("store-ta-brief-id", "data"),
    State("ta-dec-type", "value"),
    State("ta-dec-summary", "value"),
    State("ta-dec-owner", "value"),
    prevent_initial_call=True,
)
def save_ta_decision(n, brief_id, dtype, summary, owner):
    if not brief_id or not (summary or "").strip():
        return no_update, dbc.Alert("简报ID缺失或摘要为空", color="danger")

    try:
        # 注意：这里的 brief_id 是从技术简报生成的 IntelligenceProduct
        dec_id = add_decision_record(
            brief_id=brief_id, 
            decision_type=dtype, 
            decision_summary=summary.strip(),
            rationale="基于技术情报简报分析。", 
            decision_owner=(owner or "VP_RD").strip(), 
            review_date=None,
        )
        return False, dbc.Alert(f"技术决策 {dec_id} 已成功创建！可前往【决策记录】页面查看。", color="success", dismissable=True, duration=4000)
    except Exception as e:
        return False, dbc.Alert(f"保存失败：{e}", color="danger")