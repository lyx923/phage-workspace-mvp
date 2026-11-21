# pages/ai_assistant.py
"""AI 助手入口：支持受控任务创建（S1/S2/I1）与通用 LLM 智能问答。"""
import re
import json
import requests
import dash
from dash import clientside_callback, callback, ctx, dcc, html, no_update, Input, Output, State
import dash_bootstrap_components as dbc
from flask import session

from config import Config
from src.agents.core import (
    ApprovalDecision, ApprovalType, IntentRouter, IntentType, TaskStatus, get_agent_runtime,
)

dash.register_page(__name__, path="/ai-assistant", name="AI 助手")

QUICK_PROMPTS = [
    "帮我检查实验批次 BATCH-20261115-013 的数据完整性",
    "基于 PKP005 和 B-KP1 生成证据包草稿",
    "生成 PATH-003 的周期情报简报（2026-01-01 至 2026-11-15）",
    "查询所有噬菌体的裂解谱覆盖情况",
]

def _current_identity():
    user = session.get("user") or {}
    return {"id": user.get("username") or "", "role": user.get("role") or "researcher", "name": user.get("name") or ""}

layout = html.Div(
    id="ai-assistant-page",
    style={"display": "flex", "flexDirection": "column", "height": "calc(100vh - 180px)", "minHeight": "450px", "width": "100%", "overflow": "hidden", "boxSizing": "border-box"},
    children=[
        html.Div(className="page-header", style={"marginBottom": "20px", "flexShrink": 0}, children=[
            html.Div([html.Div("AI 助手", className="page-title"), html.Div("自然语言入口 · 智能问答 · 任务生成", className="page-subtitle")]),
            html.Div(className="page-actions", children=[html.Button([html.I(className="bi bi-trash3 me-1"), "清空对话"], id="btn-ai-clear", className="btn-outline-custom")]),
        ]),
        html.Div(className="surface-card", style={"padding": "0", "display": "flex", "flexDirection": "column", "flex": "1", "overflow": "hidden", "minHeight": "0"}, children=[
            html.Div(id="ai-messages", style={"flex": "1", "minHeight": "0", "overflowY": "auto", "padding": "20px", "background": "var(--c-bg)"}, children=[
                html.Div([
                    html.I(className="bi bi-robot", style={"fontSize": "48px", "color": "var(--c-primary-light)"}),
                    html.Div("受控 Agent 已就绪", style={"fontSize": "18px", "fontWeight": "700", "marginTop": "16px"}),
                    html.Div("支持 S1(批次)/S2(证据包)/I1(简报) 任务生成；直接提问可进行智能检索。", style={"color": "var(--c-text-muted)", "marginTop": "6px", "fontSize": "13px"}),
                ], style={"display": "flex", "flexDirection": "column", "alignItems": "center", "justifyContent": "center", "height": "100%", "color": "var(--c-text-muted)"}),
            ]),
            html.Div([html.Button(p, id={"type": "ai-quick", "index": i}, className="btn-outline-custom", style={"fontSize": "12px", "whiteSpace": "nowrap"}) for i, p in enumerate(QUICK_PROMPTS)], style={"padding": "10px 20px", "borderTop": "1px solid var(--c-border)", "background": "var(--c-surface)", "flexShrink": 0, "display": "flex", "gap": "8px", "overflowX": "auto"}),
            html.Div([
                dcc.Textarea(id="ai-input", placeholder="输入您的请求...", style={"flex": "1", "border": "1px solid var(--c-border)", "borderRadius": "6px", "padding": "10px 14px", "fontSize": "14px", "resize": "none", "minHeight": "42px"}, value="", rows=1),
                html.Button([html.I(className="bi bi-send-fill")], id="btn-ai-send", className="btn-primary-custom", style={"padding": "10px 16px"}),
            ], style={"display": "flex", "gap": "8px", "padding": "12px 20px", "borderTop": "1px solid var(--c-border)", "background": "var(--c-surface)", "flexShrink": 0}),
        ]),
        dcc.Store(id="store-ai-history", data=[]),
        dcc.Store(id="store-ai-redirect", data=None),
    ],
)

