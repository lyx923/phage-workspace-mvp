# pages/admin/data_import.py
import traceback
import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc

from data_access.audit import audit_danger_op
from data_access.queries import dataset_counts
from config import get_driver

dash.register_page(__name__, path="/admin/data-import", name="数据导入")

DATASETS = [
    {"name": "公开噬菌体基因组库", "node": "Phage",        "source": "NCBI RefSeq"},
    {"name": "去标识化临床病例集", "node": "ClinicalCase", "source": "内部去标识化"},
    {"name": "裂解实验历史记录",   "node": "LysisAssay",   "source": "内部实验数据库"},
    {"name": "竞争情报基础数据",   "node": "Organization", "source": "公开信息整理"},
]

DANGER_ACTIONS = [
    {
        "id": "danger-clear-all",
        "label": "清空并重新导入全部数据",
        "desc": "将删除 Neo4j 全部节点和关系，执行完整的 CSV 导入流程，并生成 v0.7 实验演示数据。",
        "confirm_title": "⚠️ 清空全库数据",
        "confirm_desc": "此操作将永久删除全库并重新导入 data 目录下的所有数据。操作后无法恢复。",
    },
    {
        "id": "danger-clear-domain",
        "label": "清空 Scientific + CI 域数据",
        "desc": "仅删除 Scientific 和 CI 域的节点和关系，Foundation 层（Pathogen / Organization 等）保留。",
        "confirm_title": "⚠️ 清空指定域数据",
        "confirm_desc": "将删除 Scientific 和 CI 域的全部节点和关系。Foundation 共享层保留。",
    },
    {
        "id": "danger-reinit-schema",
        "label": "重新初始化 Schema 约束",
        "desc": "删除并重建全部 Neo4j 索引和唯一性约束，会造成短暂写入锁定。",
        "confirm_title": "⚠️ 重置 Schema 约束",
        "confirm_desc": "将删除并重建所有索引和约束，执行期间数据库短暂锁定。",
    },
]


def _dataset_card(ds, count):
    return html.Div(className="surface-card mb-3", children=[
        html.Div([
            html.I(className="bi bi-database-fill-add me-2", style={"color": "var(--c-primary)"}),
            html.Span(ds["name"], style={"fontWeight": "600"}),
            html.Span(f" · {ds['node']}", style={"color": "var(--c-text-muted)", "fontSize": "12px", "marginLeft": "6px"}),
        ], className="surface-card-header"),
        html.Div(className="surface-card-body", children=[
            html.P(ds["name"], style={"fontSize": "13px", "color": "var(--c-text-secondary)"}),
            html.Div([
                html.Span([html.I(className="bi bi-files me-1"), f"{count} 条记录"], style={"fontSize": "12px", "color": "var(--c-text-muted)", "marginRight": "16px"}),
                html.Span([html.I(className="bi bi-link-45deg me-1"), ds["source"]], style={"fontSize": "12px", "color": "var(--c-text-muted)"}),
            ]),
        ]),
    ])


layout = html.Div([
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("数据导入", className="page-title"),
            html.Div("沙箱环境 · 仅使用去标识化历史数据 + 公开来源数据，无 PHI/PII", className="page-subtitle"),
        ]),
    ]),

    dbc.Alert([
        html.I(className="bi bi-shield-lock-fill me-2"),
        html.Strong("沙箱模式声明："),
        " 本平台当前运行于 MVP 沙箱环境，未接入医院生产系统。所有导入数据均已通过去标识化处理，不含 PHI/PII。",
    ], color="info", className="mb-4", style={"fontSize": "13px"}),

    html.H6([html.I(className="bi bi-stack me-2"), "可用数据集"], style={"fontWeight": "700", "marginBottom": "16px"}),
    html.Div(id="di-datasets"),

    html.Div(className="surface-card mb-4", children=[
        html.Div([html.Span([html.I(className="bi bi-terminal me-2"), "操作日志"])], className="surface-card-header"),
        html.Div(id="di-log",
                 style={"background": "#0F172A", "color": "#94A3B8", "fontFamily": "monospace", "fontSize": "12px",
                        "padding": "16px", "minHeight": "100px", "maxHeight": "400px", "overflowY": "auto",
                        "lineHeight": "1.8", "whiteSpace": "pre-wrap"},
                 children="等待操作..."),
    ]),

    html.Div(style={"border": "1px solid #fca5a5", "borderRadius": "10px", "background": "#fff8f8", "padding": "20px", "marginTop": "24px"}, children=[
        html.Div([html.I(className="bi bi-exclamation-octagon-fill me-2"), "危险操作区"],
                 style={"display": "flex", "alignItems": "center", "fontSize": "14px", "fontWeight": "700", "color": "var(--c-danger)", "marginBottom": "12px"}),
        html.P("以下操作将对数据库造成不可逆影响，执行前需输入 DELETE 确认。所有危险操作均会写入 AuditEvent。",
               style={"fontSize": "12px", "color": "#6B7280", "marginBottom": "16px"}),
        *[html.Div([
            html.Div([
                html.Div([html.I(className="bi bi-exclamation-triangle me-2"), a["label"]], style={"fontWeight": "600", "fontSize": "13px", "color": "var(--c-danger)", "marginBottom": "4px"}),
                html.Div(a["desc"], style={"fontSize": "12px", "color": "var(--c-text-secondary)", "maxWidth": "520px"}),
            ], style={"flex": "1"}),
            html.Button([html.I(className="bi bi-play-fill me-1"), "执行"], id={"type": "danger-btn", "index": a["id"]}, className="btn-danger-custom"),
        ], style={"display": "flex", "alignItems": "center", "justifyContent": "space-between", "gap": "16px", "padding": "12px 0", "borderBottom": "1px solid #fca5a5"}) for a in DANGER_ACTIONS],
    ]),

    html.Div(id="di-action-result", className="mt-3"),
])


