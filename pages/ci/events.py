# pages/ci/events.py
import uuid
import re
import json
import datetime
import requests
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

# 复用监控脚本
from scripts.monitor_runner import (
    _list_global_sources_raw, add_global_source, remove_global_source,
    make_session, html_to_text, collect_for_review, find_org_exact
)

from data_access.mutations import add_event
from config import get_driver, Config
from src.ci.organization_service import create_organization
from src.shared.evidence_source import create_source_artifact

dash.register_page(__name__, path="/ci/events", name="情报事件")

EVENT_TYPE_OPTIONS = [
    {"label": "管线更新", "value": "pipeline_update"},
    {"label": "临床试验更新", "value": "clinical_trial_update"},
    {"label": "监管事件", "value": "regulatory_update"},
    {"label": "论文发表", "value": "publication"},
    {"label": "专利事件", "value": "patent_event"},
    {"label": "合作事件", "value": "partnership"},
    {"label": "融资事件", "value": "funding"},
    {"label": "并购事件", "value": "acquisition"},
]

EVENT_TYPE_MAP = {
    "pipeline_update": "📈 管线更新",
    "clinical_trial_update": "🏥 临床更新",
    "regulatory_update": "⚖️ 监管事件",
    "publication": "📄 论文发表",
    "patent_event": "💡 专利事件",
    "partnership": "🤝 合作事件",
    "funding": "💰 融资事件",
    "acquisition": "🤝 并购事件",
}

STATUS_MAP = {
    "pending": "⏳ 待审核",
    "reviewed": "✅ 已确认",
    "disputed": "⚠️ 有争议"
}