def _ask_llm(prompt: str, enable_thinking: bool = False) -> str:
    """调用 DeepSeek API（HTTP 直连）。

    根据 Config.DS_MODEL_SUPPORTS_THINKING 自动适配：
    - 支持 thinking（deepseek-flash 等）：enable_thinking=True 时开启，False 时关闭；
    - 不支持 thinking（deepseek-chat）：忽略 enable_thinking，不传 thinking，temperature 正常生效。
    返回最终答案 content；若 content 为空则回退到 reasoning_content。
    """
    if not Config.DS_API_KEY:
        return "未配置大模型 Key。"

    payload = {
        "model": Config.DS_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": Config.DS_MAX_TOKENS,
    }

    if Config.DS_MODEL_SUPPORTS_THINKING:
        if enable_thinking:
            payload["thinking"] = {"type": "enabled"}
        else:
            payload["thinking"] = {"type": "disabled"}
            payload["temperature"] = 0.0
    else:
        # deepseek-chat：不支持 thinking
        payload["temperature"] = 0.0
        if enable_thinking:
            print(f"   ⚠️ 模型 {Config.DS_MODEL} 不支持 thinking 参数，enable_thinking 已忽略")

    try:
        resp = requests.post(
            f"{Config.DS_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {Config.DS_API_KEY}"},
            json=payload,
            timeout=60,
        )
        if resp.status_code != 200:
            return f"错误: {resp.text}"

        message = resp.json()["choices"][0]["message"]
        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        return content if content.strip() else reasoning
    except Exception as e:
        return f"异常: {e}"

@callback(Output("ai-input", "value", allow_duplicate=True), Input({"type": "ai-quick", "index": dash.ALL}, "n_clicks"), prevent_initial_call=True)
def cb_fill_quick(_):
    if not ctx.triggered_id: return no_update
    idx = ctx.triggered_id.get("index")
    return QUICK_PROMPTS[idx] if isinstance(idx, int) and idx < len(QUICK_PROMPTS) else no_update

@callback(Output("ai-messages", "children", allow_duplicate=True), Output("store-ai-history", "data", allow_duplicate=True), Input("btn-ai-clear", "n_clicks"), prevent_initial_call=True)
def cb_clear(_):
    return [html.Div("已重置", style={"textAlign": "center", "paddingTop": "200px"})], []

