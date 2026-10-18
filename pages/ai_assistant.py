# pages/ai_assistant.py
import json
import urllib.parse
import re
from datetime import datetime

import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc

from data_access.queries import _run
from config import Config

dash.register_page(__name__, path="/ai-assistant", name="AI 助手")

# ============================================================
# 意图路由表（保留你原有的快捷路由，确保高频问题极速响应）
# ============================================================
INTENT_ROUTES = {
    "待审核": {
        "label": "证据包审核状态",
        "cypher": """
            MATCH (pkg:ScientificEvidencePackage)
            OPTIONAL MATCH (r:Review)-[:REVIEWS]->(pkg)
            RETURN pkg.package_id AS id, pkg.package_type AS type, pkg.status AS status,
                   pkg.review_status AS review_status, r.decision AS last_review,
                   pkg.generated_by AS generated_by, pkg.created_at AS created_at
            ORDER BY pkg.created_at DESC LIMIT 15
        """,
    },
    "复用": {
        "label": "噬菌体裂解谱 Top 15",
        "cypher": """
            MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
            WITH ph, count(DISTINCT h) AS host_count, collect(DISTINCT h.strain_label)[..5] AS sample_hosts
            RETURN ph.phage_id AS id, ph.name AS name, host_count AS coverage, sample_hosts AS sample_hosts
            ORDER BY coverage DESC LIMIT 15
        """,
    },
    "本月": {
        "label": "最近 15 条情报事件",
        "cypher": """
            MATCH (e:IntelligenceEvent)
            OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
            RETURN e.event_id AS id, e.title AS title, e.event_type AS type,
                   e.event_date AS date, e.materiality AS impact, o.canonical_name AS org_name
            ORDER BY e.event_date DESC LIMIT 15
        """,
    },
    "高风险": {
        "label": "决策记录",
        "cypher": """
            MATCH (d:DecisionRecord)
            OPTIONAL MATCH (d)-[:BASED_ON]->(b:IntelligenceProduct)
            RETURN d.decision_id AS id, d.decision_summary AS summary, d.decision_type AS type,
                   d.decision_owner AS owner, d.outcome_status AS status, b.brief_id AS brief_id, d.decided_at AS decided_at
            ORDER BY d.decided_at DESC LIMIT 15
        """,
    },
    "未关联": {
        "label": "未关联病原体的开发项目",
        "cypher": """
            MATCH (p:DevelopmentProgram)
            WHERE NOT EXISTS { MATCH (p)-[:TARGETS_PATHOGEN]->(:Pathogen) }
            OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(p)
            RETURN p.program_id AS id, p.canonical_name AS name, p.development_stage AS stage,
                   p.program_status AS status, o.canonical_name AS org_name
            ORDER BY p.canonical_name LIMIT 15
        """,
    },
    "今日": {
        "label": "最近 20 条审计事件",
        "cypher": """
            MATCH (a:AuditEvent)
            RETURN a.audit_id AS id, a.action_type AS action, a.object_type AS object_type,
                   a.object_id AS object_id, a.actor_id AS actor, a.timestamp AS ts
            ORDER BY a.timestamp DESC LIMIT 20
        """,
    },
}

QUICK_PROMPTS = [
    "最近待审核的证据包有哪些？",
    "哪个噬菌体在克雷伯菌宿主复用率最高？",
    "新增了哪些情报事件？",
    "当前有哪些高风险的决策记录？",
    "列出所有未关联病原体的开发项目",
    "今日审计事件摘要",
]

SYSTEM_PROMPT = """你是 AI 助手，帮助用户查询噬菌体精准治疗平台的 Ontology 数据。
规则：
1. 只能基于用户消息中提供的 JSON 数据回答，禁止编造。
2. 数据不足时明确告知用户。
3. 回答简洁清晰，适当使用列表。
4. 用中文回答。
5. 不要提及「根据提供的 JSON 数据」之类的话，直接给出结论。
"""

