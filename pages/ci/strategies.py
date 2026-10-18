# pages/ci/strategies.py
import uuid
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.mutations import add_strategy
from config import get_driver

dash.register_page(__name__, path="/ci/strategies", name="工程策略")

# ============================================================
# 字典定义
# ============================================================
STRATEGY_TYPE_OPTIONS = [
    {"label": "宿主范围扩展",   "value": "host_range_expansion"},
    {"label": "尾纤维工程",     "value": "tail_fiber_engineering"},
    {"label": "受体结合工程",   "value": "receptor_binding_engineering"},
    {"label": "裂解能力增强",   "value": "lysis_enhancement"},
    {"label": "溶原性去除",     "value": "lysogeny_removal"},
    {"label": "生物膜破坏",     "value": "biofilm_disruption"},
    {"label": "递送载荷",       "value": "payload_delivery"},
    {"label": "抗耐药载荷",     "value": "anti_resistance_payload"},
    {"label": "抗毒力载荷",     "value": "anti_virulence_payload"},
    {"label": "免疫调节",       "value": "immune_modulation"},
    {"label": "噬菌体展示",     "value": "phage_display"},
    {"label": "基因组精简",     "value": "genome_minimization"},
    {"label": "其他",           "value": "other"},
]

MATURITY_OPTIONS = [
    {"label": "概念阶段", "value": "conceptual"},
    {"label": "体外验证", "value": "in_vitro"},
    {"label": "体内验证", "value": "in_vivo"},
    {"label": "临床",     "value": "clinical"},
]

CONSTRUCT_STATUS_OPTIONS = [
    {"label": "💡 概念设计", "value": "proposed"},
    {"label": "🛠️ 已构建",   "value": "built"},
    {"label": "🧪 体外验证", "value": "in_vitro_tested"},
    {"label": "🐭 体内验证", "value": "in_vivo_tested"},
    {"label": "🏥 临床阶段", "value": "clinical"},
]

TYPE_MAP = {opt["value"]: f"🎯 {opt['label']}" for opt in STRATEGY_TYPE_OPTIONS}
TYPE_MAP["other"] = "⚙️ 其他"

MATURITY_MAP = {
    "conceptual": "💡 概念阶段",
    "in_vitro": "🧪 体外验证",
    "in_vivo": "🐭 体内验证",
    "clinical": "🏥 临床阶段"
}

STATUS_MAP = {
    "pending": "⏳ 待审核",
    "reviewed": "✅ 已审核",
    "approved": "✅ 已通过",
    "rejected": "❌ 已拒绝"
}

CONSTRUCT_STATUS_MAP = {opt["value"]: opt["label"] for opt in CONSTRUCT_STATUS_OPTIONS}


