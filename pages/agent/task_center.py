# pages/agent/task_center.py
"""Agent 任务中心。"""
import json
import traceback

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, ctx, dcc, html, no_update
from flask import session

from src.agents.core import (
    ApprovalDecision,
    ApprovalType,
    ArtifactStatus,
    StepStatus,
    TaskStatus,
    get_agent_runtime,
)

dash.register_page(__name__, path="/agent/task-center", name="任务中心")

# ============================================================
# 中英文映射字典
# ============================================================
STATUS_MAP = {
    "DRAFT": "📝 草稿", "UNDERSTANDING": "🧠 理解中", "PLANNING": "📝 规划中",
    "PLAN_REVIEW": "⏳ 待批计划", "APPROVED": "✅ 已批准", "EXECUTING": "⚙️ 执行中",
    "WAITING_INPUT": "⌨️ 待输入", "WAITING_APPROVAL": "⏳ 待审批", "PAUSED": "⏸️ 已暂停",
    "FAILED": "❌ 失败", "CANCELLED": "🚫 已取消", "RESULT_REVIEW": "🔍 结果审核中",
    "NEEDS_REVISION": "🔄 需修改", "REJECTED": "🚫 已拒绝", "COMPLETED": "🏁 已完成",
}

DOMAIN_MAP = {
    "scientific": "科学域",
    "intelligence": "情报域",
    "General": "通用"
}

RISK_MAP = {
    "R0": "R0 只读",
    "R1": "R1 分析",
    "R2": "R2 候选",
    "R3": "R3 正式"
}

STEP_STATUS_MAP = {
    "PENDING": "⏳ 待执行",
    "WAITING_APPROVAL": "⏳ 待审批",
    "EXECUTING": "⚙️ 执行中",
    "COMPLETED": "✅ 已完成",
    "FAILED": "❌ 失败",
    "SKIPPED": "⏭️ 已跳过",
    "CANCELLED": "🚫 已取消",
}

ARTIFACT_TYPE_MAP = {
    "missing_data_report": "缺失数据报告",
    "intelligence_brief_draft": "情报简报草稿",
    "query_result": "查询结果",
    "validation_findings": "校验发现",
    "comparison_table": "对比表格",
    "draft_claim": "主张草稿",
    "draft_evidence_package": "证据包草稿",
    "conflict_report": "冲突报告",
    "final_report": "最终报告",
}