# ============================================================
# 给大模型看的 Neo4j Schema 提示词（用于生成 Cypher）
# ============================================================
SCHEMA_PROMPT = """你是 Neo4j Cypher 专家。请根据用户的自然语言提问，生成一条 Cypher 查询语句。
已知数据库中有以下节点和属性：
- (p:Phage) 属性: phage_id, name, family, receptor_target
- (p:Pathogen) 属性: pathogen_id, species, resistance_mechanism
- (h:HostStrain) 属性: host_strain_id, strain_label
- (a:LysisAssay) 属性: assay_id, result (Lytic/Non-lytic), result_value, evidence_level (L1-L5), qc_status
- (c:ClinicalCase) 属性: case_id, infection_type, clinical_outcome
- (pkg:ScientificEvidencePackage) 属性: package_id, status, review_status
- (e:IntelligenceEvent) 属性: event_id, title, event_type, event_date, review_status
- (o:Organization) 属性: organization_id, canonical_name, organization_type, headquarters_country
- (p:DevelopmentProgram) 属性: program_id, canonical_name, development_stage, program_status
- (d:DecisionRecord) 属性: decision_id, decision_summary, decision_type, outcome_status
- (s:EngineeringStrategy) 属性: strategy_id, strategy_type, evidence_maturity

已知关系：
- (Phage)-[:USED_IN]->(LysisAssay)
- (LysisAssay)-[:TESTED_AGAINST]->(HostStrain)
- (HostStrain)-[:IS_STRAIN_OF]->(Pathogen)
- (ClinicalCase)-[:INVOLVES_PATHOGEN]->(Pathogen)
- (ClinicalCase)-[:TREATED_WITH]->(Phage)
- (ScientificEvidencePackage)-[:INCLUDES_CANDIDATE]->(Phage)
- (IntelligenceEvent)-[:INVOLVES]->(Organization)
- (Organization)-[:DEVELOPS]->(DevelopmentProgram)
- (DevelopmentProgram)-[:TARGETS_PATHOGEN]->(Pathogen)
- (DevelopmentProgram)-[:USES_STRATEGY]->(EngineeringStrategy)
- (DecisionRecord)-[:BASED_ON]->(IntelligenceProduct)

要求：
1. 只能生成只读的 MATCH/RETURN 查询，绝不能包含 CREATE/DELETE/SET/MERGE 等写操作。
2. 使用 toLower() 进行模糊匹配，比如 WHERE toLower(o.canonical_name) CONTAINS toLower('biomx')。
3. 查询结果限制在 20 条以内，必须在末尾加上 LIMIT 20。
4. 返回字段请使用 AS 重命名，使其易于阅读（如 AS id, AS title）。
5. 只输出纯 JSON 格式：{"cypher": "MATCH ... RETURN ..."}，不要包含任何 Markdown 标记。
"""


# ============================================================
# 辅助函数
# ============================================================
def _route_intent(query: str):
    if not query:
        return None, None
    for kw, route in INTENT_ROUTES.items():
        if kw in query:
            return kw, route
    return None, None


def _call_deepseek(question: str, data_str: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)
        resp = client.chat.completions.create(
            model=Config.DS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"用户问题：{question}\n\n检索到的数据：\n{data_str}"},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return resp.choices[0].message.content or "（LLM 返回为空）"
    except Exception as e:
        return f"⚠️ LLM 调用失败：{e}"


