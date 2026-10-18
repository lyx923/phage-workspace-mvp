# pages/scientific/clinical_cases.py
import dash
from dash import html, dcc, Input, Output, State, callback, no_update, ctx
import dash_bootstrap_components as dbc
import dash_ag_grid as dag

from data_access.queries import (
    list_clinical_cases, list_phages, list_host_strains, _run,
)
from data_access.audit import audit
from config import get_driver
from src.shared.evidence_source import get_or_create_pathogen

dash.register_page(__name__, path="/scientific/clinical-cases", name="临床病例")

OUTCOME_OPTIONS = [
    {"label": "治愈",  "value": "cured"},
    {"label": "好转",  "value": "improved"},
    {"label": "未愈",  "value": "unchanged"},
]

# ============================================================
# ★ 扩充后的临床结局中英文映射
# ============================================================
OUTCOME_MAP = {
    "cured": "🟢 治愈",
    "improved": "🟡 好转",
    "unchanged": "🔴 未愈",
    "not improved": "🔴 未愈",
    "cyclic clearance/relapse": "🔄 周期性清除/复发",
    "relapsed then cured": "🟡 复发后治愈",
    "clearance": "🟢 已清除",
    "persistent": "🔴 持续感染",
    "bacteria decreased": "🟡 细菌减少"
}

COLUMNS = [
    {"field": "id", "headerName": "病例 ID", "width": 140,
     "cellStyle": {"fontFamily": "monospace", "fontSize": "11px"}},
    {"field": "infection_type", "headerName": "感染类型", "width": 130},
    {"field": "pathogen_species", "headerName": "病原物种", "flex": 1},
    {"field": "host_strain", "headerName": "宿主菌株", "width": 160},
    {"field": "phage_treatment", "headerName": "噬菌体治疗", "flex": 1},
    # ★ 改为中文字段
    {"field": "outcome_cn", "headerName": "临床结局", "width": 180},
    # ★ 新增操作列
    {"field": "actions", "headerName": "操作", "width": 120,
     "sortable": False, "filter": False,
     "cellStyle": {"color": "var(--c-primary)", "cursor": "pointer", "fontWeight": "bold", "textAlign": "center"}},
]


def _list_pathogen_options():
    try:
        rows = _run("MATCH (p:Pathogen) RETURN p.species AS species ORDER BY species")
        return [{"label": r["species"], "value": r["species"]}
                for r in rows if r.get("species")]
    except Exception:
        return []


