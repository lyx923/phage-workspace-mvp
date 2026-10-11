# pages/ai_assistant.py
import json
import urllib.parse
from datetime import datetime

import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc

from data_access.queries import _run
from config import Config

dash.register_page(__name__, path="/ai-assistant", name="AI 助手")


# ============================================================
# 意图路由表
# ------------------------------------------------------------
# ⚠️ 顺序敏感：dict 遍历时第一个命中的关键词胜出
#    - 6 个快捷提问的专属意图放最前（优先级最高）
#    - 通用意图放后面做兜底
#    - 英文别名（DecisionRecord 等）也要有，避免用户输入英文匹配不到
# ============================================================
INTENT_ROUTES = {
    # ─────────── 快捷提问专属意图（6 个，优先命中） ───────────
    "待审核": {
        "label": "证据包审核状态",
        "cypher": """
            MATCH (pkg:ScientificEvidencePackage)
            OPTIONAL MATCH (r:Review)-[:REVIEWS]->(pkg)
            RETURN pkg.package_id AS id,
                   pkg.package_type AS type,
                   pkg.status AS status,
                   pkg.review_status AS review_status,
                   r.decision AS last_review,
                   pkg.generated_by AS generated_by,
                   pkg.created_at AS created_at
            ORDER BY pkg.created_at DESC LIMIT 15
        """,
    },
    "复用": {
        "label": "噬菌体裂解谱 Top 15（按覆盖宿主菌株数）",
        "cypher": """
            MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
            WITH ph,
                 count(DISTINCT h) AS host_count,
                 collect(DISTINCT h.strain_label)[..5] AS sample_hosts
            RETURN ph.phage_id AS id,
                   ph.name AS name,
                   host_count AS coverage,
                   sample_hosts AS sample_hosts
            ORDER BY coverage DESC
            LIMIT 15
        """,
    },
    "本月": {
        "label": "最近 15 条情报事件",
        "cypher": """
            MATCH (e:IntelligenceEvent)
            OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
            RETURN e.event_id AS id,
                   e.title AS title,
                   e.event_type AS type,
                   e.event_date AS date,
                   e.materiality AS impact,
                   o.canonical_name AS org_name
            ORDER BY e.event_date DESC
            LIMIT 15
        """,
    },
    "高风险": {
        "label": "决策记录（按类型分类）",
        "cypher": """
            MATCH (d:DecisionRecord)
            OPTIONAL MATCH (d)-[:BASED_ON]->(b:IntelligenceProduct)
            RETURN d.decision_id AS id,
                   d.decision_summary AS summary,
                   d.decision_type AS type,
                   d.decision_owner AS owner,
                   d.outcome_status AS status,
                   b.brief_id AS brief_id,
                   d.decided_at AS decided_at
            ORDER BY d.decided_at DESC
            LIMIT 15
        """,
    },
    "未关联": {
        "label": "未关联 Pathogen 的开发项目",
        "cypher": """
            MATCH (p:DevelopmentProgram)
            WHERE NOT EXISTS {
                MATCH (p)-[:TARGETS_PATHOGEN]->(:Pathogen)
            }
            OPTIONAL MATCH (o:Organization)-[:DEVELOPS]->(p)
            RETURN p.program_id AS id,
                   p.canonical_name AS name,
                   p.development_stage AS stage,
                   p.program_status AS status,
                   o.canonical_name AS org_name
            ORDER BY p.canonical_name
            LIMIT 15
        """,
    },
    "今日": {
        "label": "最近 20 条审计事件",
        "cypher": """
            MATCH (a:AuditEvent)
            RETURN a.audit_id AS id,
                   a.action_type AS action,
                   a.object_type AS object_type,
                   a.object_id AS object_id,
                   a.actor_id AS actor,
                   a.timestamp AS ts
            ORDER BY a.timestamp DESC
            LIMIT 20
        """,
    },

    # ─────────── 通用意图（保留原有 + 英文别名兜底） ───────────
    "噬菌体": {
        "label": "噬菌体列表",
        "cypher": """
            MATCH (p:Phage)
            RETURN p.phage_id AS id, p.name AS name,
                   p.family AS family, p.receptor_target AS receptor
            ORDER BY p.name LIMIT 15
        """,
    },
    "情报事件": {
        "label": "情报事件列表",
        "cypher": """
            MATCH (e:IntelligenceEvent)
            RETURN e.event_id AS id, e.title AS title,
                   e.event_type AS type, e.event_date AS date
            ORDER BY e.event_date DESC LIMIT 15
        """,
    },
    "决策记录": {
        "label": "决策记录列表",
        "cypher": """
            MATCH (d:DecisionRecord)
            RETURN d.decision_id AS id, d.decision_summary AS summary,
                   d.decision_type AS type, d.decision_owner AS owner
            ORDER BY d.decided_at DESC LIMIT 15
        """,
    },
    "DecisionRecord": {
        "label": "决策记录列表",
        "cypher": """
            MATCH (d:DecisionRecord)
            RETURN d.decision_id AS id, d.decision_summary AS summary,
                   d.decision_type AS type, d.decision_owner AS owner
            ORDER BY d.decided_at DESC LIMIT 15
        """,
    },
    "DevelopmentProgram": {
        "label": "开发项目列表",
        "cypher": """
            MATCH (p:DevelopmentProgram)
            RETURN p.program_id AS id, p.canonical_name AS name,
                   p.development_stage AS stage,
                   p.program_status AS status
            ORDER BY p.canonical_name LIMIT 15
        """,
    },
    "AuditEvent": {
        "label": "审计事件",
        "cypher": """
            MATCH (a:AuditEvent)
            RETURN a.audit_id AS id, a.action_type AS action,
                   a.object_type AS object_type,
                   a.object_id AS object_id
            ORDER BY a.timestamp DESC LIMIT 15
        """,
    },
    "审计": {
        "label": "审计事件",
        "cypher": """
            MATCH (a:AuditEvent)
            RETURN a.audit_id AS id, a.action_type AS action,
                   a.object_type AS object_type,
                   a.object_id AS object_id
            ORDER BY a.timestamp DESC LIMIT 15
        """,
    },
    "证据包": {
        "label": "证据包列表",
        "cypher": """
            MATCH (pkg:ScientificEvidencePackage)
            RETURN pkg.package_id AS id, pkg.status AS status,
                   pkg.package_type AS package_type
            ORDER BY pkg.created_at DESC LIMIT 15
        """,
    },
    "工程策略": {
        "label": "工程策略列表",
        "cypher": """
            MATCH (s:EngineeringStrategy)
            RETURN s.strategy_id AS id, s.strategy_type AS type,
                   s.evidence_maturity AS maturity,
                   s.review_status AS review_status
            ORDER BY s.strategy_type LIMIT 15
        """,
    },
    "组织": {
        "label": "组织列表",
        "cypher": """
            MATCH (o:Organization)
            RETURN o.organization_id AS id, o.canonical_name AS name,
                   o.organization_type AS type
            ORDER BY o.canonical_name LIMIT 15
        """,
    },
    "项目": {
        "label": "开发项目列表",
        "cypher": """
            MATCH (p:DevelopmentProgram)
            RETURN p.program_id AS id, p.canonical_name AS name,
                   p.development_stage AS stage,
                   p.program_status AS status
            ORDER BY p.canonical_name LIMIT 15
        """,
    },
    "Pathogen": {
        "label": "病原体列表",
        "cypher": """
            MATCH (p:Pathogen)
            RETURN p.pathogen_id AS id, p.species AS species,
                   p.pathogen_type AS type,
                   p.resistance_mechanism AS resistance
            ORDER BY p.species LIMIT 15
        """,
    },
    "病原": {
        "label": "病原体列表",
        "cypher": """
            MATCH (p:Pathogen)
            RETURN p.pathogen_id AS id, p.species AS species,
                   p.pathogen_type AS type,
                   p.resistance_mechanism AS resistance
            ORDER BY p.species LIMIT 15
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

SYSTEM_PROMPT = """你是噬清森 AI 助手，帮助用户查询噬菌体精准治疗平台的 Ontology 数据。

规则：
1. 只能基于用户消息中提供的 JSON 数据回答，禁止编造
2. 数据不足时明确告知用户
3. 回答简洁清晰，适当使用列表
4. 用中文回答
5. 不要提及「根据提供的 JSON 数据」之类的话，直接给出结论
6. 如果用户问的是「本月」「今日」等时间范围，但检索到的数据最新记录也是历史日期，
   请如实说明「当前数据为历史快照，以下按时间倒序展示最近 N 条记录」，不要编造时间
7. 如果某个字段（如 risk_level、impact_level）在数据里不存在，
   请如实说明该字段缺失，改用其他可见字段（decision_type、outcome_status 等）做推断
"""


# ============================================================
# 辅助函数
# ============================================================
def _route_intent(query: str):
    """按 dict 顺序遍历，命中第一个关键词就返回 (kw, route)。"""
    if not query:
        return None, None
    for kw, route in INTENT_ROUTES.items():
        if kw in query:
            return kw, route
    return None, None


def _call_deepseek(question: str, data_str: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=Config.DS_API_KEY,
                        base_url=Config.DS_BASE_URL)
        resp = client.chat.completions.create(
            model=Config.DS_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",
                 "content": f"用户问题：{question}\n\n检索到的数据：\n{data_str}"},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        return resp.choices[0].message.content or "（LLM 返回为空）"
    except Exception as e:
        return f"⚠️ LLM 调用失败：{e}"


# ============================================================
# 页面骨架
# ============================================================
layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("AI 助手", className="page-title"),
            html.Div("自然语言查询 · 结构化检索 · DeepSeek 负责格式化",
                     className="page-subtitle"),
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
            style={"height": "500px", "overflowY": "auto",
                   "padding": "20px",
                   "background": "var(--c-bg)"},
            children=[
                html.Div([
                    html.I(className="bi bi-stars",
                           style={"fontSize": "48px",
                                  "color": "var(--c-primary-light)"}),
                    html.Div("噬清森 AI 助手",
                             style={"fontSize": "18px", "fontWeight": "700",
                                    "marginTop": "16px"}),
                    html.Div("向我询问平台里的 Ontology 数据",
                             style={"color": "var(--c-text-muted)",
                                    "marginTop": "6px",
                                    "fontSize": "13px"}),
                ], style={"display": "flex", "flexDirection": "column",
                          "alignItems": "center", "justifyContent": "center",
                          "height": "100%",
                          "color": "var(--c-text-muted)"}),
            ],
        ),
        # 快捷提示
        html.Div(
            [html.Button(p, id={"type": "ai-quick", "index": i},
                         className="btn-outline-custom",
                         style={"fontSize": "12px",
                                "margin": "0 6px 6px 0"})
             for i, p in enumerate(QUICK_PROMPTS)],
            style={"padding": "10px 20px",
                   "borderTop": "1px solid var(--c-border)",
                   "background": "var(--c-surface)"},
        ),
        # 输入区
        html.Div([
            dcc.Textarea(
                id="ai-input",
                placeholder="输入问题，例如：有哪些噬菌体？",
                style={"flex": "1", "border": "1px solid var(--c-border)",
                       "borderRadius": "6px", "padding": "10px 14px",
                       "fontSize": "14px", "resize": "none",
                       "minHeight": "42px", "fontFamily": "inherit"},
                value="", rows=1,
            ),
            html.Button([html.I(className="bi bi-send-fill")],
                        id="btn-ai-send", className="btn-primary-custom",
                        style={"padding": "10px 16px"}),
        ], style={"display": "flex", "gap": "8px", "padding": "12px 20px",
                  "borderTop": "1px solid var(--c-border)",
                  "background": "var(--c-surface)"}),
    ]),

    html.Div(
        [html.I(className="bi bi-shield-check me-1",
                style={"color": "var(--c-secondary)"}),
         "所有回答基于结构化检索，DeepSeek 仅用于文本格式化，"
         "不替代专家判断，不产生未经溯源的事实。"],
        style={"fontSize": "11px", "color": "var(--c-text-muted)",
               "textAlign": "center", "padding": "12px 0"},
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
            html.I(className="bi bi-stars",
                   style={"fontSize": "48px",
                          "color": "var(--c-primary-light)"}),
            html.Div("噬清森 AI 助手",
                     style={"fontSize": "18px", "fontWeight": "700",
                            "marginTop": "16px"}),
            html.Div("向我询问平台里的 Ontology 数据",
                     style={"color": "var(--c-text-muted)",
                            "marginTop": "6px", "fontSize": "13px"}),
        ], style={"display": "flex", "flexDirection": "column",
                  "alignItems": "center", "justifyContent": "center",
                  "height": "100%", "color": "var(--c-text-muted)"}),
    ]
    return empty, []


# ============================================================
# 回调 3：发送消息
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

    # 意图路由
    kw, route = _route_intent(query)
    source_ids = []
    matched_label = None

    if route:
        matched_label = route.get("label", kw)
        try:
            raw = _run(route["cypher"])
            data_str = json.dumps(raw, ensure_ascii=False, indent=2,
                                   default=str)
            source_ids = [str(r.get("id", "")) for r in raw[:5]
                          if r.get("id")]
            if not raw:
                data_str = "（查询成功，但结果为空）"
        except Exception as e:
            raw = []
            data_str = f"（检索失败：{e}）"
    else:
        raw = []
        data_str = ("（未匹配到意图。支持的查询关键词："
                    + "、".join(INTENT_ROUTES.keys()) + "）")

    # 调 DeepSeek
    if route:
        answer = _call_deepseek(query, data_str)
    else:
        answer = (f"我不太理解这个问题。\n\n"
                  f"你可以尝试以下关键词之一：\n"
                  f"**{'、'.join(INTENT_ROUTES.keys())}**\n\n"
                  f"或者点下方快捷提问按钮试试。")

    history.append({
        "role": "assistant",
        "content": answer,
        "ts": datetime.now().strftime("%H:%M"),
        "source_ids": source_ids,
        "matched_kw": kw,
        "matched_label": matched_label,
    })

    # 渲染
    children = []
    for msg in history:
        if msg["role"] == "user":
            children.append(html.Div([
                html.Div(msg["content"],
                         style={"background": "var(--c-primary)",
                                "color": "#fff", "padding": "10px 14px",
                                "borderRadius": "12px 12px 4px 12px",
                                "maxWidth": "75%", "fontSize": "13px",
                                "lineHeight": "1.6"}),
                html.Div(msg["ts"],
                         style={"fontSize": "10px",
                                "color": "var(--c-text-muted)",
                                "marginTop": "4px",
                                "textAlign": "right"}),
            ], style={"display": "flex", "flexDirection": "column",
                      "alignItems": "flex-end",
                      "marginBottom": "12px"}))
        else:
            bubble = []
            # 显示匹配到的意图
            if msg.get("matched_label"):
                bubble.append(html.Div(
                    f"🎯 匹配意图：{msg['matched_label']}",
                    style={"fontSize": "11px",
                           "color": "var(--c-text-muted)",
                           "marginBottom": "6px",
                           "fontStyle": "italic"}))
            bubble.append(html.Div(msg["content"],
                         style={"background": "var(--c-surface)",
                                "border": "1px solid var(--c-border)",
                                "padding": "12px 16px",
                                "borderRadius": "12px 12px 12px 4px",
                                "maxWidth": "75%", "fontSize": "13px",
                                "lineHeight": "1.7",
                                "whiteSpace": "pre-wrap"}))
            if msg.get("source_ids"):
                bubble.append(html.Div(
                    [html.Span(f"[来源：{sid}]",
                               style={"background": "var(--c-bg)",
                                      "border": "1px solid var(--c-border)",
                                      "borderRadius": "4px",
                                      "padding": "1px 6px",
                                      "marginRight": "4px",
                                      "fontFamily": "monospace",
                                      "fontSize": "10px",
                                      "color": "var(--c-text-muted)"})
                     for sid in msg["source_ids"][:5]],
                    style={"marginTop": "6px"}))
            bubble.append(html.Div(msg["ts"],
                                    style={"fontSize": "10px",
                                           "color": "var(--c-text-muted)",
                                           "marginTop": "4px"}))
            children.append(html.Div(bubble,
                                      style={"display": "flex",
                                             "flexDirection": "column",
                                             "alignItems": "flex-start",
                                             "marginBottom": "12px"}))

    return children, history, ""


# ============================================================
# 回调 4：URL ?q= 参数预填（来自 Dashboard 快速查询跳转）
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