def _generate_cypher(question: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=Config.DS_API_KEY, base_url=Config.DS_BASE_URL)
    try:
        resp = client.chat.completions.create(
            model=Config.DS_MODEL,
            messages=[
                {"role": "system", "content": SCHEMA_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        data = json.loads(resp.choices[0].message.content)
        return data.get("cypher", "")
    except Exception as e:
        raise ValueError(f"大模型生成 Cypher 失败: {e}")


# ============================================================
# 页面布局（完整版，无省略）
# ============================================================
layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("AI 助手", className="page-title"),
            html.Div("自然语言查询 · 结构化检索 · DeepSeek 负责格式化", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-trash3 me-1"), "清空对话"],
                        id="btn-ai-clear", className="btn-outline-custom"),
        ]),
    ]),

    html.Div(className="surface-card", style={"padding": "0"}, children=[
        # 消息区
        html.Div(
            id="ai-messages",
            style={"height": "500px", "overflowY": "auto", "padding": "20px", "background": "var(--c-bg)"},
            children=[
                html.Div([
                    html.I(className="bi bi-stars", style={"fontSize": "48px", "color": "var(--c-primary-light)"}),
                    html.Div(" AI 助手", style={"fontSize": "18px", "fontWeight": "700", "marginTop": "16px"}),
                    html.Div("向我询问平台里的 Ontology 数据", style={"color": "var(--c-text-muted)", "marginTop": "6px", "fontSize": "13px"}),
                ], style={"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center", "height": "100%", "color": "var(--c-text-muted)"}),
            ],
        ),
        # 快捷提示
        html.Div(
            [html.Button(p, id={"type": "ai-quick", "index": i}, className="btn-outline-custom", style={"fontSize": "12px", "margin": "0 6px 6px 0"}) for i, p in enumerate(QUICK_PROMPTS)],
            style={"padding": "10px 20px", "borderTop": "1px solid var(--c-border)", "background": "var(--c-surface)"},
        ),
        # 输入区
        html.Div([
            dcc.Textarea(
                id="ai-input",
                placeholder="输入问题，例如：BiomX 最近有什么新闻？",
                style={"flex": "1", "border": "1px solid var(--c-border)", "borderRadius": "6px", "padding": "10px 14px", "fontSize": "14px", "resize": "none", "minHeight": "42px", "fontFamily": "inherit"},
                value="", rows=1,
            ),
            html.Button([html.I(className="bi bi-send-fill")], id="btn-ai-send", className="btn-primary-custom", style={"padding": "10px 16px"}),
        ], style={"display": "flex", "gap": "8px", "padding": "12px 20px", "borderTop": "1px solid var(--c-border)", "background": "var(--c-surface)"}),
    ]),

    html.Div(
        [html.I(className="bi bi-shield-check me-1", style={"color": "var(--c-secondary)"}),
         "所有回答基于结构化检索，DeepSeek 仅用于文本格式化，不替代专家判断，不产生未经溯源的事实。"],
        style={"fontSize": "11px", "color": "var(--c-text-muted)", "textAlign": "center", "padding": "12px 0"},
    ),

    dcc.Store(id="store-ai-history", data=[]),
])