# ============================================================
# 表格列定义
# ============================================================
STRATEGY_COLUMNS = [
    {"field": "id", "headerName": "策略 ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "type_cn", "headerName": "策略类型", "width": 180},
    {"field": "description", "headerName": "描述", "flex": 2},
    {"field": "maturity_cn", "headerName": "证据成熟度", "width": 130},
    {"field": "construct_count", "headerName": "构建体数", "width": 100},
    {"field": "status_cn", "headerName": "审核状态", "width": 110},
    {"field": "actions", "headerName": "操作", "width": 130, "sortable": False, "filter": False, "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]

CONSTRUCT_COLUMNS = [
    {"field": "id", "headerName": "构建体 ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "name", "headerName": "公开名称", "width": 180},
    {"field": "strategies", "headerName": "实现策略", "flex": 2},
    {"field": "pathogens", "headerName": "靶向病原", "width": 200},
    {"field": "status_cn", "headerName": "研发状态", "width": 120},
]


# ============================================================
# 数据查询函数
# ============================================================
def _fetch_strategies(keyword="", stype=""):
    try:
        with get_driver().session() as s:
            query = """
                MATCH (es:EngineeringStrategy)
                WHERE ($kw = '' OR es.strategy_type CONTAINS $kw OR es.description CONTAINS $kw)
                  AND ($stype = '' OR es.strategy_type = $stype)
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es)
                RETURN es.strategy_id AS id, es.strategy_type AS strategy_type,
                       es.description AS description, es.evidence_maturity AS evidence_maturity,
                       es.review_status AS review_status, count(DISTINCT ec) AS construct_count
                ORDER BY es.strategy_type
            """
            records = list(s.run(query, kw=keyword, stype=stype))
            
        rows = []
        for r in records:
            d = dict(r)
            st = str(d.get("review_status") or "pending").strip().lower()
            d["type_cn"] = TYPE_MAP.get(d.get("strategy_type", ""), d.get("strategy_type", ""))
            d["maturity_cn"] = MATURITY_MAP.get(d.get("evidence_maturity", ""), d.get("evidence_maturity", ""))
            d["status_cn"] = STATUS_MAP.get(st, st)
            d["actions"] = "👉 确认审核" if (st == "pending" or not d.get("review_status")) else "已处理"
            rows.append(d)
        return rows
    except Exception as e:
        print(f"[Strategy Fetch Error] {e}")
        return []


def _fetch_constructs():
    try:
        with get_driver().session() as s:
            query = """
                MATCH (ec:EngineeredPhageConstruct)
                OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
                OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
                WITH ec, collect(DISTINCT es.strategy_type) AS strat_types, collect(DISTINCT p.species) AS pathogens
                RETURN ec.construct_id AS id, ec.public_name AS name, ec.construct_status AS status, strat_types, pathogens
                ORDER BY ec.created_at DESC LIMIT 100
            """
            records = list(s.run(query))
        
        rows = []
        for r in records:
            d = dict(r)
            # 翻译策略列表
            st_list = [TYPE_MAP.get(st, st) for st in d.get("strat_types", []) if st]
            d["strategies"] = ", ".join(st_list) if st_list else "未关联"
            
            # 翻译病原
            d["pathogens"] = ", ".join([p for p in d.get("pathogens", []) if p]) or "未指定"
            
            # 翻译状态
            st = d.get("status", "")
            d["status_cn"] = CONSTRUCT_STATUS_MAP.get(st, st)
            rows.append(d)
        return rows
    except Exception as e:
        print(f"[Construct Fetch Error] {e}")
        return []


def _get_strategy_options():
    """用于新建构建体时选择关联策略"""
    try:
        rows = _fetch_strategies()
        return [{"label": r["type_cn"], "value": r["id"]} for r in rows]
    except:
        return []


# ============================================================
# 页面布局 (Tabs)
# ============================================================
layout = html.Div([
    html.Div(id="st-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("工程情报与策略", className="page-title"),
            html.Div("管理工程策略理论 · 记录实际工程化构建体", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-st-refresh", className="btn-outline-custom"),
        ]),
    ]),

    # 标签页
    dbc.Tabs([
        # Tab 1: 工程策略
        dbc.Tab(label="工程策略 (Strategies)", tab_id="tab-strategy", children=[
            html.Div(className="filter-bar mt-3", children=[
                dcc.Input(id="st-search", type="text", debounce=True, value="", placeholder="搜索策略类型或描述…", className="filter-search"),
                dcc.Dropdown(id="st-type-filter", options=[{"label": "全部类型", "value": ""}] + STRATEGY_TYPE_OPTIONS, value="", clearable=False, style={"width": "200px"}),
                html.Button([html.I(className="bi bi-plus-lg me-1"), "新建策略"], id="btn-st-new", className="btn-primary-custom ms-3"),
                html.Div(id="st-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
            ]),
            html.Div(className="surface-card", children=[
                dag.AgGrid(id="st-grid", columnDefs=STRATEGY_COLUMNS, rowData=[],
                           dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                           style={"height": None, "minHeight": "400px"}),
            ]),
        ]),
        
        # Tab 2: 构建体
        dbc.Tab(label="工程化构建体 (Constructs)", tab_id="tab-construct", children=[
            html.Div(className="filter-bar mt-3", children=[
                html.Div("已入库的具体工程噬菌体设计方案", style={"fontSize": "13px", "color": "var(--c-text-secondary)", "display": "flex", "alignItems": "center"}),
                html.Button([html.I(className="bi bi-plus-lg me-1"), "新建构建体"], id="btn-c-new", className="btn-primary-custom ms-auto"),
            ]),
            html.Div(className="surface-card", children=[
                dag.AgGrid(id="c-grid", columnDefs=CONSTRUCT_COLUMNS, rowData=[],
                           dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
                           style={"height": None, "minHeight": "400px"}),
            ]),
        ])
    ], id="st-tabs", active_tab="tab-strategy"),

    # ========================================
    # 抽屉 1：新建策略
    # ========================================
    dbc.Offcanvas(
        id="st-offcanvas", title="新建工程策略", placement="end", is_open=False, style={"width": "480px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("策略类型 *", width=3), dbc.Col(dbc.Select(id="st-form-type", options=STRATEGY_TYPE_OPTIONS, value="host_range_expansion"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("证据成熟度", width=3), dbc.Col(dbc.Select(id="st-form-maturity", options=MATURITY_OPTIONS, value="conceptual"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("描述", width=3), dbc.Col(dbc.Textarea(id="st-form-desc", rows=4), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-st-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-st-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="st-form-feedback", className="mt-3"),
        ])]),

    # ========================================
    # 抽屉 2：新建构建体
    # ========================================
    dbc.Offcanvas(
        id="c-offcanvas", title="新建工程化构建体", placement="end", is_open=False, style={"width": "500px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("公开名称 *", width=4), dbc.Col(dbc.Input(id="c-form-name", placeholder="如 vB_Kpn_Immune_01"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("实现策略 *", width=4), dbc.Col(dcc.Dropdown(id="c-form-strategies", options=_get_strategy_options(), multi=True, placeholder="选择该构建体使用的策略"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("靶向病原", width=4), dbc.Col(dbc.Input(id="c-form-pathogens", placeholder="如 Klebsiella pneumoniae"), width=8)], className="mb-3"),
            dbc.Row([dbc.Label("研发状态", width=4), dbc.Col(dbc.Select(id="c-form-status", options=CONSTRUCT_STATUS_OPTIONS, value="proposed"), width=8)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-c-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-c-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="c-form-feedback", className="mt-3"),
        ])]),

    # 审核策略弹窗
    dcc.Store(id="store-st-active"),
    dbc.Modal(
        id="modal-st-review", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("审核工程策略")),
            dbc.ModalBody(id="modal-st-body", children="确认该策略归类正确吗？"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-st-modal-cancel", className="btn-outline-custom me-2"),
                html.Button("❌ 拒绝", id="btn-st-modal-reject", className="btn-danger-custom me-2"),
                html.Button("✅ 通过", id="btn-st-modal-approve", className="btn-primary-custom"),
            ]),
        ]
    )
])