@callback(
    Output("ai-messages", "children", allow_duplicate=True),
    Output("store-ai-history", "data", allow_duplicate=True),
    Output("ai-input", "value", allow_duplicate=True),
    Input("btn-ai-send", "n_clicks"), State("ai-input", "value"), State("store-ai-history", "data"), prevent_initial_call=True,
)
def cb_send(_, user_input, history):
    if not user_input or not user_input.strip(): return no_update, no_update, no_update
    query = user_input.strip()
    history = history or []
    history.append({"role": "user", "content": query})
    
    result = IntentRouter().route(query)
    identity = _current_identity()
    if not identity["id"]:
        history.append({"role": "assistant", "content": "请先登录后再操作。"})
        return _render_history(history), history, ""

    try:
        rt = get_agent_runtime()
        
        # 1. S1 批次完整性
        if result.intent == IntentType.SCI_S1_BATCH_COMPLETENESS:
            batch_id = (result.params.get("experiment_batch_id") or "").strip()
            if not batch_id:
                history.append({"role": "assistant", "content": "请补充批次 ID，例如 BATCH-20261115-ABC"})
                return _render_history(history), history, ""
            
            with rt.driver.session() as s:
                exists = s.run("MATCH (b:ExperimentBatch {id: $bid}) RETURN 1", bid=batch_id).single()
                if not exists:
                    recent = s.run("MATCH (b:ExperimentBatch) RETURN b.id AS id, b.name AS name LIMIT 5").data()
                    hint = "\n\n现有批次参考：\n" + "\n".join([f"- {r['id']} ({r['name']})" for r in recent]) if recent else ""
                    history.append({"role": "assistant", "content": f"⚠️ 批次 **{batch_id}** 不存在。{hint}"})
                    return _render_history(history), history, ""
            
            task, plan = rt.s1_service.create_task(experiment_batch_id=batch_id, submitted_by=identity["id"], user_role=identity["role"])
            target_label = "批次"

        # 2. S2 证据包草稿
        elif result.intent == IntentType.SCI_S2_EVIDENCE_PACKAGE:
            raw_phage = (result.params.get("phage_id") or "").strip()
            raw_host = (result.params.get("host_strain_id") or "").strip()
            missing = []
            if not raw_phage: missing.append("噬菌体 ID 或名称 (如 PKP005)")
            if not raw_host: missing.append("宿主菌株 ID 或标签 (如 B-KP1)")
            if missing:
                history.append({"role": "assistant", "content": "识别为 SCI-S2，但缺少：" + "、".join(missing)})
                return _render_history(history), history, ""
            
            with rt.driver.session() as s:
                p_rec = s.run("MATCH (p:Phage) WHERE p.phage_id = $val OR p.name = $val RETURN p.phage_id AS id LIMIT 1", val=raw_phage).single()
                h_rec = s.run("MATCH (h:HostStrain) WHERE h.host_strain_id = $val OR h.name = $val OR h.strain_name = $val RETURN h.host_strain_id AS id LIMIT 1", val=raw_host).single()
                
                if not p_rec or not h_rec:
                    msg = "⚠️ 对象不存在："
                    if not p_rec: 
                        recent = s.run("MATCH (p:Phage) RETURN coalesce(p.name, p.phage_id) AS name, p.phage_id AS id LIMIT 5").data()
                        msg += f"\n- 未找到噬菌体 **{raw_phage}**（库中参考: " + ", ".join([f"{r['name']}" for r in recent]) + "）"
                    if not h_rec:
                        recent_h = s.run("MATCH (h:HostStrain) RETURN coalesce(h.strain_name, h.name, h.host_strain_id) AS name LIMIT 5").data()
                        ref_str = ", ".join([str(r['name']) for r in recent_h if r['name']])
                        msg += f"\n- 未找到宿主 **{raw_host}**（库中参考: {ref_str}）"
                    history.append({"role": "assistant", "content": msg})
                    return _render_history(history), history, ""
                
                real_phage_id = p_rec["id"]
                real_host_id = h_rec["id"]
                    
            task, plan = rt.s2_service.create_task(phage_id=real_phage_id, host_strain_id=real_host_id, submitted_by=identity["id"], user_role=identity["role"])
            target_label = "组合"

        # 3. I1 情报简报
        elif result.intent == IntentType.INT_I1_PERIODIC_BRIEF:
            if identity["role"] not in {"analyst", "data_manager", "admin"}:
                history.append({"role": "assistant", "content": "无权创建情报域任务。"})
                return _render_history(history), history, ""
            pathogen_id = (result.params.get("pathogen_id") or "").strip()
            date_from = result.params.get("date_from") or ""
            date_to = result.params.get("date_to") or ""
            if not pathogen_id or not date_from or not date_to:
                history.append({"role": "assistant", "content": "缺少病原体 ID 或日期范围。"})
                return _render_history(history), history, ""
            
            with rt.driver.session() as s:
                if not s.run("MATCH (p:Pathogen {pathogen_id: $pid}) RETURN 1", pid=pathogen_id).single():
                    history.append({"role": "assistant", "content": f"⚠️ 未找到病原体 {pathogen_id}。"})
                    return _render_history(history), history, ""
                
            task, plan = rt.i1_service.create_task(pathogen_id=pathogen_id, date_from=date_from, date_to=date_to, submitted_by=identity["id"], user_role=identity["role"])
            target_label = "病原体"

        # 4. 通用智能问答
        else:
            with rt.driver.session() as s:
                labels = [r["label"] for r in s.run("CALL db.labels()")]
                rels = [r["relationshipType"] for r in s.run("CALL db.relationshipTypes()")]
            
            prompt = f"""你是一个 Neo4j 专家。
数据库标签: {', '.join(labels)}
数据库关系类型: {', '.join(rels)}

请将用户的自然语言转化为单条只读的 Cypher 查询语句。
【极其重要】：必须输出纯 Cypher，禁止解释！如果不确定关系，尽量用单点查询。

用户问题：{query}
"""
            llm_res = _ask_llm(prompt, enable_thinking=True)
            cypher_match = re.search(r"(?is)(MATCH|RETURN|OPTIONAL MATCH|CALL|WITH)\s+.*?(?=(?:\n\n|\Z|```))", llm_res)
            cypher = cypher_match.group(0).strip().replace("```", "").strip() if cypher_match else ""
            
            summary = ""
            if cypher:
                with rt.driver.session() as s:
                    try:
                        data = s.run(cypher).data()
                        if not data:
                            fallback_msg = "查询未匹配到直接关系数据。\n\n"
                            if "Phage" in query or "噬菌体" in query:
                                recent = s.run("MATCH (p:Phage) RETURN coalesce(p.name, p.phage_id) AS name, p.phage_id AS id LIMIT 5").data()
                                if recent:
                                    fallback_msg += "💡 **系统兜底提示**：库中现有部分噬菌体节点，例如：\n" + "\n".join([f"- {r['id']} ({r['name']})" for r in recent])
                            if "LysisAssay" in query or "裂解" in query:
                                cnt = s.run("MATCH (l:LysisAssay) RETURN count(l) AS c").single()["c"]
                                fallback_msg += f"\n\n- 库中另有 **{cnt}** 条裂解实验记录。"
                            fallback_msg += "\n\n（注：图数据库中可能尚未建立两者之间的物理连线，或大模型生成的查询方向有误。）"
                            summary = fallback_msg
                        else:
                            summary = _ask_llm(f"用户问题：{query}\n数据：{json.dumps(data[:20], ensure_ascii=False, default=str)}\n请用中文简洁总结。", enable_thinking=False)
                    except Exception as e:
                        summary = "生成的图查询语句报错，无法执行。"
            else:
                summary = llm_res

            history.append({"role": "assistant", "content": summary})
            return _render_history(history), history, ""

    except Exception as e:
        history.append({"role": "assistant", "content": f"操作失败：{e}"})
        return _render_history(history), history, ""

    history.append({"role": "plan_card", "data": {"task_id": task.task_id, "plan_id": plan.plan_id, "goal_summary": plan.goal_summary, "steps": [s.to_dict() for s in plan.steps], "batch_id": task.scope.get("experiment_batch_id") or task.scope.get("pathogen_id") or f"{task.scope.get('phage_id')} × {task.scope.get('host_strain_id')}", "target_label": target_label, "status": "pending"}})
    return _render_history(history), history, ""

