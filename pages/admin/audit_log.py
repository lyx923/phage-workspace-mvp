# pages/admin/audit_log.py
import re
from datetime import datetime, timezone, timedelta

import dash
from dash import html, dcc, Input, Output, State, callback, no_update
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import list_audit_events

dash.register_page(__name__, path="/admin/audit-log", name="审计日志")

LOCAL_TZ = timezone(timedelta(hours=8))

# 后端受控词表里的 action_type
ACTION_TYPE_OPTIONS = [
    {"label": "CREATE",          "value": "CREATE"},
    {"label": "UPDATE",          "value": "UPDATE"},
    {"label": "STATUS_CHANGE",   "value": "STATUS_CHANGE"},
    {"label": "LINK_CREATE",     "value": "LINK_CREATE"},
    {"label": "LINK_DELETE",     "value": "LINK_DELETE"},
    {"label": "REVIEW_APPROVE",  "value": "REVIEW_APPROVE"},
    {"label": "REVIEW_REJECT",   "value": "REVIEW_REJECT"},
    {"label": "DATA_CORRECTION", "value": "DATA_CORRECTION"},
    {"label": "MIGRATION",       "value": "MIGRATION"},
]

OBJECT_TYPE_OPTIONS = [
    {"label": "Organization",            "value": "Organization"},
    {"label": "DevelopmentProgram",      "value": "DevelopmentProgram"},
    {"label": "IntelligenceEvent",       "value": "IntelligenceEvent"},
    {"label": "EngineeringStrategy",     "value": "EngineeringStrategy"},
    {"label": "EngineeredPhageConstruct","value": "EngineeredPhageConstruct"},
    {"label": "DecisionRecord",          "value": "DecisionRecord"},
    {"label": "IntelligenceProduct",     "value": "IntelligenceProduct"},
    {"label": "Phage",                   "value": "Phage"},
    {"label": "HostStrain",              "value": "HostStrain"},
    {"label": "ClinicalCase",            "value": "ClinicalCase"},
    {"label": "System",                  "value": "System"},
]


def _fmt_ts(v):
    if v is None:
        return ""
    try:
        if isinstance(v, str):
            s = v.strip().replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(s)
            except ValueError:
                return v[:19]
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        if hasattr(v, "to_native"):
            v = v.to_native()
        if hasattr(v, "strftime"):
            if getattr(v, "tzinfo", None) is None:
                v = v.replace(tzinfo=timezone.utc)
            return v.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")
        return str(v)
    except Exception:
        return str(v)


COLUMNS = [
    {"field": "id", "headerName": "AuditEvent ID", "width": 180,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "action_type", "headerName": "操作类型", "width": 150},
    {"field": "object_type", "headerName": "对象类型", "width": 200},
    {"field": "object_id", "headerName": "对象 ID", "width": 200,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "actor_id", "headerName": "操作者", "width": 140},
    {"field": "reason", "headerName": "备注", "flex": 2},
    {"field": "timestamp", "headerName": "时间", "width": 170,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
]


layout = html.Div([
    html.Div(id="al-error-banner"),
    html.Div(className="page-header", children=[
        html.Div([
            html.Div("审计日志", className="page-title"),
            html.Div("全量 AuditEvent 查询 · 操作溯源 · 合规审计",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-al-refresh", className="btn-outline-custom",
                        n_clicks=0),
            html.Button([html.I(className="bi bi-download me-1"), "导出 CSV"],
                        id="btn-al-export", className="btn-outline-custom",
                        n_clicks=0),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="al-search", type="text", debounce=True, value="",
                  placeholder="搜索对象 ID 或操作者…", className="filter-search"),
        dcc.Dropdown(id="al-action-filter",
                     options=[{"label": "全部动作", "value": ""}] + ACTION_TYPE_OPTIONS,
                     value="", clearable=False, style={"width": "180px"}),
        dcc.Dropdown(id="al-object-filter",
                     options=[{"label": "全部对象", "value": ""}] + OBJECT_TYPE_OPTIONS,
                     value="", clearable=False, style={"width": "220px"}),
        html.Div(id="al-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="al-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 20,
                "domLayout": "autoHeight",
            },
            style={"height": None, "minHeight": "500px"},
        ),
    ]),
    dcc.Download(id="al-download"),
])


@callback(
    Output("al-grid", "rowData"),
    Output("al-count-label", "children"),
    Output("al-error-banner", "children"),
    Input("btn-al-refresh", "n_clicks"),
    Input("al-search", "value"),
    Input("al-action-filter", "value"),
    Input("al-object-filter", "value"),
)
def cb_load(_, search, action, obj):
    try:
        rows = list_audit_events(action_type=action or "",
                                  object_type=obj or "")
        # 前端过滤 search
        if search:
            kw = search.lower()
            rows = [r for r in rows
                    if kw in str(r.get("object_id", "")).lower()
                    or kw in str(r.get("actor_id", "")).lower()]
        # 时间格式化
        for r in rows:
            r["timestamp"] = _fmt_ts(r.get("timestamp"))
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}",
                                          color="danger", className="mb-3")


# ============================================================
# 导出 CSV
# ============================================================
@callback(
    Output("al-download", "data"),
    Input("btn-al-export", "n_clicks"),
    State("al-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_al_export(n_clicks, rows):
    if not n_clicks or not rows:
        return no_update
    try:
        import pandas as pd
        df = pd.DataFrame(rows)
        # 只导出当前列（顺序一致）
        cols = ["id", "action_type", "object_type", "object_id",
                "actor_id", "reason", "timestamp"]
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return dcc.send_data_frame(
            df.to_csv, f"audit_log_{ts}.csv",
            index=False, encoding="utf-8-sig")
    except Exception:
        return no_update