@callback(
    Output("di-datasets", "children"),
    Input("interval-global", "n_intervals"),
    Input("btn-confirm-ok", "n_clicks"),
)
def cb_load_datasets(_, __):
    try:
        counts = dataset_counts()
    except Exception as e:
        traceback.print_exc()
        counts = {}
    return [_dataset_card(ds, counts.get(ds["node"], 0)) for ds in DATASETS]


@callback(
    Output("store-confirm-payload", "data", allow_duplicate=True),
    Output("store-active-danger-id", "data", allow_duplicate=True),
    Input({"type": "danger-btn", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def cb_danger_btn(n_clicks_list):
    from dash import ctx
    if not any(n_clicks_list) or not ctx.triggered_id:
        return no_update, no_update
    action_id = ctx.triggered_id["index"]
    action = next((a for a in DANGER_ACTIONS if a["id"] == action_id), None)
    if not action:
        return no_update, no_update
    return {"title": action["confirm_title"], "desc": action["confirm_desc"]}, action_id


@callback(
    Output("di-log", "children"),
    Output("di-action-result", "children"),
    Output("store-active-danger-id", "data", allow_duplicate=True),
    Input("btn-confirm-ok", "n_clicks"),
    State("store-active-danger-id", "data"),
    prevent_initial_call=True,
)
def cb_execute_danger(n_clicks, action_id):
    if not n_clicks or not action_id:
        return no_update, no_update, no_update

    logs = []
    result_ui = None

    try:
        if action_id == "danger-clear-all":
            # 调用后端统一调度函数
            from src.scientific.import_service import initialize_all_data
            
            # 使用闭包收集后端打印的进度日志
            def progress(msg):
                logs.append(msg)
            
            success, msg = initialize_all_data(get_driver(), progress_callback=progress)
            
            audit_danger_op(action_id, "全库清空并重新导入")
            
            color = "success" if success else "danger"
            result_ui = dbc.Alert(msg, color=color, dismissable=True)

        elif action_id == "danger-clear-domain":
            with get_driver().session() as s:
                s.run("""
                    MATCH (n)
                    WHERE n:Phage OR n:HostStrain OR n:LysisAssay
                       OR n:ClinicalCase OR n:ScientificEvidencePackage
                       OR n:KnowledgeReuseEvent
                       OR n:IntelligenceEvent OR n:DevelopmentProgram
                       OR n:DecisionRecord
                       OR n:EnzymeGene OR n:ExperimentBatch OR n:BiofilmAssay
                    DETACH DELETE n
                """)
            audit_danger_op(action_id, "清空 Scientific + CI 域")
            logs.append("✅ Scientific + CI 域数据已清空，Foundation 层保留")
            result_ui = dbc.Alert("已清空指定域", color="warning", dismissable=True)

        elif action_id == "danger-reinit-schema":
            with get_driver().session() as s:
                s.run("DROP INDEX enzyme_id_idx IF EXISTS")
                s.run("DROP INDEX batch_id_idx IF EXISTS")
                s.run("DROP INDEX biofilm_id_idx IF EXISTS")
                s.run("DROP INDEX phage_engineered_idx IF EXISTS")

            from src.foundation.schema import create_schema
            create_schema(get_driver())
            
            audit_danger_op(action_id, "Schema 约束重建")
            logs.append("✅ Schema 约束及索引已重新初始化")
            result_ui = dbc.Alert("Schema 已重建", color="warning", dismissable=True)

    except Exception as e:
        traceback.print_exc()
        logs.append(f"❌ 执行失败：{e}")
        result_ui = dbc.Alert(f"执行失败：{e}", color="danger", dismissable=True)

    return "\n".join(logs), result_ui, None