@callback(
    Output("ai-messages", "children", allow_duplicate=True),
    Output("store-ai-history", "data", allow_duplicate=True),
    Output("store-ai-redirect", "data", allow_duplicate=True),
    Input({"type": "btn-ai-approve-plan", "index": dash.ALL}, "n_clicks"),
    Input({"type": "btn-ai-reject-plan", "index": dash.ALL}, "n_clicks"),
    State("store-ai-history", "data"), prevent_initial_call=True,
)
def cb_plan_action(approve_n, reject_n, history):
    trigger = ctx.triggered_id
    if not trigger or not any(approve_n + reject_n): return no_update, no_update, no_update
    plan_id = trigger.get("index"); action = trigger.get("type"); history = history or []
    plan_idx = next((i for i, item in enumerate(history) if item.get("role") == "plan_card" and item["data"].get("plan_id") == plan_id), None)
    if plan_idx is None: return no_update, no_update, no_update

    card = history[plan_idx]["data"]; task_id = card["task_id"]; identity = _current_identity()
    
    if action == "btn-ai-reject-plan":
        try: get_agent_runtime().intervention_service.cancel(task_id, requested_by=identity["id"], reason="拒绝计划")
        except Exception: pass
        card["status"] = "rejected"
        history.append({"role": "assistant", "content": "已拒绝计划。"})
        return _render_history(history), history, no_update

    if identity["role"] not in {"data_manager", "admin"}:
        history.append({"role": "assistant", "content": "⚠️ 当前角色无审核权限，请到任务中心处理。"})
        return _render_history(history), history, no_update

    try:
        rt = get_agent_runtime()
        task = rt.task_repository.get(task_id)
        if task is None or task.status != TaskStatus.PLAN_REVIEW:
            history.append({"role": "assistant", "content": "任务已不在 PLAN_REVIEW。"})
            return _render_history(history), history, no_update

        approval = rt.approval_service.request_approval(
            task_id=task_id, approval_type=ApprovalType.PLAN, requested_by=task.assigned_agent,
            requested_from_role=identity["role"], plan_id=task.current_plan_id, plan_version=task.current_plan_version, correlation_id=task.correlation_id,
        )
        rt.approval_service.decide(approval.approval_id, decision=ApprovalDecision.APPROVED, decided_by=identity["id"], decided_by_role=identity["role"], comment="AI 助手批准", correlation_id=task.correlation_id)
        rt.task_service.approve_plan(task_id, approval_id=approval.approval_id, approval_validator=rt.approval_service.is_valid_approval, actor_id=identity["id"])

        task_type = getattr(task, "task_type", "")
        if task_type == "SCI-S1-BATCH-COMPLETENESS": rt.s1_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
        elif task_type == "SCI-S2-EVIDENCE-PACKAGE-DRAFT": rt.s2_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
        elif task_type == "INT-I1-PERIODIC-BRIEF-DRAFT": rt.i1_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
    except Exception as e:
        history.append({"role": "assistant", "content": f"批准失败：{e}"})
        return _render_history(history), history, no_update

    card["status"] = "approved"
    history.append({"role": "assistant", "content": "计划已批准，即将跳转..."})
    return _render_history(history), history, "/agent/task-center"