COLUMNS = [
    {"field": "id", "headerName": "事件 ID", "width": 160, "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "title", "headerName": "标题", "flex": 2},
    {"field": "type_cn", "headerName": "类型", "width": 130},
    {"field": "org_name", "headerName": "归因组织", "width": 160},
    {"field": "event_date", "headerName": "日期", "width": 110, "sort": "desc"},
    {"field": "status_cn", "headerName": "状态", "width": 110},
    {"field": "actions", "headerName": "操作", "width": 130, "sortable": False, "filter": False, "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]

MONITOR_COLUMNS = [
    {"headerName": "", "checkboxSelection": True, "headerCheckboxSelection": True, "width": 60},
    {"field": "title", "headerName": "标题", "minWidth": 200, "flex": 1, "editable": True},
    {"field": "org_name", "headerName": "归因组织", "width": 150, "editable": True},
    {"field": "event_type", "headerName": "类型", "width": 110, "editable": True},
    {"field": "event_date", "headerName": "日期", "width": 110, "editable": True},
    {"field": "summary", "headerName": "事实摘要", "minWidth": 300, "flex": 2, "editable": True,
     "cellStyle": {"whiteSpace": "normal", "lineHeight": "1.5"}},
    {"field": "source_url", "headerName": "来源 URL", "width": 100, "hide": True},
]


def _fetch_events(keyword="", etype=""):
    try:
        with get_driver().session() as s:
            query = """
                MATCH (e:IntelligenceEvent)
                WHERE ($kw = '' OR e.event_id CONTAINS $kw OR e.title CONTAINS $kw)
                  AND ($etype = '' OR e.event_type = $etype)
                OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
                OPTIONAL MATCH (e)-[:HAS_SOURCE]->(src:SourceArtifact)
                RETURN e.event_id AS id, e.title AS title, e.event_type AS event_type,
                       e.event_date AS event_date, e.factual_summary AS summary,
                       e.review_status AS review_status, o.canonical_name AS org_name,
                       src.source_id AS source_id
                ORDER BY e.event_date DESC LIMIT 100
            """
            records = list(s.run(query, kw=keyword, etype=etype))
            
        rows = []
        for r in records:
            d = dict(r)
            st = str(d.get("review_status") or "pending").strip().lower()
            d["status_cn"] = STATUS_MAP.get(st, st)
            d["type_cn"] = EVENT_TYPE_MAP.get(d.get("event_type", ""), d.get("event_type", ""))
            d["actions"] = "👉 确认事实" if (st == "pending" or not d.get("review_status")) else "已确认"
            rows.append(d)
        return rows
    except Exception as e:
        print(f"[Events Fetch Error] {e}")
        return []


layout = html.Div([
    html.Div(id="ie-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("情报事件", className="page-title"),
            html.Div("管理所有 IntelligenceEvent · 归因组织 · SourceArtifact 溯源", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-gear me-1"), "监控中心"], id="btn-ie-monitor", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-globe me-1"), "URL 智能抓取"], id="btn-ie-fetch", className="btn-primary-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "手动新增"], id="btn-ie-new", className="btn-outline-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="ie-search", type="text", debounce=True, value="", placeholder="搜索 ID、标题或组织名…", className="filter-search"),
        dcc.Dropdown(id="ie-type-filter", options=[{"label": "全部类型", "value": ""}] + EVENT_TYPE_OPTIONS, value="", clearable=False, style={"width": "180px"}),
        html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"], id="btn-ie-refresh", className="btn-outline-custom"),
        html.Div(id="ie-count-label", style={"marginLeft": "auto", "fontSize": "12px", "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(id="ie-grid", columnDefs=COLUMNS, rowData=[], dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"}, style={"height": None, "minHeight": "420px"}),
    ]),

    # 手动新增
    dbc.Offcanvas(
        id="ie-offcanvas", title="手动新增情报事件", placement="end", is_open=False, style={"width": "520px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("标题 *", width=3), dbc.Col(dbc.Input(id="ie-form-title"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("事件类型", width=3), dbc.Col(dbc.Select(id="ie-form-type", options=EVENT_TYPE_OPTIONS, value="publication"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("组织 ID *", width=3), dbc.Col(dbc.Input(id="ie-form-org", placeholder="CI:ORG:XXXXXXXX"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("事件日期", width=3), dbc.Col(dbc.Input(id="ie-form-date", type="date"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("来源 URL", width=3), dbc.Col(dbc.Input(id="ie-form-src-url"), width=9)], className="mb-3"),
            dbc.Row([dbc.Label("摘要", width=3), dbc.Col(dbc.Textarea(id="ie-form-summary", rows=4), width=9)], className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-ie-cancel", className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"], id="btn-ie-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="ie-form-feedback", className="mt-3"),
        ])]),

    # 审核确认
    dcc.Store(id="store-ie-active"),
    dbc.Modal(
        id="modal-ie-review", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认情报事实")),
            dbc.ModalBody(id="modal-ie-body", children="确认该事件为真实事实吗？"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-ie-modal-cancel", className="btn-outline-custom me-2"),
                html.Button("✅ 确认入库", id="btn-ie-modal-approve", className="btn-primary-custom"),
            ]),
        ]
    ),

    # 监控中心
    dbc.Modal(
        id="modal-ie-monitor", is_open=False, size="lg", centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("监控中心")),
            dbc.ModalBody([
                dbc.InputGroup(className="mb-4", children=[
                    dbc.Input(id="monitor-new-url", placeholder="输入要长期监控的列表页/搜索页 URL (如搜狗微信搜索结果页)"),
                    dbc.Button([html.I(className="bi bi-plus-lg me-1"), "添加监控源"], id="btn-monitor-add", className="btn-outline-custom"),
                ]),
                html.Div(id="monitor-list-container", className="mb-4"),
                html.Hr(),
                html.Div([
                    html.Button([html.I(className="bi bi-play-fill me-1"), "一键抓取全部监控源 (最新 10 篇)"], id="btn-monitor-run", className="btn-primary-custom w-100 mb-2"),
                    html.Div(id="monitor-run-status")
                ])
            ]),
        ]
    ),

    # 单篇 URL 抓取弹窗
    dbc.Modal(
        id="modal-ie-fetch", is_open=False, size="lg", centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("单篇 URL 智能解析")),
            dbc.ModalBody([
                dbc.InputGroup(className="mb-3", children=[
                    dbc.Input(id="ie-fetch-url", placeholder="输入单篇文章链接 (如 https://mp.weixin.qq.com/s/...)"),
                    dbc.Button([html.I(className="bi bi-search me-1"), "解析网页"], id="btn-ie-do-fetch", className="btn-primary-custom"),
                ]),
                
                html.Div(id="ie-fetch-status"),
                
                html.Div(id="ie-fetch-form-container", style={"display": "none"}, children=[
                    dbc.Row([dbc.Label("标题", width=2), dbc.Col(dbc.Input(id="fetch-res-title"), width=10)], className="mb-2 mt-3"),
                    dbc.Row([dbc.Label("组织", width=2), dbc.Col(dbc.Input(id="fetch-res-org"), width=10)], className="mb-2"),
                    dbc.Row([dbc.Label("类型", width=2), dbc.Col(dbc.Input(id="fetch-res-type"), width=10)], className="mb-2"),
                    dbc.Row([dbc.Label("日期", width=2), dbc.Col(dbc.Input(id="fetch-res-date", type="date"), width=10)], className="mb-2"),
                    dbc.Row([dbc.Label("摘要", width=2), dbc.Col(dbc.Textarea(id="fetch-res-summary", rows=3), width=10)], className="mb-3"),
                    html.Button([html.I(className="bi bi-database-add me-1"), "确认并入库"], id="btn-ie-save-fetched", className="btn-primary-custom w-100"),
                ])
            ]),
        ]
    ),

    # 监控中心抓取结果批量入库弹窗
    dbc.Modal(
        id="modal-monitor-results", is_open=False, size="xl", centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("监控中心抓取结果")),
            dbc.ModalBody([
                dag.AgGrid(
                    id="monitor-results-grid", columnDefs=MONITOR_COLUMNS, rowData=[],
                    dashGridOptions={"rowSelection": "multiple", "domLayout": "autoHeight"},
                    style={"height": None, "minHeight": "300px", "maxHeight": "600px"}, 
                ),
                html.Button([html.I(className="bi bi-database-add me-1"), "将勾选的数据批量入库"], id="btn-monitor-save", className="btn-primary-custom w-100 mt-3"),
            ])
        ]
    )
])


