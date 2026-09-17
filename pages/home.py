# pages/home.py
import streamlit as st
import json
from config import get_driver


# ==================== 数据库连接 ====================
@st.cache_resource
def get_db():
    return get_driver()


driver = get_db()


# ==================== Apple 风格样式 ====================
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 4rem !important;
        max-width: 1180px;
    }

    /* Hero */
    .apple-hero { text-align: center; padding: 3.5rem 1rem 2.5rem; margin-bottom: 1rem; }
    .apple-hero h1 {
        font-size: 3.6rem; font-weight: 700; letter-spacing: -0.04em; line-height: 1.05; margin: 0;
        background: linear-gradient(135deg, #1d1d1f 0%, #4a4a4d 100%);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    }
    .apple-hero .subtitle { font-size: 1.35rem; color: #6e6e73; margin-top: 1.1rem; font-weight: 400; letter-spacing: -0.012em; }
    .apple-hero .eyebrow { font-size: 0.85rem; color: #0071e3; letter-spacing: 0.08em; font-weight: 600; text-transform: uppercase; margin-bottom: 0.6rem; }

    /* 分区标题 */
    .apple-section {
        font-size: 1.55rem; font-weight: 600; letter-spacing: -0.025em;
        color: #1d1d1f; margin: 3rem 0 0.4rem; padding: 0;
        display: flex; align-items: center; gap: 0.6rem;
    }
    .apple-section .tag {
        font-size: 0.7rem; font-weight: 500; letter-spacing: 0.05em;
        background: #eef2ff; color: #1e40af;
        padding: 0.2rem 0.6rem; border-radius: 100px;
        text-transform: uppercase;
    }
    .apple-section-sub { font-size: 0.95rem; color: #86868b; margin-top: 0.2rem; margin-bottom: 1.4rem; letter-spacing: -0.01em; }

    /* 卡片 */
    .apple-card {
        background: #ffffff; border-radius: 22px; padding: 24px 22px;
        border: 1px solid rgba(0, 0, 0, 0.05);
        box-shadow: 0 1px 2px rgba(0,0,0,0.015), 0 8px 28px rgba(0,0,0,0.035);
        height: 100%; transition: transform 0.25s ease, box-shadow 0.25s ease;
    }
    .apple-card:hover { transform: translateY(-2px); box-shadow: 0 2px 4px rgba(0,0,0,0.02), 0 14px 36px rgba(0,0,0,0.06); }
    .apple-card .label { font-size: 0.78rem; color: #86868b; font-weight: 500; letter-spacing: 0.06em; text-transform: uppercase; }
    .apple-card .value { font-size: 2.75rem; font-weight: 600; color: #1d1d1f; letter-spacing: -0.035em; line-height: 1; margin-top: 12px; }
    .apple-card .sub { font-size: 0.84rem; color: #86868b; margin-top: 10px; letter-spacing: -0.005em; line-height: 1.4; }
    .apple-card .sub b { color: #1d1d1f; font-weight: 600; }

    .apple-card.accent-blue .value   { color: #0071e3; }
    .apple-card.accent-green .value  { color: #34c759; }
    .apple-card.accent-orange .value { color: #ff9500; }
    .apple-card.accent-red .value    { color: #ff3b30; }
    .apple-card.accent-purple .value { color: #af52de; }
    .apple-card.accent-teal .value   { color: #0a84a5; }

    /* 列表小标题 */
    .apple-list-title {
        font-size: 1rem;
        font-weight: 600;
        color: #1d1d1f;
        letter-spacing: -0.01em;
        margin: 28px 0 14px 0;
        padding: 0;
        display: flex;
        align-items: center;
        gap: 0.4rem;
    }

    /* 列表 */
    .apple-list {
        background: #ffffff;
        border-radius: 22px;
        padding: 8px 24px;
        border: 1px solid rgba(0, 0, 0, 0.05);
        box-shadow: 0 1px 2px rgba(0,0,0,0.015), 0 8px 28px rgba(0,0,0,0.035);
        min-height: 380px;
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
    }
    .apple-list-item {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 15px 0;
        border-bottom: 1px solid rgba(0,0,0,0.05);
    }
    .apple-list-item:last-child { border-bottom: none; }
    .apple-list-item .name { font-weight: 500; color: #1d1d1f; font-size: 0.94rem; letter-spacing: -0.005em; }
    .apple-list-item .meta { color: #86868b; font-size: 0.79rem; margin-top: 3px; }
    .apple-list-item .count { font-weight: 600; color: #1d1d1f; font-size: 1.02rem; font-variant-numeric: tabular-nums; }
    .apple-list-item .count.pill { background: #f5f5f7; padding: 4px 12px; border-radius: 100px; font-size: 0.82rem; }

    .apple-list-empty {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 40px 0;
        text-align: center;
        color: #86868b;
        font-size: 0.9rem;
    }

    /* 小徽标 */
    .badge-ok    { background:#e8f9ee; color:#1a7a3a; }
    .badge-warn  { background:#fff5e0; color:#a56400; }
    .badge-alert { background:#ffe9e6; color:#c62828; }

    div[data-testid="stVerticalBlock"] > div:has(.apple-card) { padding: 0; }
    #MainMenu, footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# ==================== ECharts 工具 ====================
def render_echarts(option: dict, height: int = 340, key: str = "chart"):
    html = f"""
    <!DOCTYPE html>
    <html><head><meta charset="utf-8">
    <style>html,body{{margin:0;padding:0;background:transparent;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Display","Segoe UI",sans-serif;}}</style>
    </head><body>
    <div id="{key}" style="width:100%;height:{height}px;"></div>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <script>
    (function(){{
        var el = document.getElementById("{key}");
        var chart = echarts.init(el, null, {{ renderer: 'svg' }});
        chart.setOption({json.dumps(option)});
        window.addEventListener('resize', function () {{ chart.resize(); }});
    }})();
    </script></body></html>
    """
    st.iframe(html, height=height + 16)


# ==================== 数据加载 ====================
@st.cache_data(ttl=90, show_spinner=False)
def load_dashboard_data():
    """
    一次性拉取首页所有统计信息，分 4 类视角：
      - assets  : 核心资产
      - quality : 证据质量
      - ci      : 情报与决策闭环
      - ops     : 运营健康
    """
    with driver.session() as session:

        def one(cypher, **params):
            r = session.run(cypher, **params).single()
            return r[0] if r else 0

        data = {}

        # ============ A. 核心资产 ============
        data["assets"] = {
            "phages":  one("MATCH (p:Phage) RETURN count(p)"),
            "hosts":   one("MATCH (h:HostStrain) RETURN count(h)"),
            "assays":  one("MATCH (a:LysisAssay) RETURN count(a)"),
            "cases":   one("MATCH (c:ClinicalCase) RETURN count(c)"),
            "patients": one("MATCH (p:Patient) RETURN count(p)"),
            "orgs":    one("MATCH (o:Organization) RETURN count(o)"),
            "programs": one("MATCH (d:DevelopmentProgram) RETURN count(d)"),
            "constructs": one("MATCH (ec:EngineeredPhageConstruct) RETURN count(ec)"),
        }

        # ============ B. 证据质量 ============
        dist = {}
        for row in session.run("""
            MATCH (a:LysisAssay)
            RETURN COALESCE(a.evidence_level, 'unknown') AS level, count(a) AS cnt
        """):
            dist[row["level"]] = row["cnt"]

        high_quality = sum(dist.get(l, 0) for l in ["L3", "L4", "L5"])
        total_assays = sum(dist.values()) or 1
        data["quality"] = {
            "dist": dist,
            "L1": dist.get("L1", 0),
            "L2": dist.get("L2", 0),
            "L3": dist.get("L3", 0),
            "L4": dist.get("L4", 0),
            "L5": dist.get("L5", 0),
            "confirmed": high_quality,
            "pending":   dist.get("L1", 0) + dist.get("L2", 0),
            "missing":   dist.get("unknown", 0),
            "high_quality_ratio": round(high_quality / total_assays * 100, 1),
        }

        data["quality"]["proposal_executed"] = one("""
            MATCH (p:EvidenceUpgradeProposal {status: 'executed'})
            RETURN count(p)
        """)
        data["quality"]["proposal_pending"] = one("""
            MATCH (p:EvidenceUpgradeProposal {status: 'pending_review'})
            RETURN count(p)
        """)
        data["quality"]["golden_rules"] = one("""
            MATCH (r:ScientificKnowledgeRule) RETURN count(r)
        """)

        data["quality"]["reuse_confirmed"] = one("""
            MATCH (k:KnowledgeReuseEvent {status: 'confirmed'}) RETURN count(k)
        """)
        data["quality"]["reuse_pending"] = one("""
            MATCH (k:KnowledgeReuseEvent {status: 'detected'}) RETURN count(k)
        """)
        data["quality"]["reuse_total"] = one("""
            MATCH (k:KnowledgeReuseEvent) RETURN count(k)
        """)

        # ============ C. 情报与决策闭环 ============
        data["ci"] = {
            "events":   one("MATCH (e:IntelligenceEvent) RETURN count(e)"),
            "high_impact": one("""
                MATCH (e:IntelligenceEvent)
                WHERE e.event_type IN ['acquisition','merger','ipo','regulatory_approval','clinical_failure']
                RETURN count(e)
            """),
            "briefs":   one("MATCH (b:IntelligenceProduct) RETURN count(b)"),
            "briefs_approved": one("""
                MATCH (b:IntelligenceProduct {review_status: 'approved'}) RETURN count(b)
            """),
            "decisions": one("MATCH (d:DecisionRecord) RETURN count(d)"),
            # ★ 修复：监控企业 = 有情报事件覆盖的企业（而非必须有 monitor 决策）
            "monitored_orgs": one("""
                MATCH (e:IntelligenceEvent)-[:CONCERNS]->(o:Organization)
                RETURN count(DISTINCT o)
            """),
            # 已进入决策监控名单的企业（子集）
            "decision_monitored_orgs": one("""
                MATCH (dec:DecisionRecord {decision_type: 'monitor'})
                      -[:BASED_ON]->(brief:IntelligenceProduct)
                      -[:COVERS]->(org:Organization)
                RETURN count(DISTINCT org)
            """),
            "reviews_approved": one("""
                MATCH (r:Review {decision: 'approved'}) RETURN count(r)
            """),
        }

        # ★ 修复：监控企业列表 = 有情报事件关联的企业
        monitored = []
        for row in session.run("""
            MATCH (e:IntelligenceEvent)-[:CONCERNS]->(org:Organization)
            WITH org, count(DISTINCT e) AS event_count
            RETURN org.canonical_name AS name,
                   org.organization_id AS id,
                   org.headquarters_country AS country,
                   org.organization_type AS type,
                   event_count
            ORDER BY event_count DESC
            LIMIT 5
        """):
            monitored.append(dict(row))
        data["ci"]["monitored_list"] = monitored

        # 近期高影响事件
        recent_high = []
        for row in session.run("""
            MATCH (e:IntelligenceEvent)
            WHERE e.event_type IN ['acquisition','merger','ipo','regulatory_approval']
            OPTIONAL MATCH (o:Organization {organization_id: e.organization_id})
            RETURN e.title AS title, e.event_type AS type,
                   e.event_date AS date, o.canonical_name AS org
            ORDER BY e.event_date DESC
            LIMIT 5
        """):
            recent_high.append(dict(row))
        data["ci"]["recent_high"] = recent_high

        # ============ D. 运营健康 ============
        data["ops"] = {
            "pending_proposals": one("""
                MATCH (p:EvidenceUpgradeProposal {status: 'pending_review'}) RETURN count(p)
            """),
            "pending_packages": one("""
                MATCH (p:ScientificEvidencePackage)
                WHERE p.review_status = 'pending' OR p.status = 'draft'
                RETURN count(p)
            """),
            "pending_qc": one("""
                MATCH (a:LysisAssay {qc_status: 'pending'}) RETURN count(a)
            """),
            "missing_level": data["quality"]["missing"],
            "no_source": one("""
                MATCH (a:LysisAssay)
                WHERE NOT (a)-[:DERIVED_FROM]->(:SourceArtifact)
                RETURN count(a)
            """),
            "no_pathogen": one("""
                MATCH (a:LysisAssay)
                WHERE a.pathogen_id IS NULL
                RETURN count(a)
            """),
            "audit_events": one("MATCH (a:AuditEvent) RETURN count(a)"),
        }

        data["ops"]["events_30d"] = one("""
            MATCH (e:IntelligenceEvent)
            WHERE e.event_date IS NOT NULL AND e.event_date >= toString(date() - duration('P30D'))
            RETURN count(e)
        """)

        return data


# ==================== 渲染 ====================
with st.spinner("加载数据总览..."):
    D = load_dashboard_data()

# ============================================================
# Section A —— 核心资产
# ============================================================
st.markdown(
    '<div class="apple-section">核心资产 <span class="tag">护城河</span></div>',
    unsafe_allow_html=True
)
st.markdown(
    '<div class="apple-section-sub">平台沉淀的可复用数据资产 —— 菌株库、裂解谱、临床案例与病原知识</div>',
    unsafe_allow_html=True
)

A = D["assets"]
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">噬菌体库</div>
        <div class="value">{A['phages']}</div>
        <div class="sub">覆盖 <b>{A['hosts']}</b> 株宿主菌</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">裂解实验</div>
        <div class="value">{A['assays']}</div>
        <div class="sub">互作记录</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">临床案例</div>
        <div class="value">{A['cases']}</div>
        <div class="sub">关联 <b>{A['patients']}</b> 位患者</div>
    </div>""", unsafe_allow_html=True)
with c4:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">竞争情报</div>
        <div class="value">{A['orgs']}</div>
        <div class="sub">覆盖 <b>{A['programs']}</b> 个研发管线</div>
    </div>""", unsafe_allow_html=True)


# ============================================================
# Section B —— 证据质量
# ============================================================
st.markdown(
    '<div class="apple-section">证据质量 <span class="tag">核心价值</span></div>',
    unsafe_allow_html=True
)
st.markdown(
    '<div class="apple-section-sub">高等级证据（L3-L5）的占比，是平台专业度与商业可行性的直接信号</div>',
    unsafe_allow_html=True
)

Q = D["quality"]
b1, b2, b3, b4 = st.columns(4)
with b1:
    st.markdown(f"""
    <div class="apple-card accent-green">
        <div class="label">高等级证据</div>
        <div class="value">{Q['confirmed']}</div>
        <div class="sub">L3–L5 · 占比 <b>{Q['high_quality_ratio']}%</b></div>
    </div>""", unsafe_allow_html=True)
with b2:
    st.markdown(f"""
    <div class="apple-card accent-purple">
        <div class="label">黄金配型规则</div>
        <div class="value">{Q['golden_rules']}</div>
        <div class="sub">经临床验证的配型知识</div>
    </div>""", unsafe_allow_html=True)
with b3:
    st.markdown(f"""
    <div class="apple-card accent-teal">
        <div class="label">证据升级累计</div>
        <div class="value">{Q['proposal_executed']}</div>
        <div class="sub">已执行升级 · 待审 <b>{Q['proposal_pending']}</b></div>
    </div>""", unsafe_allow_html=True)
with b4:
    st.markdown(f"""
    <div class="apple-card accent-orange">
        <div class="label">知识复用</div>
        <div class="value">{Q['reuse_confirmed']}</div>
        <div class="sub">已确认复用 · 待确认 <b>{Q['reuse_pending']}</b></div>
    </div>""", unsafe_allow_html=True)


# ---------- 图表：证据等级分布 + 高等级证据占比 ----------
g1, g2 = st.columns([3, 2])

with g1:
    levels = ["L1", "L2", "L3", "L4", "L5"]
    values = [Q[l] for l in levels]
    bar_option = {
        "grid": {"top": 40, "left": 48, "right": 24, "bottom": 36},
        "tooltip": {
            "trigger": "axis", "axisPointer": {"type": "shadow"},
            "backgroundColor": "rgba(255,255,255,0.98)",
            "borderColor": "rgba(0,0,0,0.05)", "borderWidth": 1,
            "textStyle": {"color": "#1d1d1f", "fontSize": 12},
            "extraCssText": "border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08);"
        },
        "xAxis": {
            "type": "category", "data": levels,
            "axisLine": {"show": False}, "axisTick": {"show": False},
            "axisLabel": {"color": "#86868b", "fontSize": 12, "fontWeight": 500}
        },
        "yAxis": {
            "type": "value",
            "splitLine": {"lineStyle": {"color": "#f0f0f2", "type": "dashed"}},
            "axisLabel": {"color": "#86868b", "fontSize": 11},
            "axisLine": {"show": False}
        },
        "series": [{
            "type": "bar", "data": values, "barWidth": "42%",
            "itemStyle": {
                "borderRadius": [10, 10, 4, 4],
                "color": {
                    "type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                    "colorStops": [
                        {"offset": 0, "color": "#0071e3"},
                        {"offset": 1, "color": "#64b5f6"}
                    ]
                }
            },
            "label": {"show": True, "position": "top", "color": "#1d1d1f", "fontSize": 13, "fontWeight": 600}
        }],
        "backgroundColor": "transparent"
    }
    render_echarts(bar_option, height=340, key="evidenceBar")

with g2:
    confirmed = Q["confirmed"]
    pending   = Q["pending"]
    missing   = Q["missing"]
    donut_option = {
        "tooltip": {
            "trigger": "item",
            "backgroundColor": "rgba(255,255,255,0.98)",
            "borderColor": "rgba(0,0,0,0.05)", "borderWidth": 1,
            "textStyle": {"color": "#1d1d1f", "fontSize": 12},
            "extraCssText": "border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.08);"
        },
        "legend": {
            "bottom": 0, "icon": "circle", "itemWidth": 8, "itemHeight": 8, "itemGap": 18,
            "textStyle": {"color": "#86868b", "fontSize": 11}
        },
        "series": [{
            "type": "pie", "radius": ["62%", "82%"], "center": ["50%", "45%"],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderRadius": 8, "borderColor": "#fff", "borderWidth": 3},
            "label": {"show": False}, "labelLine": {"show": False},
            "emphasis": {
                "scale": True, "scaleSize": 8,
                "label": {"show": True, "fontSize": 14, "fontWeight": 600, "color": "#1d1d1f", "formatter": "{b}\n{c}"}
            },
            "data": [
                {"value": confirmed, "name": "L3-L5 高等级", "itemStyle": {"color": "#34c759"}},
                {"value": pending,   "name": "L1-L2 待升级", "itemStyle": {"color": "#ff9500"}},
                {"value": missing,   "name": "缺失等级",   "itemStyle": {"color": "#ff3b30"}},
            ]
        }],
        "backgroundColor": "transparent"
    }
    render_echarts(donut_option, height=340, key="integrityDonut")


# ============================================================
# Section C —— 情报与决策闭环
# ============================================================
st.markdown(
    '<div class="apple-section">情报与决策闭环 <span class="tag">业务落地</span></div>',
    unsafe_allow_html=True
)
st.markdown(
    '<div class="apple-section-sub">从情报源到组织决策的完整链路覆盖 —— 体现平台的商业闭环能力</div>',
    unsafe_allow_html=True
)

C = D["ci"]
d1, d2, d3, d4 = st.columns(4)
with d1:
    # ★ 修复：主数值 = 有情报覆盖的企业，副标题提示其中已列入决策名单的数量
    st.markdown(f"""
    <div class="apple-card accent-purple">
        <div class="label">CR 监控企业</div>
        <div class="value">{C['monitored_orgs']}</div>
        <div class="sub">有情报覆盖 · 已决策 <b>{C['decision_monitored_orgs']}</b></div>
    </div>""", unsafe_allow_html=True)
with d2:
    st.markdown(f"""
    <div class="apple-card accent-orange">
        <div class="label">情报事件</div>
        <div class="value">{C['events']}</div>
        <div class="sub">高影响 <b>{C['high_impact']}</b> · 近 30 天 <b>{D['ops']['events_30d']}</b></div>
    </div>""", unsafe_allow_html=True)
with d3:
    approved_ratio = round(C['briefs_approved'] / C['briefs'] * 100, 0) if C['briefs'] else 0
    st.markdown(f"""
    <div class="apple-card accent-green">
        <div class="label">情报简报</div>
        <div class="value">{C['briefs']}</div>
        <div class="sub">已审核 <b>{C['briefs_approved']}</b> · {int(approved_ratio)}%</div>
    </div>""", unsafe_allow_html=True)
with d4:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">决策记录</div>
        <div class="value">{C['decisions']}</div>
        <div class="sub">已闭环 {C['reviews_approved']} 个审核</div>
    </div>""", unsafe_allow_html=True)


# ---------- 监控企业 + 近期高影响情报 ----------
st.markdown('<div style="height: 8px;"></div>', unsafe_allow_html=True)

q1, q2 = st.columns(2)

with q1:
    st.markdown('<div class="apple-list-title">🎯 CR 监控企业</div>', unsafe_allow_html=True)
    if not C["monitored_list"]:
        st.markdown("""
        <div class="apple-list"><div class="apple-list-empty">
            暂无 CR 监控企业<br>
            <span style="font-size:0.8rem;">导入情报事件后自动出现</span>
        </div></div>""", unsafe_allow_html=True)
    else:
        rows_html = ""
        for org in C["monitored_list"]:
            country = org.get("country") or "—"
            rows_html += f"""
            <div class="apple-list-item">
                <div>
                    <div class="name">{org['name']}</div>
                    <div class="meta">{country} · {org.get('type') or 'biotech'}</div>
                </div>
                <div class="count pill badge-ok">{org['event_count']} 事件</div>
            </div>"""
        st.markdown(f'<div class="apple-list">{rows_html}</div>', unsafe_allow_html=True)

with q2:
    st.markdown('<div class="apple-list-title">⚡ 近期高影响情报</div>', unsafe_allow_html=True)
    if not C["recent_high"]:
        st.markdown("""
        <div class="apple-list"><div class="apple-list-empty">
            暂无高影响事件
        </div></div>""", unsafe_allow_html=True)
    else:
        TYPE_COLORS = {
            "acquisition": "badge-alert",
            "merger": "badge-alert",
            "ipo": "badge-warn",
            "regulatory_approval": "badge-ok",
        }
        rows_html = ""
        for evt in C["recent_high"]:
            badge_cls = TYPE_COLORS.get(evt["type"], "badge-ok")
            date = evt.get("date") or "—"
            org_name = evt.get("org") or "未知组织"
            rows_html += f"""
            <div class="apple-list-item">
                <div>
                    <div class="name">{evt['title'][:64]}{'...' if len(evt['title']) > 64 else ''}</div>
                    <div class="meta">{org_name} · {date}</div>
                </div>
                <div class="count pill {badge_cls}">{evt['type'].replace('_', ' ')}</div>
            </div>"""
        st.markdown(f'<div class="apple-list">{rows_html}</div>', unsafe_allow_html=True)


# ============================================================
# Section D —— 运营健康
# ============================================================
st.markdown(
    '<div class="apple-section">运营健康 <span class="tag">日常工作</span></div>',
    unsafe_allow_html=True
)
st.markdown(
    '<div class="apple-section-sub">待处理队列、数据缺口与审计覆盖 —— 平台的数据治理与工作流状态</div>',
    unsafe_allow_html=True
)

O = D["ops"]
e1, e2, e3, e4 = st.columns(4)
with e1:
    total_pending = (O["pending_proposals"] + O["pending_packages"] + O["pending_qc"])
    st.markdown(f"""
    <div class="apple-card accent-orange">
        <div class="label">待处理队列</div>
        <div class="value">{total_pending}</div>
        <div class="sub">提案 {O['pending_proposals']} · 证据包 {O['pending_packages']} · QC {O['pending_qc']}</div>
    </div>""", unsafe_allow_html=True)
with e2:
    total_gap = O["missing_level"] + O["no_source"] + O["no_pathogen"]
    color_cls = "accent-red" if total_gap > 0 else "accent-green"
    st.markdown(f"""
    <div class="apple-card {color_cls}">
        <div class="label">数据缺口</div>
        <div class="value">{total_gap}</div>
        <div class="sub">缺 level {O['missing_level']} · 缺来源 {O['no_source']} · 缺病原 {O['no_pathogen']}</div>
    </div>""", unsafe_allow_html=True)
with e3:
    st.markdown(f"""
    <div class="apple-card accent-blue">
        <div class="label">审计事件</div>
        <div class="value">{O['audit_events']}</div>
        <div class="sub">AuditEvent 全量留痕</div>
    </div>""", unsafe_allow_html=True)
with e4:
    st.markdown(f"""
    <div class="apple-card accent-purple">
        <div class="label">工程化管线</div>
        <div class="value">{A['constructs']}</div>
        <div class="sub">关联 <b>{A['programs']}</b> 个项目</div>
    </div>""", unsafe_allow_html=True)


# ---------- Footer ----------
st.markdown(f"""
<div style="text-align:center; margin-top:4rem; color:#86868b; font-size:0.82rem;">
    共收录 <b>{A['orgs']}</b> 家组织 · <b>{C['events']}</b> 条情报事件 · <b>{C['briefs']}</b> 份情报简报
    <br><br>
    <span style="font-size:0.75rem;">Phage Intelligence Platform · MVP Demo</span>
</div>
""", unsafe_allow_html=True)