# ============================================================
# 回调函数
# ============================================================
@callback(
    Output("st-grid", "rowData"),
    Output("st-count-label", "children"),
    Output("c-grid", "rowData"),
    Output("st-error-banner", "children"),
    Input("btn-st-refresh", "n_clicks"),
    Input("st-search", "value"),
    Input("st-type-filter", "value"),
    Input("btn-c-save", "n_clicks"),
)
def cb_load(_, search, stype, __):
    try:
        s_rows = _fetch_strategies(keyword=search or "", stype=stype or "")
        c_rows = _fetch_constructs()
        return s_rows, f"共 {len(s_rows)} 条策略", c_rows, None
    except Exception as e:
        return [], "加载失败", [], dbc.Alert(f"Neo4j 连接失败：{e}", color="danger", className="mb-3")


@callback(
    Output("st-offcanvas", "is_open"),
    Input("btn-st-new", "n_clicks"),
    Input("btn-st-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_st_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-st-new"


@callback(
    Output("c-offcanvas", "is_open"),
    Output("c-form-strategies", "options"),
    Input("btn-c-new", "n_clicks"),
    Input("btn-c-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_c_offcanvas(new_n, cancel_n):
    if ctx.triggered_id == "btn-c-new":
        # 每次打开时刷新一下下拉选项
        return True, _get_strategy_options()
    return False, no_update


@callback(
    Output("st-form-feedback", "children"),
    Output("st-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-st-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-st-save", "n_clicks"),
    State("st-form-type", "value"),
    State("st-form-maturity", "value"),
    State("st-form-desc", "value"),
    prevent_initial_call=True,
)
def cb_save_strategy(_, stype, maturity, desc):
    if not stype:
        return dbc.Alert("策略类型不能为空", color="danger"), no_update, no_update
    try:
        sid = add_strategy(strategy_type=stype, description=desc or "", evidence_maturity=maturity)
        return dbc.Alert(f"已创建/复用策略 {sid}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update


# ★ 保存新构建体逻辑
@callback(
    Output("c-form-feedback", "children"),
    Output("c-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-st-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-c-save", "n_clicks"),
    State("c-form-name", "value"),
    State("c-form-strategies", "value"),
    State("c-form-pathogens", "value"),
    State("c-form-status", "value"),
    prevent_initial_call=True,
)
def cb_save_construct(_, name, strategies, pathogens, status):
    if not name or not strategies:
        return dbc.Alert("名称和实现策略不能为空", color="danger"), no_update, no_update
    try:
        cid = f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"
        with get_driver().session() as s:
            # 1. 创建构建体节点
            s.run("""
                CREATE (ec:EngineeredPhageConstruct {
                    construct_id: $cid, public_name: $name,
                    construct_status: $status, review_status: 'pending',
                    created_at: datetime(), updated_at: datetime()
                })
            """, cid=cid, name=name, status=status)
            
            # 2. 关联策略
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                UNWIND $sids AS sid
                MATCH (es:EngineeringStrategy {strategy_id: sid})
                MERGE (ec)-[:IMPLEMENTS]->(es)
            """, cid=cid, sids=strategies)
            
            # 3. 关联病原
            if pathogens:
                for p in pathogens.split(","):
                    p = p.strip()
                    if p:
                        s.run("""
                            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                            MERGE (path:Pathogen {species: $sp})
                            ON CREATE SET path.pathogen_id = $pid
                            MERGE (ec)-[:TARGETS]->(path)
                        """, cid=cid, sp=p, pid=f"PATH-{uuid.uuid4().hex[:6].upper()}")
                        
        return dbc.Alert(f"已创建构建体 {cid}，策略关联成功", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update


# 策略审核：打开弹窗
@callback(
    Output("store-st-active", "data"),
    Output("modal-st-review", "is_open"),
    Output("modal-st-body", "children"),
    Input("st-grid", "cellClicked"),
    State("st-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_review(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update
    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update
    row = row_data[rowIndex]
    if row.get("actions") != "👉 确认审核":
        return no_update, no_update, no_update
    sid = row["id"]
    body = f"确认策略 [{row.get('type_cn')}] 的归类是否正确？\n描述：{row.get('description') or '无'}"
    return sid, True, body


# 策略审核：执行审核
@callback(
    Output("modal-st-review", "is_open", allow_duplicate=True),
    Output("btn-st-refresh", "n_clicks", allow_duplicate=True),
    Output("st-error-banner", "children", allow_duplicate=True),
    Input("btn-st-modal-approve", "n_clicks"),
    Input("btn-st-modal-reject", "n_clicks"),
    Input("btn-st-modal-cancel", "n_clicks"),
    State("store-st-active", "data"),
    prevent_initial_call=True,
)
def cb_do_review(approve_n, reject_n, cancel_n, sid):
    trigger = ctx.triggered_id
    if trigger == "btn-st-modal-cancel" or not sid:
        return False, no_update, no_update
    decision = "approved" if trigger == "btn-st-modal-approve" else "rejected"
    try:
        with get_driver().session() as s:
            s.run("MATCH (es:EngineeringStrategy {strategy_id: $sid}) SET es.review_status = $decision, es.updated_at = datetime()", sid=sid, decision=decision)
            rid = f"REV-{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                CREATE (r:Review {review_id: $rid, review_type: 'technical_intelligence_review', target_object_type: 'EngineeringStrategy', target_object_id: $sid, reviewer_id: 'dashboard_admin', decision: $decision, created_at: datetime()})
                CREATE (r)-[:REVIEWS]->(es)
            """, sid=sid, decision=decision, rid=rid)
        msg = dbc.Alert(f"策略 {sid} 已标记为【{STATUS_MAP.get(decision)}】", color="success", dismissable=True, duration=3000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"操作失败：{e}", color="danger", dismissable=True)