# ============================================================
# 列表、手动新增、审核逻辑
# ============================================================
@callback(
    Output("ie-grid", "rowData"),
    Output("ie-count-label", "children"),
    Output("ie-error-banner", "children"),
    Input("btn-ie-refresh", "n_clicks"),
    Input("ie-search", "value"),
    Input("ie-type-filter", "value"),
    Input("btn-ie-modal-approve", "n_clicks"),
    Input("btn-ie-save-fetched", "n_clicks"),
    Input("btn-monitor-save", "n_clicks"),
)
def cb_load(_, search, etype, __, ___, ____):
    try:
        rows = _fetch_events(keyword=search or "", etype=etype or "")
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}", color="danger", className="mb-3")

@callback(
    Output("ie-offcanvas", "is_open"),
    Input("btn-ie-new", "n_clicks"),
    Input("btn-ie-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-ie-new"

@callback(
    Output("ie-form-feedback", "children"),
    Output("ie-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-ie-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-ie-save", "n_clicks"),
    State("ie-form-title", "value"),
    State("ie-form-type", "value"),
    State("ie-form-org", "value"),
    State("ie-form-date", "value"),
    State("ie-form-src-url", "value"),
    State("ie-form-summary", "value"),
    prevent_initial_call=True,
)
def cb_save(_, title, etype, org_id, event_date, src_url, summary):
    if not title or not (org_id or "").strip():
        return dbc.Alert("标题和组织 ID 不能为空", color="danger"), no_update, no_update
    try:
        event_id = add_event(event_type=etype, title=title, factual_summary=summary or "", organization_id=org_id.strip(), event_date=event_date, source_url=src_url)
        return dbc.Alert(f"已创建 {event_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update

@callback(
    Output("store-ie-active", "data"),
    Output("modal-ie-review", "is_open"),
    Output("modal-ie-body", "children"),
    Input("ie-grid", "cellClicked"),
    State("ie-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_review(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update
    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update
    row = row_data[rowIndex]
    if row.get("actions") != "👉 确认事实":
        return no_update, no_update, no_update
    evt_id = row["id"]
    body = f"是否确认事件 [{row.get('title')}] 的真实性？\n确认后将可用于生成竞争简报。"
    return evt_id, True, body

@callback(
    Output("modal-ie-review", "is_open", allow_duplicate=True),
    Output("btn-ie-refresh", "n_clicks", allow_duplicate=True),
    Output("ie-error-banner", "children", allow_duplicate=True),
    Input("btn-ie-modal-approve", "n_clicks"),
    Input("btn-ie-modal-cancel", "n_clicks"),
    State("store-ie-active", "data"),
    prevent_initial_call=True,
)
def cb_do_review(approve_n, cancel_n, evt_id):
    trigger = ctx.triggered_id
    if trigger == "btn-ie-modal-cancel" or not evt_id:
        return False, no_update, no_update
    try:
        with get_driver().session() as s:
            s.run("MATCH (e:IntelligenceEvent {event_id: $eid}) SET e.review_status = 'reviewed', e.updated_at = datetime()", eid=evt_id)
            rid = f"REV-{uuid.uuid4().hex[:8].upper()}"
            s.run("""
                MATCH (e:IntelligenceEvent {event_id: $eid})
                CREATE (r:Review {review_id: $rid, review_type: 'ci_fact_review', target_object_type: 'IntelligenceEvent', target_object_id: $eid, reviewer_id: 'dashboard_admin', decision: 'approved', created_at: datetime()})
                CREATE (r)-[:REVIEWS]->(e)
            """, eid=evt_id, rid=rid)
        msg = dbc.Alert(f"事件 {evt_id} 已确认为真实事实。", color="success", dismissable=True, duration=3000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"操作失败：{e}", color="danger", dismissable=True)


# ============================================================
# 监控中心逻辑
# ============================================================
@callback(
    Output("modal-ie-monitor", "is_open"),
    Output("monitor-list-container", "children"),
    Input("btn-ie-monitor", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_monitor_modal(n):
    sources = _list_global_sources_raw(get_driver())
    if not sources:
        list_ui = dbc.Alert("暂无配置的监控源", color="info")
    else:
        items = []
        for s in sources:
            items.append(
                html.Div([
                    html.Span(s['label'] or s['url'], style={"fontWeight": "600"}),
                    html.Span(s['url'], style={"fontSize": "12px", "color": "#888", "marginLeft": "10px"}),
                    html.Button("删除", id={"type": "btn-del-monitor", "index": s['source_id']}, className="btn-danger-custom", style={"float": "right", "padding": "2px 8px", "fontSize": "12px"})
                ], style={"padding": "8px 0", "borderBottom": "1px solid #eee"})
            )
        list_ui = html.Div(items)
    return True, list_ui

@callback(
    Output("monitor-new-url", "value"),
    Output("monitor-list-container", "children", allow_duplicate=True),
    Input("btn-monitor-add", "n_clicks"),
    State("monitor-new-url", "value"),
    prevent_initial_call=True,
)
def add_monitor_url(n, url):
    if not url: return no_update, no_update
    try:
        stype = "sogou_wechat" if "weixin.sogou.com" in url else "mixed"
        add_global_source(url, stype, "自定义监控")
        sources = _list_global_sources_raw(get_driver())
        items = []
        for s in sources:
            items.append(
                html.Div([
                    html.Span(s['label'] or s['url'], style={"fontWeight": "600"}),
                    html.Span(s['url'], style={"fontSize": "12px", "color": "#888", "marginLeft": "10px"}),
                    html.Button("删除", id={"type": "btn-del-monitor", "index": s['source_id']}, className="btn-danger-custom", style={"float": "right", "padding": "2px 8px", "fontSize": "12px"})
                ], style={"padding": "8px 0", "borderBottom": "1px solid #eee"})
            )
        return "", html.Div(items)
    except Exception as e:
        return no_update, dbc.Alert(f"添加失败: {e}", color="danger")

@callback(
    Output("monitor-list-container", "children", allow_duplicate=True),
    Input({"type": "btn-del-monitor", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def del_monitor_url(n_clicks_list):
    if not any(n_clicks_list): return no_update
    trigger = ctx.triggered_id
    if not trigger or "index" not in trigger: return no_update
    try:
        remove_global_source(trigger["index"])
        sources = _list_global_sources_raw(get_driver())
        items = []
        for s in sources:
            items.append(
                html.Div([
                    html.Span(s['label'] or s['url'], style={"fontWeight": "600"}),
                    html.Span(s['url'], style={"fontSize": "12px", "color": "#888", "marginLeft": "10px"}),
                    html.Button("删除", id={"type": "btn-del-monitor", "index": s['source_id']}, className="btn-danger-custom", style={"float": "right", "padding": "2px 8px", "fontSize": "12px"})
                ], style={"padding": "8px 0", "borderBottom": "1px solid #eee"})
            )
        return html.Div(items)
    except Exception:
        return no_update

@callback(
    Output("monitor-run-status", "children"),
    Output("monitor-results-grid", "rowData"),
    Output("modal-monitor-results", "is_open"),
    Input("btn-monitor-run", "n_clicks"),
    prevent_initial_call=True,
)
def run_monitor(n):
    try:
        result = collect_for_review(time_filter="week")
        events = result.get("events", [])
        
        extracted_rows = []
        for e in events:
            org_name = e.get("organization_name", "").strip()
            if not org_name:
                org_name = "⚠️ 未识别组织"

            extracted_rows.append({
                "title": e.get("title"),
                "org_name": org_name,
                "event_type": e.get("event_type", "publication"),
                "event_date": e.get("event_date", ""),
                "summary": e.get("factual_summary", ""),
                "source_url": e.get("_source_url", "")
            })
            
        if not extracted_rows:
            return dbc.Alert("抓取完成，但没有发现新事件。", color="info"), [], False
            
        return no_update, extracted_rows, True
    except Exception as e:
        return dbc.Alert(f"运行失败: {e}", color="danger"), [], False


# ============================================================
# 单篇 URL 抓取逻辑
# ============================================================
@callback(
    Output("modal-ie-fetch", "is_open", allow_duplicate=True),
    Input("btn-ie-fetch", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_fetch_modal(n):
    return True

def _extract_date_from_html(html_text):
    """
    从 HTML 源码中提取日期。
    针对微信公众号等动态渲染页面增加了时间戳解析。
    """
    if not html_text:
        return ""
    
    # 1. 微信特有的 JS 变量时间戳匹配 (10 位秒级时间戳)
    wechat_ts_patterns = [
        r'var\s+ct\s*=\s*"(\d{10})"',
        r'var\s+create_time\s*=\s*"(\d{10})"',
        r'create_time\s*[:=]\s*["\']?(\d{10})',
        r'msg_publish_time\s*[:=]\s*["\']?(\d{10})',
    ]
    for p in wechat_ts_patterns:
        m = re.search(p, html_text)
        if m:
            ts = int(m.group(1))
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

    # 2. 标准 Meta 标签
    meta_patterns = [
        r'<meta[^>]+property="article:published_time"[^>]+content="([^"]+)"',
        r'<meta[^>]+name="publish_date"[^>]+content="([^"]+)"',
        r'<meta[^>]+property="og:release_date"[^>]+content="([^"]+)"',
    ]
    for p in meta_patterns:
        m = re.search(p, html_text, re.IGNORECASE)
        if m:
            return m.group(1).strip()[:10]

    # 3. 普通文本正则匹配兜底
    m = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})', html_text)
    if m:
        date_str = m.group(1).replace("年", "-").replace("月", "-").replace("日", "")
        return date_str.strip()[:10]
        
    return ""

@callback(
    Output("ie-fetch-status", "children"),
    Output("ie-fetch-form-container", "style"),
    Output("fetch-res-title", "value"),
    Output("fetch-res-org", "value"),
    Output("fetch-res-type", "value"),
    Output("fetch-res-date", "value"),
    Output("fetch-res-summary", "value"),
    Input("btn-ie-do-fetch", "n_clicks"),
    State("ie-fetch-url", "value"),
    prevent_initial_call=True,
)
def cb_fetch_url(n, url):
    if not url or not url.startswith("http"):
        return dbc.Alert("请输入合法的 URL", color="warning"), {"display": "none"}, no_update, no_update, no_update, no_update, no_update

    session = make_session()
    # ★ 增加伪装浏览器 headers，防止被微信拦截
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    try:
        r = session.get(url, headers=headers, timeout=15)
        r.encoding = r.apparent_encoding or "utf-8"
        html_text = r.text
        text = html_to_text(html_text)[:5000]
    except Exception as e:
        return dbc.Alert(f"抓取网页失败：{e}", color="danger"), {"display": "none"}, no_update, no_update, no_update, no_update, no_update

    html_date = _extract_date_from_html(html_text)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)
        prompt = f"""请从以下网页正文中提取“竞争情报事件”。只输出严格的 JSON。
要求：
{{
  "title": "事件简明标题（中文）",
  "event_type": "pipeline_update/clinical_trial_update/regulatory_update/publication/patent_event/partnership/funding/acquisition 选其一",
  "factual_summary": "事实摘要（中文，100字内）",
  "organization_name": "涉及的外部公司名称",
  "event_date": "YYYY-MM-DD (如果正文中没有明确日期，请留空字符串)"
}}
网页正文：
{text}"""
        res = client.chat.completions.create(
            model=Config.DS_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        data = json.loads(res.choices[0].message.content)
    except Exception as e:
        return dbc.Alert(f"大模型提取失败：{e}", color="danger"), {"display": "none"}, no_update, no_update, no_update, no_update, no_update

    # ★ 日期智能判断逻辑
    llm_date = (data.get("event_date") or "").strip()
    
    # 如果模型提取出了合法日期，且不是明显错误的 1月1号（通常是模型瞎猜的）
    if re.match(r'^\d{4}-\d{2}-\d{2}$', llm_date) and not llm_date.endswith("-01-01"):
        real_date = llm_date
    elif html_date:  
        # 否则优先使用 HTML 解析出的真实时间戳
        real_date = html_date
    elif re.match(r'^\d{4}-\d{2}-\d{2}$', llm_date):
        # 兜底用模型的
        real_date = llm_date
    else:
        # 最后兜底用今天
        real_date = datetime.date.today().strftime("%Y-%m-%d")

    return (
        dbc.Alert("✅ 提取成功，请核对信息后点击下方确认按钮入库：", color="success"),
        {"display": "block"},
        data.get("title"),
        data.get("organization_name"),
        data.get("event_type"),
        real_date,
        data.get("factual_summary"),
    )

@callback(
    Output("modal-ie-fetch", "is_open", allow_duplicate=True),
    Output("btn-ie-refresh", "n_clicks", allow_duplicate=True),
    Output("ie-error-banner", "children", allow_duplicate=True),
    Input("btn-ie-save-fetched", "n_clicks"),
    State("fetch-res-title", "value"),
    State("fetch-res-org", "value"),
    State("fetch-res-type", "value"),
    State("fetch-res-date", "value"),
    State("fetch-res-summary", "value"),
    State("ie-fetch-url", "value"),
    prevent_initial_call=True,
)
def cb_save_fetched(n, title, org_name, etype, date, summary, url):
    if not n: return no_update, no_update, no_update
    if not title or not org_name:
        return no_update, no_update, dbc.Alert("标题和组织名称不能为空", color="danger")
    try:
        _save_single_event(title, org_name, etype, date, summary, url)
        msg = dbc.Alert(f"成功抓取入库：{title}", color="success", dismissable=True, duration=4000)
        return False, 1, msg
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"入库失败：{e}", color="danger")


# ============================================================
# 监控结果批量入库 (带拦截校验)
# ============================================================
@callback(
    Output("modal-monitor-results", "is_open", allow_duplicate=True),
    Output("btn-ie-refresh", "n_clicks", allow_duplicate=True),
    Output("ie-error-banner", "children", allow_duplicate=True),
    Input("btn-monitor-save", "n_clicks"),
    State("monitor-results-grid", "selectedRows"),
    prevent_initial_call=True,
)
def cb_save_monitor_results(n, selected_rows):
    if not n: return no_update, no_update, no_update
    if not selected_rows:
        return no_update, no_update, dbc.Alert("请先在表格中勾选需要入库的事件", color="warning")
    
    # ★ 入库前拦截检查：如果有未识别组织，阻止入库
    missing_orgs = [r for r in selected_rows if not r.get("org_name") or r.get("org_name") == "⚠️ 未识别组织"]
    if missing_orgs:
        return no_update, no_update, dbc.Alert(
            f"有 {len(missing_orgs)} 条数据的组织为空或未识别。请双击表格中的【归因组织】列，补充完整后再点击入库！", 
            color="warning", dismissable=True
        )

    success_count = 0
    try:
        for row in selected_rows:
            _save_single_event(
                title=row.get("title"), 
                org_name=row.get("org_name"), 
                etype=row.get("event_type", "publication"), 
                date=row.get("event_date", ""), 
                summary=row.get("summary", ""), 
                url=row.get("source_url", "")
            )
            success_count += 1
        msg = dbc.Alert(f"成功批量入库 {success_count} 条情报事件！", color="success", dismissable=True, duration=4000)
        return False, 1, msg
    except Exception as e:
        return no_update, no_update, dbc.Alert(f"批量入库失败：{e}", color="danger")


# 内部公共入库函数
def _save_single_event(title, org_name, etype, date, summary, url):
    if not title or not org_name:
        raise ValueError("标题和组织不能为空")
    with get_driver().session() as s:
        org_res = s.run("MATCH (o:Organization) WHERE toLower(o.canonical_name) = toLower($name) RETURN o.organization_id AS oid LIMIT 1", name=org_name).single()
        if org_res:
            org_id = org_res["oid"]
        else:
            org_id = create_organization(get_driver(), canonical_name=org_name, organization_type="biotech", actor_id="llm_fetcher")

        src_id = create_source_artifact(
            get_driver(), source_type="url_scrape", title=title, 
            url=url, published_date=date or "unknown", credibility_tier="secondary", actor_id="llm_fetcher"
        )

        evt_id = f"CI:EVT:{uuid.uuid4().hex[:8].upper()}"
        s.run("""
            CREATE (e:IntelligenceEvent {
                event_id: $eid, event_type: $etype, title: $title, factual_summary: $summary,
                event_date: $date, review_status: 'pending', organization_id: $oid,
                created_at: datetime(), discovered_at: datetime()
            })
            WITH e
            MATCH (o:Organization {organization_id: $oid})
            CREATE (e)-[:INVOLVES]->(o)
            WITH e
            MATCH (src:SourceArtifact {source_id: $sid})
            CREATE (e)-[:HAS_SOURCE]->(src)
        """, eid=evt_id, etype=etype, title=title, summary=summary, date=date, oid=org_id, sid=src_id)