clientside_callback(
    "function(target) { if (target) window.location.href = target; return window.dash_clientside.no_update; }",
    Output("store-ai-redirect", "id"), Input("store-ai-redirect", "data"), prevent_initial_call=True,
)

def _render_history(history):
    children = []
    for msg in history:
        role = msg.get("role")
        if role == "user":
            children.append(html.Div([html.Div(msg["content"], style={"background": "var(--c-primary)", "color": "#fff", "padding": "10px 14px", "borderRadius": "12px 12px 4px 12px", "maxWidth": "75%", "fontSize": "13px"})], style={"display": "flex", "justifyContent": "flex-end", "marginBottom": "12px"}))
        elif role == "assistant":
            children.append(html.Div([html.Div(msg["content"], style={"background": "var(--c-surface)", "border": "1px solid var(--c-border)", "padding": "12px 16px", "borderRadius": "12px 12px 12px 4px", "maxWidth": "85%", "fontSize": "13px", "lineHeight": "1.7", "whiteSpace": "pre-wrap"})], style={"display": "flex", "justifyContent": "flex-start", "marginBottom": "12px"}))
        elif role == "plan_card":
            d = msg["data"]; status = d.get("status", "pending")
            steps_ui = [html.Li(f"Step {i+1}: {s.get('name')}", style={"fontSize": "12px", "marginBottom": "4px"}) for i, s in enumerate(d.get("steps", []))]
            target_label = d.get("target_label", "对象")
            card_body = [
                html.H6("📋 待批准计划", style={"fontWeight": "700", "marginBottom": "8px"}),
                html.Div(f"任务：{d['task_id']}", style={"fontFamily": "monospace", "fontSize": "12px", "color": "var(--c-text-muted)"}),
                html.Div(f"目标：{d['goal_summary']}", style={"fontSize": "13px", "marginBottom": "8px", "color": "var(--c-text-secondary)"}),
                html.Div(f"{target_label}：{d['batch_id']}", style={"fontSize": "12px", "marginBottom": "8px"}),
                html.Ul(steps_ui, style={"paddingLeft": "20px", "marginBottom": "16px"}),
            ]
            if status == "pending":
                card_body.append(html.Div([
                    html.Button("✅ 批准计划", id={"type": "btn-ai-approve-plan", "index": d["plan_id"]}, className="btn-primary-custom", style={"flex": "1"}),
                    html.Button("❌ 拒绝", id={"type": "btn-ai-reject-plan", "index": d["plan_id"]}, className="btn-danger-custom", style={"flex": "1"}),
                ], style={"display": "flex", "gap": "8px"}))
            elif status == "approved":
                card_body.append(html.Div("✅ 已批准", style={"color": "var(--c-secondary)", "fontWeight": "600", "textAlign": "center"}))
            children.append(html.Div(card_body, style={"background": "var(--c-surface)", "border": "1px solid var(--c-border)", "borderRadius": "8px", "padding": "16px", "maxWidth": "80%", "marginBottom": "16px", "boxShadow": "var(--shadow-sm)"}))
    return children