layout = html.Div([
    html.Div(id="cc-error-banner"),

    # 合规声明
    html.Div(
        [html.I(className="bi bi-shield-lock-fill me-2"),
         "所有病例数据已通过去标识化处理，不含 PHI/PII，仅限沙箱环境使用。"],
        style={"background": "#EFF6FF", "color": "#1E40AF",
               "border": "1px solid #BFDBFE", "borderRadius": "8px",
               "padding": "12px 16px", "marginBottom": "16px",
               "fontSize": "13px"},
    ),

    html.Div(className="page-header", children=[
        html.Div([
            html.Div("临床病例", className="page-title"),
            html.Div("管理所有 ClinicalCase · 感染类型 · 治疗结局",
                     className="page-subtitle"),
        ]),
        html.Div(className="page-actions", children=[
            html.Button([html.I(className="bi bi-arrow-clockwise me-1"), "刷新"],
                        id="btn-cc-refresh", className="btn-outline-custom"),
            html.Button([html.I(className="bi bi-plus-lg me-1"), "新增病例"],
                        id="btn-cc-new", className="btn-primary-custom"),
        ]),
    ]),
    html.Div(className="filter-bar", children=[
        dcc.Input(id="cc-search", type="text", debounce=True, value="",
                  placeholder="搜索病例 ID 或病原物种…", className="filter-search"),
        dcc.Dropdown(id="cc-outcome-filter",
                     options=[{"label": "全部结局", "value": ""}] + OUTCOME_OPTIONS,
                     value="", clearable=False, style={"width": "160px"}),
        html.Div(id="cc-count-label",
                 style={"marginLeft": "auto", "fontSize": "12px",
                        "color": "var(--c-text-muted)"}),
    ]),
    html.Div(className="surface-card", children=[
        dag.AgGrid(
            id="cc-grid", columnDefs=COLUMNS, rowData=[],
            dashGridOptions={
                "pagination": True,
                "paginationPageSize": 20,
                "domLayout": "autoHeight",
            },
            style={"height": None, "minHeight": "500px"},
        ),
    ]),

    # 录入表单
    dbc.Offcanvas(
        id="cc-offcanvas", title="新增临床病例",
        placement="end", is_open=False, style={"width": "580px"},
        children=[dbc.Form([
            dbc.Row([dbc.Label("病例 ID *", width=3),
                     dbc.Col(dbc.Input(id="cc-form-case-id",
                                       placeholder="如 CASE-101"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("感染类型 *", width=3),
                     dbc.Col(dbc.Input(id="cc-form-infection-type",
                                       placeholder="如 Pneumonia"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("感染部位", width=3),
                     dbc.Col(dbc.Input(id="cc-form-infection-site",
                                       placeholder="如 肺部"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("标本类型", width=3),
                     dbc.Col(dbc.Input(id="cc-form-specimen",
                                       placeholder="如 痰液"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("病原 *", width=3),
                     dbc.Col(dcc.Dropdown(id="cc-form-pathogen",
                                          placeholder="选择病原物种",
                                          options=_list_pathogen_options(),
                                          clearable=False), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("宿主菌株", width=3),
                     dbc.Col(dcc.Dropdown(id="cc-form-host",
                                          placeholder="选择宿主菌株（可选）",
                                          options=[]), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("噬菌体", width=3),
                     dbc.Col(dcc.Dropdown(id="cc-form-phages",
                                          placeholder="选择使用的噬菌体（可多选）",
                                          options=[], multi=True), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("临床结局", width=3),
                     dbc.Col(dcc.Dropdown(id="cc-form-outcome",
                                          options=OUTCOME_OPTIONS,
                                          placeholder="治愈 / 好转 / 未愈"), width=9)],
                    className="mb-3"),
            dbc.Row([dbc.Label("微生物学结局", width=3),
                     dbc.Col(dbc.Input(id="cc-form-micro",
                                       placeholder="如 细菌清除"), width=9)],
                    className="mb-4"),
            html.Div([
                html.Button("取消", id="btn-cc-cancel",
                            className="btn-outline-custom me-2"),
                html.Button([html.I(className="bi bi-check2 me-1"), "保存"],
                            id="btn-cc-save", className="btn-primary-custom"),
            ], style={"display": "flex", "justifyContent": "flex-end"}),
            html.Div(id="cc-form-feedback", className="mt-3"),
        ])]),

    # ★ 新增：修改结局弹窗
    dcc.Store(id="store-active-case"),
    dbc.Modal(
        id="modal-cc-outcome", is_open=False, centered=True,
        children=[
            dbc.ModalHeader(dbc.ModalTitle("修改临床结局")),
            dbc.ModalBody([
                html.Div(id="cc-outcome-info", style={"marginBottom": "20px", "background": "#F8FAFC", "padding": "16px", "borderRadius": "8px"}),
                dbc.Row([
                    dbc.Label("新的结局描述", width=3),
                    dbc.Col([
                        dbc.Input(id="cc-outcome-input", placeholder="输入结局，或选择下方快捷选项"),
                        html.Div(style={"marginTop": "10px", "display": "flex", "gap": "8px"}, children=[
                            html.Button("治愈", id="btn-out-cured", className="btn-outline-custom", style={"fontSize": "12px", "padding": "2px 8px"}),
                            html.Button("好转", id="btn-out-improved", className="btn-outline-custom", style={"fontSize": "12px", "padding": "2px 8px"}),
                            html.Button("未愈", id="btn-out-unchanged", className="btn-outline-custom", style={"fontSize": "12px", "padding": "2px 8px"}),
                            html.Button("复发", id="btn-out-relapse", className="btn-outline-custom", style={"fontSize": "12px", "padding": "2px 8px"}),
                        ])
                    ], width=9)
                ])
            ]),
            dbc.ModalFooter([
                html.Button("取消", id="btn-cc-outcome-cancel", className="btn-outline-custom me-2"),
                html.Button("确认修改", id="btn-cc-outcome-save", className="btn-primary-custom"),
            ]),
        ]
    )
])


# ============================================================
# 列表加载与新建逻辑
# ============================================================
@callback(
    Output("cc-grid", "rowData"),
    Output("cc-count-label", "children"),
    Output("cc-error-banner", "children"),
    Input("btn-cc-refresh", "n_clicks"),
    Input("cc-search", "value"),
    Input("cc-outcome-filter", "value"),
    Input("btn-cc-outcome-save", "n_clicks"),
)
def cb_load(_, search, outcome, __):
    try:
        rows = list_clinical_cases(keyword=search or "", outcome=outcome or "")
        
        # ★ 遍历中文化
        for r in rows:
            raw_out = str(r.get("clinical_outcome") or "unknown").strip().lower()
            r["outcome_cn"] = OUTCOME_MAP.get(raw_out, raw_out)
            r["actions"] = "修改"
            
        return rows, f"共 {len(rows)} 条", None
    except Exception as e:
        return [], "加载失败", dbc.Alert(f"Neo4j 连接失败：{e}", color="danger", className="mb-3")


@callback(
    Output("cc-offcanvas", "is_open"),
    Input("btn-cc-new", "n_clicks"),
    Input("btn-cc-cancel", "n_clicks"),
    prevent_initial_call=True,
)
def cb_offcanvas(new_n, cancel_n):
    return ctx.triggered_id == "btn-cc-new"


@callback(
    Output("cc-form-host", "options"),
    Output("cc-form-phages", "options"),
    Input("btn-cc-new", "n_clicks"),
    prevent_initial_call=True,
)
def cb_load_options(_):
    try:
        hosts = list_host_strains()
        host_opts = [{"label": f"{h['label']} ({h['id']})", "value": h["id"]}
                     for h in hosts if h.get("id")]
    except Exception:
        host_opts = []
    try:
        phages = list_phages()
        phage_opts = [{"label": f"{p['name']} ({p['id']})", "value": p["id"]}
                      for p in phages if p.get("id")]
    except Exception:
        phage_opts = []
    return host_opts, phage_opts


@callback(
    Output("cc-form-feedback", "children"),
    Output("cc-offcanvas", "is_open", allow_duplicate=True),
    Output("btn-cc-refresh", "n_clicks", allow_duplicate=True),
    Input("btn-cc-save", "n_clicks"),
    State("cc-form-case-id", "value"),
    State("cc-form-infection-type", "value"),
    State("cc-form-infection-site", "value"),
    State("cc-form-specimen", "value"),
    State("cc-form-pathogen", "value"),
    State("cc-form-host", "value"),
    State("cc-form-phages", "value"),
    State("cc-form-outcome", "value"),
    State("cc-form-micro", "value"),
    prevent_initial_call=True,
)
def cb_save(_, case_id, infection_type, infection_site, specimen,
             pathogen_species, host_id, phage_ids, outcome, micro):
    if not case_id or not case_id.strip():
        return dbc.Alert("病例 ID 不能为空", color="danger"), no_update, no_update
    if not pathogen_species:
        return dbc.Alert("病原物种必填", color="danger"), no_update, no_update
    if not infection_type or not infection_type.strip():
        return dbc.Alert("感染类型必填", color="danger"), no_update, no_update

    try:
        pathogen_id = get_or_create_pathogen(
            get_driver(), species=pathogen_species, actor_id="dash_frontend")

        case_id = case_id.strip()
        phage_ids = phage_ids or []

        with get_driver().session() as s:
            # 查噬菌体名称（同时写入 phage_treatment 字段，双保险）
            treatment_str = ""
            if phage_ids:
                rows = s.run("""
                    UNWIND $pids AS pid
                    MATCH (ph:Phage {phage_id: pid})
                    RETURN collect(ph.name) AS names
                """, pids=phage_ids).single()
                if rows and rows["names"]:
                    treatment_str = ", ".join(rows["names"])

            # 创建/更新病例节点
            s.run("""
                MERGE (c:ClinicalCase {case_id: $cid})
                ON CREATE SET c.created_at = datetime()
                SET c.infection_type = $itype,
                    c.infection_site = $isite,
                    c.specimen_type = $spec,
                    c.phage_treatment = $treatment,
                    c.clinical_outcome = $outcome,
                    c.microbiological_outcome = $micro,
                    c.curated_by = 'dash_frontend',
                    c.curation_date = date(),
                    c.updated_at = datetime()
                WITH c
                MATCH (p:Pathogen {pathogen_id: $pathid})
                MERGE (c)-[:INVOLVES_PATHOGEN]->(p)
            """, cid=case_id, itype=infection_type,
                 isite=infection_site or "", spec=specimen or "",
                 treatment=treatment_str,
                 outcome=outcome or "", micro=micro or "",
                 pathid=pathogen_id)

            # TREATED_WITH 噬菌体
            if phage_ids:
                s.run("""
                    MATCH (c:ClinicalCase {case_id: $cid})
                    UNWIND $pids AS pid
                    MATCH (ph:Phage {phage_id: pid})
                    MERGE (c)-[:TREATED_WITH]->(ph)
                """, cid=case_id, pids=phage_ids)

            # HAS_ISOLATE 宿主菌株
            if host_id:
                s.run("""
                    MATCH (c:ClinicalCase {case_id: $cid})
                    MATCH (h:HostStrain {host_strain_id: $hid})
                    MERGE (c)-[:HAS_ISOLATE]->(h)
                """, cid=case_id, hid=host_id)

        audit("CREATE", "ClinicalCase", case_id,
              delta={"infection_type": infection_type,
                     "pathogen": pathogen_species,
                     "phages": phage_ids, "host_id": host_id},
              reason=f"录入临床病例 {case_id}")
        return dbc.Alert(f"已创建 {case_id}", color="success"), False, 1
    except Exception as e:
        return dbc.Alert(f"保存失败：{e}", color="danger"), no_update, no_update


# ============================================================
# ★ 修改临床结局逻辑
# ============================================================
# 1. 点击操作列，打开弹窗
@callback(
    Output("store-active-case", "data"),
    Output("modal-cc-outcome", "is_open"),
    Output("cc-outcome-info", "children"),
    Output("cc-outcome-input", "value"),
    Input("cc-grid", "cellClicked"),
    State("cc-grid", "rowData"),
    prevent_initial_call=True,
)
def cb_open_outcome_modal(cell, row_data):
    if not cell or cell.get("colId") != "actions":
        return no_update, no_update, no_update, no_update

    rowIndex = cell.get("rowIndex")
    if rowIndex is None or not row_data or len(row_data) <= rowIndex:
        return no_update, no_update, no_update, no_update

    row = row_data[rowIndex]
    case_id = row["id"]
    current_out = row.get("outcome_cn", "未知")

    info_ui = [
        html.Div([html.Span("病例 ID: ", style={"fontWeight": "600"}), html.Span(case_id, style={"fontFamily": "monospace"})], className="mb-2"),
        html.Div([html.Span("当前结局: ", style={"fontWeight": "600"}), html.Span(current_out)])
    ]
    
    # 输入框预填当前的原始英文值
    raw_val = row.get("clinical_outcome", "")
    return case_id, True, info_ui, raw_val


# 2. 快捷选项按钮，回填输入框
@callback(
    Output("cc-outcome-input", "value", allow_duplicate=True),
    Input("btn-out-cured", "n_clicks"),
    Input("btn-out-improved", "n_clicks"),
    Input("btn-out-unchanged", "n_clicks"),
    Input("btn-out-relapse", "n_clicks"),
    prevent_initial_call=True,
)
def cb_quick_outcome(c, i, u, r):
    trigger = ctx.triggered_id
    if trigger == "btn-out-cured": return "cured"
    if trigger == "btn-out-improved": return "improved"
    if trigger == "btn-out-unchanged": return "unchanged"
    if trigger == "btn-out-relapse": return "relapsed then cured"
    return no_update


# 3. 保存修改
@callback(
    Output("modal-cc-outcome", "is_open", allow_duplicate=True),
    Output("btn-cc-refresh", "n_clicks", allow_duplicate=True),
    Output("cc-error-banner", "children", allow_duplicate=True),
    Input("btn-cc-outcome-save", "n_clicks"),
    Input("btn-cc-outcome-cancel", "n_clicks"),
    State("store-active-case", "data"),
    State("cc-outcome-input", "value"),
    prevent_initial_call=True,
)
def cb_save_outcome(save_n, cancel_n, case_id, new_outcome):
    trigger = ctx.triggered_id
    if trigger == "btn-cc-outcome-cancel" or not case_id:
        return False, no_update, no_update

    try:
        with get_driver().session() as s:
            s.run("""
                MATCH (c:ClinicalCase {case_id: $cid})
                SET c.clinical_outcome = $outcome, c.updated_at = datetime()
            """, cid=case_id, outcome=new_outcome.strip())
            
        msg = dbc.Alert(f"病例 {case_id} 的临床结局已更新。", color="success", dismissable=True, duration=3000)
        return False, 1, msg
    except Exception as e:
        return False, no_update, dbc.Alert(f"修改失败：{e}", color="danger", dismissable=True)