# ============================================================
# 回调 1：快捷提示 → 填入输入框
# ============================================================
@callback(
    Output("ai-input", "value", allow_duplicate=True),
    Input({"type": "ai-quick", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cb_fill_quick(n_clicks_list):
    from dash import ctx
    if not ctx.triggered_id:
        return no_update
    idx = ctx.triggered_id["index"]
    return QUICK_PROMPTS[idx]


# ============================================================
# 回调 2：清空对话
# ============================================================
@callback(
    Output("ai-messages", "children", allow_duplicate=True),
    Output("store-ai-history", "data", allow_duplicate=True),
    Input("btn-ai-clear", "n_clicks"),
    prevent_initial_call=True,
)
def cb_clear(_):
    empty = [
        html.Div([
            html.I(className="bi bi-stars", style={"fontSize": "48px", "color": "var(--c-primary-light)"}),
            html.Div(" AI 助手", style={"fontSize": "18px", "fontWeight": "700", "marginTop": "16px"}),
            html.Div("向我询问平台里的 Ontology 数据", style={"color": "var(--c-text-muted)", "marginTop": "6px", "fontSize": "13px"}),
        ], style={"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center", "height": "100%", "color": "var(--c-text-muted)"}),
    ]
    return empty, []


# ============================================================
# 回调 3：发送消息（集成动态 Cypher 查询）
# ============================================================
@callback(
    Output("ai-messages", "children", allow_duplicate=True),
    Output("store-ai-history", "data", allow_duplicate=True),
    Output("ai-input", "value", allow_duplicate=True),
    Input("btn-ai-send", "n_clicks"),
    State("ai-input", "value"),
    State("store-ai-history", "data"),
    prevent_initial_call=True,
)
def cb_send(n_clicks, user_input, history):
    if not user_input or not user_input.strip():
        return no_update, no_update, no_update

    query = user_input.strip()
    ts = datetime.now().strftime("%H:%M")
    history = history or []
    history.append({"role": "user", "content": query, "ts": ts})

    kw, route = _route_intent(query)
    source_ids = []
    matched_label = None
    generated_cypher = None

    if route:
        # 1. 命中固定意图
        matched_label = route.get("label", kw)
        try:
            raw = _run(route["cypher"])
            data_str = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
            source_ids = [str(r.get("id", "")) for r in raw[:5] if r.get("id")]
            if not raw:
                data_str = "（查询成功，但结果为空）"
        except Exception as e:
            raw = []
            data_str = f"（检索失败：{e}）"
        answer = _call_deepseek(query, data_str)
    else:
        # 2. 未命中，动态生成 Cypher
        matched_label = "🤖 AI 动态图谱检索"
        try:
            generated_cypher = _generate_cypher(query)
            
            # 安全检查：防御恶意写操作
            forbidden = ["CREATE", "DELETE", "SET ", "MERGE", "REMOVE", "DROP"]
            if any(f in generated_cypher.upper() for f in forbidden):
                raise ValueError("安全拦截：生成的 Cypher 包含非法写操作。")

            raw = _run(generated_cypher)
            data_str = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
            source_ids = [str(r.get("id", "")) for r in raw[:5] if r.get("id")]
            
            if not raw:
                answer = "我尝试查询了图谱，但没有找到符合条件的数据。你可以换个问法试试。"
            else:
                answer = _call_deepseek(query, data_str)
                
        except Exception as e:
            answer = f"我在理解你的问题时遇到了困难：{e}\n\n请尝试更具体地提问，或者使用下方的快捷提问。"

    history.append({
        "role": "assistant",
        "content": answer,
        "ts": datetime.now().strftime("%H:%M"),
        "source_ids": source_ids,
        "matched_label": matched_label,
        "cypher": generated_cypher,
    })

    # 渲染消息列表
    children = []
    for msg in history:
        if msg["role"] == "user":
            children.append(html.Div([
                html.Div(msg["content"], style={"background": "var(--c-primary)", "color": "#fff", "padding": "10px 14px", "borderRadius": "12px 12px 4px 12px", "maxWidth": "75%", "fontSize": "13px", "lineHeight": "1.6"}),
                html.Div(msg["ts"], style={"fontSize": "10px", "color": "var(--c-text-muted)", "marginTop": "4px", "textAlign": "right"}),
            ], style={"display": "flex", "flexDirection": "column", "alignItems": "flex-end", "marginBottom": "12px"}))
        else:
            bubble = []
            if msg.get("matched_label"):
                bubble.append(html.Div(
                    f"🎯 {msg['matched_label']}",
                    style={"fontSize": "11px", "color": "var(--c-primary)", "marginBottom": "6px", "fontStyle": "italic"}))
                
            bubble.append(html.Div(msg["content"],
                         style={"background": "var(--c-surface)", "border": "1px solid var(--c-border)", "padding": "12px 16px", "borderRadius": "12px 12px 12px 4px", "maxWidth": "85%", "fontSize": "13px", "lineHeight": "1.7", "whiteSpace": "pre-wrap"}))
            
            # 如果是动态生成的 Cypher，展示在气泡下方
            if msg.get("cypher"):
                bubble.append(html.Details([
                    html.Summary("查看生成的 Cypher 语句", style={"fontSize": "11px", "color": "var(--c-text-muted)", "cursor": "pointer", "marginTop": "4px"}),
                    html.Pre(msg["cypher"], style={"fontSize": "11px", "background": "var(--c-bg)", "padding": "8px", "borderRadius": "4px", "marginTop": "4px", "overflowX": "auto"})
                ]))

            if msg.get("source_ids"):
                bubble.append(html.Div(
                    [html.Span(f"[来源：{sid}]", style={"background": "var(--c-bg)", "border": "1px solid var(--c-border)", "borderRadius": "4px", "padding": "1px 6px", "marginRight": "4px", "fontFamily": "monospace", "fontSize": "10px", "color": "var(--c-text-muted)"}) for sid in msg["source_ids"][:5]],
                    style={"marginTop": "6px"}))
            bubble.append(html.Div(msg["ts"], style={"fontSize": "10px", "color": "var(--c-text-muted)", "marginTop": "4px"}))
            children.append(html.Div(bubble, style={"display": "flex", "flexDirection": "column", "alignItems": "flex-start", "marginBottom": "12px"}))

    return children, history, ""


# ============================================================
# 回调 4：URL ?q= 参数预填
# ============================================================
@callback(
    Output("ai-input", "value", allow_duplicate=True),
    Input("url", "search"),
    prevent_initial_call=True,
)
def cb_prefill_from_url(search):
    if not search:
        return no_update
    params = urllib.parse.parse_qs(search.lstrip("?"))
    q = params.get("q", [""])[0]
    return q if q else no_update