TASK_COLUMNS = [
    {"field": "task_id", "headerName": "任务 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "title", "headerName": "任务", "flex": 2, "minWidth": 240},
    {"field": "domain_cn", "headerName": "领域", "width": 110},
    {"field": "risk_cn", "headerName": "风险", "width": 90},
    {"field": "status_cn", "headerName": "状态", "width": 130},
    {"field": "submitted_by", "headerName": "发起人", "width": 130},
    {"field": "created_at", "headerName": "创建时间", "width": 180},
    {"field": "action", "headerName": "查看", "width": 80,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
    {"field": "delete", "headerName": "删除", "width": 80,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-danger)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]

TASK_TEMPLATE_OPTIONS = [
    {"label": "科学域：实验批次完整性检查（SCI-S1）", "value": "SCI-S1-BATCH-COMPLETENESS"},
    {"label": "科学域：证据包草稿（SCI-S2）", "value": "SCI-S2-EVIDENCE-PACKAGE-DRAFT"},
    {"label": "情报域：周期情报简报草稿（INT-I1）", "value": "INT-I1-PERIODIC-BRIEF-DRAFT"},
]

def _current_identity():
    user = session.get("user") or {}
    return {
        "id": user.get("username") or "",
        "role": user.get("role") or "researcher",
        "name": user.get("name") or "",
    }

layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("Agent 任务中心", className="page-title"),
            html.Div("受控任务 · 人工审核 · 执行监控 · 完整审计", className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button("刷新", id="btn-agent-v2-refresh", className="btn-outline-custom"),
            html.Button("新建任务", id="btn-agent-v2-new", className="btn-primary-custom"),
        ]),
    ]),

    dbc.Alert(
        "当前为 Agent 验证界面。结果不用于科学、业务或临床决策。",
        color="warning", className="mb-3",
    ),

    html.Div(id="agent-v2-feedback"),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="agent-v2-grid", columnDefs=TASK_COLUMNS, rowData=[],
            dashGridOptions={"pagination": True, "paginationPageSize": 20, "domLayout": "autoHeight"},
            style={"height": None, "minHeight": "400px"},
        ),
    ]),

    dbc.Offcanvas(
        id="agent-v2-create-drawer", title="创建 Agent 任务",
        placement="end", is_open=False, style={"width": "480px"},
        children=[
            dbc.Label("任务模板 *"),
            dcc.Dropdown(
                id="agent-v2-template",
                options=TASK_TEMPLATE_OPTIONS,
                value="SCI-S1-BATCH-COMPLETENESS",
                clearable=False,
                style={"marginBottom": "16px"},
            ),
            
            # S1 字段
            html.Div(id="agent-v2-s1-fields", children=[
                dbc.Label("实验批次 ID *"),
                dbc.Input(id="agent-v2-batch-id", placeholder="可直接输入，或从下方选择"),
                dcc.Dropdown(id="agent-v2-batch-selector", placeholder="从现有批次中选择...", options=[], clearable=False, style={"marginTop": "8px", "fontSize": "12px"}),
            ]),
            
            # S2 字段
            html.Div(id="agent-v2-s2-fields", style={"display": "none"}, children=[
                dbc.Label("噬菌体 ID *"),
                dbc.Input(id="agent-v2-s2-phage-id", placeholder="例如 PHG-001"),
                dbc.Label("宿主菌株 ID *", style={"marginTop": "16px"}),
                dbc.Input(id="agent-v2-s2-host-id", placeholder="例如 HS-001"),
            ]),

            # I1 字段
            html.Div(id="agent-v2-i1-fields", style={"display": "none"}, children=[
                dbc.Label("病原体 ID *"),
                dbc.Input(id="agent-v2-pathogen-id", placeholder="可直接输入，或从下方选择"),
                dcc.Dropdown(id="agent-v2-pathogen-selector", placeholder="从现有病原体中选择...", options=[], clearable=False, style={"marginTop": "8px", "fontSize": "12px", "marginBottom": "16px"}),
                dbc.Label("开始日期 *"), dbc.Input(id="agent-v2-date-from", type="date"),
                dbc.Label("结束日期 *", style={"marginTop": "16px"}), dbc.Input(id="agent-v2-date-to", type="date"),
            ]),
            
            html.Div([
                html.Button("取消", id="btn-agent-v2-create-cancel", className="btn-outline-custom me-2"),
                html.Button("创建并生成计划", id="btn-agent-v2-create-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end", "marginTop": "24px"}),
        ],
    ),

    dcc.Store(id="store-agent-v2-task-id"),
    dcc.Store(id="store-agent-v2-delete-id"),
    dbc.Modal(
        id="agent-v2-delete-modal", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("确认删除任务"), style={"color": "var(--c-danger)"}),
            dbc.ModalBody("确定要删除该任务及其所有计划、产物、审批记录吗？此操作不可恢复。"),
            dbc.ModalFooter([
                html.Button("取消", id="btn-agent-v2-del-cancel", className="btn-outline-custom me-2"),
                html.Button("确认删除", id="btn-agent-v2-del-confirm", className="btn-danger-custom"),
            ]),
        ]
    ),

    dbc.Offcanvas(
        id="agent-v2-detail-drawer", title="Agent 任务详情",
        placement="end", is_open=False, style={"width": "840px"},
        children=[
            html.Div(id="agent-v2-detail-summary"), html.Hr(),
            html.H6("计划与审核"), html.Div(id="agent-v2-plan-panel"), html.Hr(),
            html.H6("执行与结果（含版本链）"), html.Div(id="agent-v2-result-panel"), html.Hr(),
            html.H6("干预操作（原因必填）"),
            dbc.Textarea(id="agent-v2-intervention-reason", placeholder="操作原因...", className="mb-2"),
            html.Div([
                html.Button("批准计划", id="btn-agent-v2-plan-approve", className="btn-primary-custom me-2", style={"display": "none"}),
                html.Button("执行任务", id="btn-agent-v2-execute", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("批准结果", id="btn-agent-v2-result-approve", className="btn-primary-custom me-2", style={"display": "none"}),
                html.Button("部分批准", id="btn-agent-v2-result-partial", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("退回修订", id="btn-agent-v2-result-reject", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("拒绝结果", id="btn-agent-v2-result-reject-final", className="btn-danger-custom me-2", style={"display": "none"}),
                html.Button("重试失败步骤", id="btn-agent-v2-retry", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("生成结果修订版", id="btn-agent-v2-revise", className="btn-primary-custom me-2", style={"display": "none"}),
                html.Button("生成修订计划", id="btn-agent-v2-replan", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("暂停", id="btn-agent-v2-pause", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("恢复", id="btn-agent-v2-resume", className="btn-outline-custom me-2", style={"display": "none"}),
                html.Button("取消任务", id="btn-agent-v2-cancel", className="btn-danger-custom", style={"display": "none"}),
            ], style={"display": "flex", "flexWrap": "wrap", "gap": "8px"}),
            html.Hr(), html.H6("审计时间线"), html.Div(id="agent-v2-timeline"),
        ],
    ),
])

@callback(
    Output("agent-v2-create-drawer", "is_open"),
    Input("btn-agent-v2-new", "n_clicks"), Input("btn-agent-v2-create-cancel", "n_clicks"), prevent_initial_call=True,
)
def toggle_create_drawer(_, __): return ctx.triggered_id == "btn-agent-v2-new"

@callback(
    Output("agent-v2-batch-selector", "options"), Output("agent-v2-pathogen-selector", "options"),
    Input("btn-agent-v2-new", "n_clicks"), prevent_initial_call=True,
)
def load_dropdown_options(_):
    try:
        rt = get_agent_runtime()
        with rt.driver.session() as s:
            batches = s.run("MATCH (b:ExperimentBatch) RETURN b.id AS id, b.name AS name LIMIT 100")
            batch_opts = [{"label": f"{r['id']} ({r['name']})" if r.get('name') else r['id'], "value": r['id']} for r in batches if r['id']]
            pathogens = s.run("MATCH (p:Pathogen) RETURN p.pathogen_id AS id, p.name AS name LIMIT 100")
            path_opts = [{"label": f"{r['id']} ({r['name']})" if r.get('name') else r['id'], "value": r['id']} for r in pathogens if r['id']]
        return batch_opts, path_opts
    except Exception: return [], []

@callback(Output("agent-v2-batch-id", "value"), Input("agent-v2-batch-selector", "value"), prevent_initial_call=True)
def fill_batch_id(batch_id): return batch_id or no_update

@callback(Output("agent-v2-pathogen-id", "value"), Input("agent-v2-pathogen-selector", "value"), prevent_initial_call=True)
def fill_pathogen_id(pathogen_id): return pathogen_id or no_update

@callback(
    Output("agent-v2-s1-fields", "style"), Output("agent-v2-s2-fields", "style"), Output("agent-v2-i1-fields", "style"),
    Input("agent-v2-template", "value"),
)
def switch_task_template(template_id):
    if template_id == "SCI-S2-EVIDENCE-PACKAGE-DRAFT": return {"display": "none"}, {"display": "block"}, {"display": "none"}
    if template_id == "INT-I1-PERIODIC-BRIEF-DRAFT": return {"display": "none"}, {"display": "none"}, {"display": "block"}
    return {"display": "block"}, {"display": "none"}, {"display": "none"}

_TRIGGER_INPUTS = [
    "btn-agent-v2-refresh", "btn-agent-v2-create-save", "btn-agent-v2-plan-approve", "btn-agent-v2-execute",
    "btn-agent-v2-result-approve", "btn-agent-v2-result-partial", "btn-agent-v2-result-reject", "btn-agent-v2-result-reject-final",
    "btn-agent-v2-retry", "btn-agent-v2-revise", "btn-agent-v2-replan", "btn-agent-v2-pause", "btn-agent-v2-resume", "btn-agent-v2-cancel",
]

@callback(Output("agent-v2-grid", "rowData"), *[Input(t, "n_clicks") for t in _TRIGGER_INPUTS])
def load_tasks(*_):
    identity = _current_identity()
    if not identity["id"]: return []
    try: rt = get_agent_runtime()
    except Exception: return []
    with rt.driver.session() as s:
        rows = list(s.run("MATCH (t:AgentTask) RETURN t.task_id AS task_id, t.title AS title, t.domain AS domain, t.risk_level AS risk_level, t.status AS status, t.submitted_by AS submitted_by, toString(t.created_at) AS created_at ORDER BY t.created_at DESC LIMIT 100"))
    result_rows = []
    for r in rows:
        d = dict(r)
        d["status_cn"] = STATUS_MAP.get(d.get("status"), d.get("status", "未知"))
        d["domain_cn"] = DOMAIN_MAP.get(d.get("domain"), d.get("domain", "未知"))
        d["risk_cn"] = RISK_MAP.get(d.get("risk_level"), d.get("risk_level", "未知"))
        raw_time = d.get("created_at", "")
        if raw_time and "T" in raw_time: d["created_at"] = raw_time[:19].replace("T", " ")
        d["action"] = "查看"
        d["delete"] = "删除"
        result_rows.append(d)
    return result_rows

@callback(
    Output("agent-v2-create-drawer", "is_open", allow_duplicate=True),
    Output("agent-v2-feedback", "children", allow_duplicate=True),
    Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-agent-v2-create-save", "n_clicks"),
    State("agent-v2-template", "value"), State("agent-v2-batch-id", "value"), State("agent-v2-s2-phage-id", "value"), State("agent-v2-s2-host-id", "value"), State("agent-v2-pathogen-id", "value"), State("agent-v2-date-from", "value"), State("agent-v2-date-to", "value"),
    prevent_initial_call=True,
)
def create_agent_task(_, template_id, batch_id, s2_phage, s2_host, pathogen_id, date_from, date_to):
    identity = _current_identity()
    if not identity["id"]: return no_update, dbc.Alert("请先登录", color="danger"), no_update
    try:
        rt = get_agent_runtime()
        if template_id == "SCI-S1-BATCH-COMPLETENESS":
            if not batch_id: return no_update, dbc.Alert("批次 ID 必填", color="danger"), no_update
            task, _ = rt.s1_service.create_task(experiment_batch_id=batch_id.strip(), submitted_by=identity["id"], user_role=identity["role"])
        elif template_id == "SCI-S2-EVIDENCE-PACKAGE-DRAFT":
            if not s2_phage or not s2_host: return no_update, dbc.Alert("噬菌体和宿主 ID 必填", color="danger"), no_update
            task, _ = rt.s2_service.create_task(phage_id=s2_phage.strip(), host_strain_id=s2_host.strip(), submitted_by=identity["id"], user_role=identity["role"])
        elif template_id == "INT-I1-PERIODIC-BRIEF-DRAFT":
            if identity["role"] not in {"analyst", "data_manager", "admin"}: return no_update, dbc.Alert("无权创建", color="danger"), no_update
            if not pathogen_id or not date_from or not date_to: return no_update, dbc.Alert("必填项缺失", color="danger"), no_update
            task, _ = rt.i1_service.create_task(pathogen_id=pathogen_id.strip(), date_from=date_from, date_to=date_to, submitted_by=identity["id"], user_role=identity["role"])
        else: return no_update, dbc.Alert("未知模板", color="danger"), no_update
        return False, dbc.Alert(f"任务已创建：{task.task_id}", color="success"), 1
    except Exception as e: return no_update, dbc.Alert(f"创建失败：{e}", color="danger"), no_update

@callback(
    Output("store-agent-v2-task-id", "data"), Output("agent-v2-detail-drawer", "is_open"), Output("store-agent-v2-delete-id", "data"), Output("agent-v2-delete-modal", "is_open"),
    Input("agent-v2-grid", "cellClicked"), State("agent-v2-grid", "rowData"), prevent_initial_call=True,
)
def handle_grid_click(cell, row_data):
    if not cell: return no_update, no_update, no_update, no_update
    row = cell.get("data") or (row_data[cell.get("rowIndex")] if cell.get("rowIndex") is not None else None)
    if not row or not row.get("task_id"): return no_update, no_update, no_update, no_update
    col_id = cell.get("colId"); task_id = row.get("task_id")
    if col_id == "action": return task_id, True, no_update, no_update
    elif col_id == "delete": return no_update, no_update, task_id, True
    return no_update, no_update, no_update, no_update

@callback(
    Output("agent-v2-delete-modal", "is_open", allow_duplicate=True), Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True), Output("agent-v2-feedback", "children", allow_duplicate=True),
    Input("btn-agent-v2-del-confirm", "n_clicks"), Input("btn-agent-v2-del-cancel", "n_clicks"), State("store-agent-v2-delete-id", "data"), prevent_initial_call=True,
)
def confirm_delete_task(confirm_n, cancel_n, task_id):
    if ctx.triggered_id == "btn-agent-v2-del-cancel" or not task_id: return False, no_update, no_update
    try:
        rt = get_agent_runtime()
        with rt.driver.session() as s:
            plan_ids = [r["pid"] for r in s.run("MATCH (p:AgentPlan {task_id: $tid}) RETURN p.plan_id AS pid", tid=task_id)]
            s.run("MATCH (t:AgentTask {task_id: $tid}) DETACH DELETE t", tid=task_id)
            s.run("MATCH (p:AgentPlan {task_id: $tid}) DETACH DELETE p", tid=task_id)
            s.run("MATCH (a:AgentArtifact {task_id: $tid}) DETACH DELETE a", tid=task_id)
            s.run("MATCH (ap:AgentApproval {task_id: $tid}) DETACH DELETE ap", tid=task_id)
            s.run("MATCH (i:AgentIntervention {task_id: $tid}) DETACH DELETE i", tid=task_id)
            s.run("MATCH (c:ContextSnapshot {task_id: $tid}) DETACH DELETE c", tid=task_id)
            for pid in plan_ids: s.run("MATCH (s:AgentStep {plan_id: $pid}) DETACH DELETE s", pid=pid)
        return False, 1, dbc.Alert("任务已删除", color="success", duration=3000)
    except Exception as e: return False, no_update, dbc.Alert(f"删除失败：{e}", color="danger")

def _render_artifact(a):
    status_color = {ArtifactStatus.APPROVED: "success", ArtifactStatus.RESULT_REVIEW: "warning", ArtifactStatus.NEEDS_REVISION: "warning", ArtifactStatus.PARTIALLY_APPROVED: "warning", ArtifactStatus.REJECTED: "danger", ArtifactStatus.SUPERSEDED: "secondary"}.get(a.status, "secondary")
    type_cn = ARTIFACT_TYPE_MAP.get(a.artifact_type.value, a.artifact_type.value)
    return dbc.Card(className="mb-2", children=[
        dbc.CardHeader([html.Strong(f"{type_cn} v{a.version}"), dbc.Badge(a.status.value, color=status_color, className="ms-2"), html.Span(f" · {a.checksum[:12]}…", style={"fontSize": "11px", "color": "var(--c-text-muted)", "fontFamily": "monospace"})]),
        dbc.CardBody([html.Details([html.Summary("查看结构化结果", style={"cursor": "pointer"}), html.Pre(json.dumps(a.content, ensure_ascii=False, indent=2, default=str), style={"maxHeight": "300px", "overflow": "auto", "fontSize": "12px"})])]),
    ])

@callback(
    Output("agent-v2-detail-summary", "children"), Output("agent-v2-plan-panel", "children"), Output("agent-v2-result-panel", "children"), Output("agent-v2-timeline", "children"),
    Output("btn-agent-v2-plan-approve", "style"), Output("btn-agent-v2-execute", "style"), Output("btn-agent-v2-result-approve", "style"), Output("btn-agent-v2-result-partial", "style"), Output("btn-agent-v2-result-reject", "style"), Output("btn-agent-v2-result-reject-final", "style"),
    Output("btn-agent-v2-retry", "style"), Output("btn-agent-v2-revise", "style"), Output("btn-agent-v2-replan", "style"), Output("btn-agent-v2-pause", "style"), Output("btn-agent-v2-resume", "style"), Output("btn-agent-v2-cancel", "style"),
    Input("store-agent-v2-task-id", "data"), Input("btn-agent-v2-refresh", "n_clicks"),
)
def load_task_detail(task_id, _):
    hidden = {"display": "none"}; shown = {"display": "inline-block"}
    empty = ("", "", "", "", hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden)
    if not task_id: return empty
    try:
        rt = get_agent_runtime()
        task = rt.task_repository.get(task_id)
        if task is None: return (dbc.Alert("任务不存在", color="danger"), "", "", "", hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden)
        
        plan = rt.plan_repository.get(task.current_plan_id) if task.current_plan_id else None
        artifacts = rt.artifact_repository.list_for_task(task_id)

        status_cn = STATUS_MAP.get(task.status.value, task.status.value)
        risk_cn = RISK_MAP.get(task.risk_level.value, task.risk_level.value)
        
        summary = html.Div([
            html.Div([html.B("任务 ID："), html.Code(task.task_id)]), html.Div([html.B("类型："), html.Span(getattr(task, "task_type", "未知"))]),
            html.Div([html.B("状态："), html.Span(status_cn)]), html.Div([html.B("请求："), html.Span(task.user_request)]),
            html.Div([html.B("风险："), html.Span(risk_cn)]), html.Div([html.B("发起人："), html.Span(task.submitted_by)]), html.Div([html.B("Correlation："), html.Code(task.correlation_id)]),
        ], style={"lineHeight": "2"})

        if plan:
            plan_panel = html.Div([
                html.Div([html.B("计划："), html.Code(plan.plan_id)]), html.Div([html.B("版本："), html.Span(str(plan.version))]),
                html.Div([html.B("状态："), html.Span(plan.status.value)]), html.Div([html.B("目标："), html.Span(plan.goal_summary)]),
                html.Ol([html.Li(f"{s.name} · {STEP_STATUS_MAP.get(s.status.value, s.status.value)} · {s.tool_id or '-'}") for s in plan.steps]),
            ])
        else: plan_panel = dbc.Alert("暂无计划", color="secondary")

        if artifacts:
            families = {}
            for a in artifacts: families.setdefault(a.artifact_family_id, []).append(a)
            groups = []
            for family_id, versions in families.items():
                versions.sort(key=lambda x: x.version, reverse=True)
                groups.append(html.Div([html.Div(f"产物族 {family_id}", style={"fontWeight": "600", "fontSize": "12px", "marginTop": "8px"}), *[_render_artifact(a) for a in versions]]))
            result_panel = html.Div(groups)
        else: result_panel = dbc.Alert("尚无执行结果", color="secondary")

        try: events = rt.timeline_service.get_task_timeline(task_id, limit=200)
        except Exception: events = []
        timeline = html.Div([html.Div([
            html.Div([html.Code(e.get("event_type") or "?"), html.Span(f" · {e.get('actor_id') or '-'}", style={"color": "var(--c-text-muted)", "fontSize": "12px"})]),
            html.Div(e.get("reason") or "", style={"fontSize": "12px"}), html.Div(str(e.get("timestamp") or ""), style={"fontSize": "11px", "color": "var(--c-text-muted)"}),
        ], style={"borderLeft": "3px solid var(--c-primary)", "paddingLeft": "12px", "marginBottom": "10px"}) for e in events]) if events else html.Div("暂无审计事件", style={"color": "var(--c-text-muted)"})

        is_reviewer = _current_identity()["role"] in {"data_manager", "admin"}
        plan_approve = shown if (task.status == TaskStatus.PLAN_REVIEW and is_reviewer) else hidden
        execute = shown if task.status == TaskStatus.EXECUTING else hidden
        is_result_review = (task.status == TaskStatus.RESULT_REVIEW and is_reviewer)
        has_failed_step = plan is not None and any(s.status == StepStatus.FAILED for s in plan.steps)
        has_revisable_artifact = any(a.status in {ArtifactStatus.NEEDS_REVISION, ArtifactStatus.PARTIALLY_APPROVED} for a in artifacts)

        return (summary, plan_panel, result_panel, timeline,
                plan_approve, execute, shown if is_result_review else hidden, shown if is_result_review else hidden, shown if is_result_review else hidden, shown if is_result_review else hidden,
                shown if (task.status in {TaskStatus.FAILED, TaskStatus.PAUSED} and has_failed_step) else hidden,
                shown if (task.status == TaskStatus.NEEDS_REVISION and has_revisable_artifact) else hidden,
                shown if task.status == TaskStatus.NEEDS_REVISION else hidden,
                shown if task.status in {TaskStatus.EXECUTING, TaskStatus.WAITING_INPUT, TaskStatus.WAITING_APPROVAL} else hidden,
                shown if task.status == TaskStatus.PAUSED else hidden,
                shown if task.status not in {TaskStatus.CANCELLED, TaskStatus.COMPLETED, TaskStatus.REJECTED} else hidden)
    except Exception as e:
        return (dbc.Alert(f"渲染详情失败：{e}", color="danger"), "", "", "", hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden, hidden)

def _build_payload(task):
    t = getattr(task, "task_type", "")
    if t == "SCI-S1-BATCH-COMPLETENESS": return {"experiment_batch_id": task.scope.get("experiment_batch_id", "")}
    if t == "SCI-S2-EVIDENCE-PACKAGE-DRAFT": return {"phage_id": task.scope.get("phage_id", ""), "host_strain_id": task.scope.get("host_strain_id", "")}
    if t == "INT-I1-PERIODIC-BRIEF-DRAFT": return {"pathogen_id": task.scope.get("pathogen_id", ""), "date_from": task.scope.get("date_from", ""), "date_to": task.scope.get("date_to", "")}
    return {}

def _tool_version_for(task, rt):
    t = getattr(task, "task_type", "")
    if t == "SCI-S1-BATCH-COMPLETENESS": return rt.batch_tool.version
    if t == "SCI-S2-EVIDENCE-PACKAGE-DRAFT": return rt.s2_draft_tool.version
    if t == "INT-I1-PERIODIC-BRIEF-DRAFT": return rt.i1_brief_tool.version
    return None

def _template_generated_by(task_type):
    return {"SCI-S1-BATCH-COMPLETENESS": "SCI-S1-TEMPLATE", "SCI-S2-EVIDENCE-PACKAGE-DRAFT": "SCI-S2-TEMPLATE", "INT-I1-PERIODIC-BRIEF-DRAFT": "INT-I1-TEMPLATE"}.get(task_type, "SYSTEM")

@callback(
    Output("agent-v2-feedback", "children", allow_duplicate=True), Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-agent-v2-plan-approve", "n_clicks"), State("store-agent-v2-task-id", "data"), prevent_initial_call=True,
)
def approve_plan(_, task_id):
    identity = _current_identity()
    if identity["role"] not in {"data_manager", "admin"}: return dbc.Alert("无审核权限", color="danger"), no_update
    try:
        rt = get_agent_runtime()
        task = rt.task_repository.get(task_id)
        if task is None or task.status != TaskStatus.PLAN_REVIEW: return dbc.Alert("不在 PLAN_REVIEW", color="warning"), no_update

        approval = rt.approval_service.request_approval(task_id=task_id, approval_type=ApprovalType.PLAN, requested_by=task.assigned_agent, requested_from_role=identity["role"], plan_id=task.current_plan_id, plan_version=task.current_plan_version, correlation_id=task.correlation_id)
        rt.approval_service.decide(approval.approval_id, decision=ApprovalDecision.APPROVED, decided_by=identity["id"], decided_by_role=identity["role"], comment="批准", correlation_id=task.correlation_id)
        rt.task_service.approve_plan(task_id, approval_id=approval.approval_id, approval_validator=rt.approval_service.is_valid_approval, actor_id=identity["id"])

        t = getattr(task, "task_type", "")
        if t == "SCI-S1-BATCH-COMPLETENESS": rt.s1_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
        elif t == "SCI-S2-EVIDENCE-PACKAGE-DRAFT": rt.s2_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
        elif t == "INT-I1-PERIODIC-BRIEF-DRAFT": rt.i1_service.activate_approved_task(task_id=task_id, actor_id=identity["id"], user_role=identity["role"])
        else: return dbc.Alert("未知任务类型", color="danger"), no_update
        return dbc.Alert("已批准", color="success"), 1
    except Exception as e: return dbc.Alert(f"批准失败：{e}", color="danger"), no_update

@callback(
    Output("agent-v2-feedback", "children", allow_duplicate=True), Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-agent-v2-execute", "n_clicks"), State("store-agent-v2-task-id", "data"), prevent_initial_call=True,
)
def execute_task(_, task_id):
    identity = _current_identity()
    try:
        rt = get_agent_runtime()
        task = rt.task_repository.get(task_id)
        if task is None: return dbc.Alert("任务不存在", color="danger"), no_update
        plan = rt.plan_repository.get(task.current_plan_id)
        if plan is None or not plan.steps: return dbc.Alert("无可执行步骤", color="danger"), no_update
        step = next((s for s in plan.steps if s.status == StepStatus.PENDING), None)
        if step is None: return dbc.Alert("没有 PENDING 步骤", color="warning"), no_update

        payload = _build_payload(task)
        tool_version = step.tool_version or _tool_version_for(task, rt)
        if tool_version is None: return dbc.Alert("未知类型，无法执行", color="danger"), no_update

        artifact = rt.execution_service.execute_step(task_id=task_id, step_id=step.step_id, payload=payload, user_id=identity["id"], user_role=identity["role"], tool_version=tool_version)
        return dbc.Alert(f"执行完成，结果已送审：{artifact.artifact_id}", color="success"), 1
    except Exception as e: return dbc.Alert(f"执行失败：{e}", color="danger"), no_update

@callback(
    Output("agent-v2-feedback", "children", allow_duplicate=True), Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-agent-v2-result-approve", "n_clicks"), Input("btn-agent-v2-result-partial", "n_clicks"), Input("btn-agent-v2-result-reject", "n_clicks"), Input("btn-agent-v2-result-reject-final", "n_clicks"),
    State("store-agent-v2-task-id", "data"), State("agent-v2-intervention-reason", "value"), prevent_initial_call=True,
)
def review_result(approve_n, partial_n, reject_n, reject_final_n, task_id, reason):
    identity = _current_identity()
    if identity["role"] not in {"data_manager", "admin"}: return dbc.Alert("无审核权限", color="danger"), no_update
    trigger = ctx.triggered_id
    if not trigger or not task_id: return no_update, no_update

    decision_map = {"btn-agent-v2-result-approve": (ApprovalDecision.APPROVED, "人工审核通过"), "btn-agent-v2-result-partial": (ApprovalDecision.PARTIALLY_APPROVED, "部分批准"), "btn-agent-v2-result-reject": (ApprovalDecision.NEEDS_REVISION, "退回修订"), "btn-agent-v2-result-reject-final": (ApprovalDecision.REJECTED, "拒绝结果")}
    if trigger not in decision_map: return no_update, no_update
    decision, default_comment = decision_map[trigger]
    comment = reason or default_comment

    approved_scope = None; rejected_scope = None
    if decision == ApprovalDecision.PARTIALLY_APPROVED:
        if not reason or not reason.strip(): return dbc.Alert("部分批准必须在原因栏填写获批内容（多项用英文逗号分隔）", color="danger"), no_update
        approved_scope = [s.strip() for s in reason.split(",") if s.strip()]; rejected_scope = []

    try:
        rt = get_agent_runtime()
        task = rt.task_repository.get(task_id)
        if task is None or task.status != TaskStatus.RESULT_REVIEW: return dbc.Alert("不在 RESULT_REVIEW", color="warning"), no_update
        artifacts = rt.artifact_repository.list_for_task(task_id)
        review_artifacts = [a for a in artifacts if a.status == ArtifactStatus.RESULT_REVIEW]
        if not review_artifacts: return dbc.Alert("没有待审核 Artifact", color="warning"), no_update
        artifact = review_artifacts[-1]
        
        approval = rt.result_review_service.request_review(task_id=task_id, artifact_id=artifact.artifact_id, requested_by=task.assigned_agent, reviewer_role=identity["role"], reviewer_user_id=identity["id"])
        rt.result_review_service.decide(approval_id=approval.approval_id, decision=decision, reviewer_id=identity["id"], reviewer_role=identity["role"], comment=comment, approved_scope=approved_scope, rejected_scope=rejected_scope)
        return dbc.Alert(f"结果审核完成：{decision.value}", color="success"), 1
    except Exception as e: return dbc.Alert(f"审核失败：{e}", color="danger"), no_update

@callback(
    Output("agent-v2-feedback", "children", allow_duplicate=True), Output("btn-agent-v2-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-agent-v2-retry", "n_clicks"), Input("btn-agent-v2-revise", "n_clicks"), Input("btn-agent-v2-replan", "n_clicks"), Input("btn-agent-v2-pause", "n_clicks"), Input("btn-agent-v2-resume", "n_clicks"), Input("btn-agent-v2-cancel", "n_clicks"),
    State("store-agent-v2-task-id", "data"), State("agent-v2-intervention-reason", "value"), prevent_initial_call=True,
)
def dispatch_action(*_, task_id=None, reason=None):
    trigger = ctx.triggered_id
    if not trigger or not task_id: return no_update, no_update
    if not reason or not reason.strip(): return dbc.Alert("必须填写原因", color="danger"), no_update
    identity = _current_identity()
    try:
        rt = get_agent_runtime()
        if trigger == "btn-agent-v2-pause": rt.intervention_service.pause(task_id, requested_by=identity["id"], reason=reason.strip()); msg = "已暂停"
        elif trigger == "btn-agent-v2-resume": rt.intervention_service.resume(task_id, requested_by=identity["id"], reason=reason.strip()); msg = "已恢复"
        elif trigger == "btn-agent-v2-cancel": rt.intervention_service.cancel(task_id, requested_by=identity["id"], reason=reason.strip()); msg = "已取消"
        elif trigger == "btn-agent-v2-retry":
            task = rt.task_repository.get(task_id); plan = rt.plan_repository.get(task.current_plan_id)
            failed = next((s for s in plan.steps if s.status == StepStatus.FAILED), None)
            if failed is None: return dbc.Alert("无失败步骤", color="warning"), no_update
            rt.step_retry_service.prepare_retry(task_id=task_id, step_id=failed.step_id, requested_by=identity["id"], reason=reason.strip())
            payload = _build_payload(task); tool_version = failed.tool_version or _tool_version_for(task, rt)
            rt.execution_service.execute_step(task_id=task_id, step_id=failed.step_id, payload=payload, user_id=identity["id"], user_role=identity["role"], tool_version=tool_version); msg = "已重试"
        elif trigger == "btn-agent-v2-revise":
            task = rt.task_repository.get(task_id); artifacts = rt.artifact_repository.list_for_task(task_id)
            candidate = next((a for a in artifacts if a.status in {ArtifactStatus.NEEDS_REVISION, ArtifactStatus.PARTIALLY_APPROVED}), None)
            if candidate is None: return dbc.Alert("无可修订产物", color="warning"), no_update
            payload = _build_payload(task); tool_version = _tool_version_for(task, rt)
            new_art = rt.artifact_revision_service.execute_revision(task_id=task_id, previous_artifact_id=candidate.artifact_id, payload=payload, user_id=identity["id"], user_role=identity["role"], tool_version=tool_version, revision_instruction=reason.strip()); msg = f"已生成 v{new_art.version}"
        elif trigger == "btn-agent-v2-replan":
            task = rt.task_repository.get(task_id)
            rt.replan_service.create_revised_plan(task_id, revision_comment=reason.strip(), generated_by=_template_generated_by(getattr(task, "task_type", "")))
            rt.task_service.submit_plan_for_review(task_id, actor_id=_template_generated_by(getattr(task, "task_type", ""))); msg = "已生成修订计划"
        else: return no_update, no_update
        return dbc.Alert(msg, color="success"), 1
    except Exception as e: return dbc.Alert(f"操作失败：{e}", color="danger"), no_update