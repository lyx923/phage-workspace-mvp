# pages/ci.py
import streamlit as st
import pandas as pd
from config import get_driver
from src.shared.audit_service import write_audit_event

# CI 相关导入
from src.ci.organization_service import create_organization
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event
from src.shared.source_artifact_service import create_source_artifact
from src.ci.competitor_profile import build_competitor_profile, list_organizations
from src.ci.competitor_brief import generate_competitor_brief
from src.shared.review import create_review
from src.decision_support.decision_record import create_decision_record
from src.ci.use_event_service import record_intelligence_use
from src.engineering_intelligence.strategy_classifier import create_engineering_strategy
from src.engineering_intelligence.construct_service import create_engineered_construct, link_program_to_construct
from src.engineering_intelligence.claim_extractor import (
    create_technical_claim, create_technical_result)
from src.engineering_intelligence.technology_assessment import (
    create_technology_assessment)
from src.ci.competitor_assessment import create_competitor_assessment

@st.cache_resource
def get_db():
    return get_driver()

driver = get_db()

def ci_mode(driver):
    """CI竞争情报模式的所有界面"""
    # ---- 自定义 CSS 样式（提升视觉档次） ----
    st.markdown("""
    <style>
    .ci-main-title { font-size: 1.8rem; font-weight: 700; color: #0f172a; margin-bottom: 0.2rem; }
    .ci-subtitle { color: #64748b; margin-bottom: 1.5rem; }
    .ci-step-header {
        font-size: 1.2rem;
        font-weight: 600;
        color: #1e293b;
        display: flex;
        align-items: center;
        gap: 0.5rem;
        margin-bottom: 0.75rem;
    }
    .ci-step-number {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #0068c9;
        color: white;
        border-radius: 50%;
        width: 28px;
        height: 28px;
        font-size: 0.9rem;
        font-weight: 700;
        flex-shrink: 0;
    }
    .ci-badge {
        background: #eef2ff;
        color: #1e40af;
        border-radius: 20px;
        padding: 0.15rem 0.75rem;
        font-size: 0.75rem;
        font-weight: 500;
    }
    .ci-metric-box {
        background: #f8fafc;
        border-radius: 8px;
        padding: 0.8rem 1rem;
        text-align: center;
        border: 1px solid #e9edf2;
    }
    .ci-metric-box .number { font-size: 1.6rem; font-weight: 700; color: #0f172a; line-height: 1.2; }
    .ci-metric-box .label { font-size: 0.8rem; color: #64748b; margin-top: 0.15rem; }
    </style>
    """, unsafe_allow_html=True)

    # ---- 初始化会话状态 ----
    if "ci_step" not in st.session_state:
        st.session_state.ci_step = 0
    if "ci_context" not in st.session_state:
        st.session_state.ci_context = {
            "org_ids": {}, "program_ids": {}, "source_ids": {}, "event_ids": {},
            "strategy_ids": {}, "construct_ids": {}, "claim_ids": {}, "result_ids": {},
            "brief_ids": [], "decision_ids": [], "use_event_ids": [],
            "current_org_id": None, "current_program_id": None, "current_brief_id": None,
            "technology_assessment_id": None,
            "temp_events": [],
            "created_objects": {
                "organization": None,
                "program": None,
                "sources": [],
                "events": []
            }
        }
    if "ci_step_status" not in st.session_state:
        st.session_state.ci_step_status = {f"step{i+1}_done": False for i in range(6)}
    if "ci_step6_results" not in st.session_state:
        st.session_state["ci_step6_results"] = None

    # ---- 创建三个 Tab ----
    ci_tab0, ci_tab1, ci_tab2 = st.tabs(["📊 决策链图", "📋 情报流程", "🔍 情报查询"])

    # ========== Tab0: 决策链图（独立） ==========
    with ci_tab0:
        st.markdown("### 🧭 情报与决策 Ontology 链路")
        st.caption("下图展示了从情报源到组织决策的完整数据链路，包括市场情报与工程情报的融合。")
        mermaid_html = """
        <div class="mermaid">
        graph LR
            A[情报源<br>SourceArtifact] -->|HAS_SOURCE| B[情报事件<br>IntelligenceEvent]
            B -->|AFFECTS| C[开发项目<br>DevelopmentProgram]
            C -->|TARGETS_PATHOGEN| D[病原体<br>Pathogen]
            B -->|AFFECTS| E[组织<br>Organization]
            E -->|COVERS| F[简报<br>IntelligenceProduct]
            F -->|REVIEWS| G[审核<br>Review]
            G -->|BASED_ON| H[决策记录<br>DecisionRecord]
            H -->|CONSUMES| I[情报使用事件<br>IntelligenceUseEvent]

            C -.->|USES_CONSTRUCT| J[工程化构建体<br>EngineeredPhageConstruct]
            J -->|IMPLEMENTS| K[工程策略<br>EngineeringStrategy]
            J -.->|CLAIMS_ABOUT| L[技术主张<br>TechnicalClaim]
            J -.->|RESULT_FOR| M[技术结果<br>TechnicalResult]

            style A fill:#dbeafe,stroke:#2563eb
            style B fill:#fef3c7,stroke:#d97706
            style C fill:#e0e7ff,stroke:#4338ca
            style D fill:#fce7f3,stroke:#db2777
            style E fill:#d1fae5,stroke:#059669
            style F fill:#f3e8ff,stroke:#7c3aed
            style G fill:#fecaca,stroke:#dc2626
            style H fill:#c7d2fe,stroke:#4f46e5
            style I fill:#fef08a,stroke:#ca8a04
            style J fill:#d9f99d,stroke:#65a30d
            style K fill:#fde047,stroke:#ca8a04
            style L fill:#fca5a5,stroke:#dc2626
            style M fill:#93c5fd,stroke:#2563eb
        </div>
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
        <script>
            (function() {
                function initMermaid() {
                    if (typeof mermaid !== 'undefined') {
                        mermaid.initialize({ startOnLoad: true, theme: 'neutral' });
                        mermaid.run();
                    } else {
                        setTimeout(initMermaid, 300);
                    }
                }
                if (document.readyState === 'complete') {
                    initMermaid();
                } else {
                    window.addEventListener('load', initMermaid);
                }
            })();
        </script>
        """
        st.iframe(mermaid_html, height=330)
        st.caption("💡 实线表示主要链路，虚线表示可选关联（工程情报分支）。")

    # ========== Tab1: 情报流程（含步骤卡片） ==========
    with ci_tab1:
        # ---- 步骤指示器 ----
        step_names = ["创建组织/项目/事件", "工程策略与构建体", "技术主张与结果", "生成简报并审核", "情报消费", "归因验证"]
        step_status = [st.session_state.ci_step_status[f"step{i+1}_done"] for i in range(6)]

        cols = st.columns(len(step_names))
        for i, (name, done) in enumerate(zip(step_names, step_status)):
            with cols[i]:
                color = "#22c55e" if done else "#94a3b8"
                st.markdown(f"""
                <div style="text-align:center; padding:0.5rem; background: {'#dcfce7' if done else '#f1f5f9'}; border-radius:8px; border:1px solid {color};">
                    <div style="font-size:0.75rem; font-weight:600; color:{color};">步骤 {i+1}</div>
                    <div style="font-size:0.7rem; color:#475569;">{name}</div>
                    <div style="font-size:0.65rem; color:{color};">{'✅ 已完成' if done else '⏳ 待执行'}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("---")

        # ---- 当前步骤卡片 ----
        step = st.session_state.ci_step

        def go_to_step(n):
            st.session_state.ci_step = n
            st.rerun()

        # 步骤 1
        if step == 0:
            with st.container(border=True):
                st.markdown("#### 🏢 步骤 1：创建组织、项目与情报事件")

                if st.session_state.ci_step_status.get("step1_done", False):
                    st.success("✅ 步骤1已完成，已创建以下对象：")
                    obj = st.session_state.ci_context.get("created_objects", {})
                    st.write(f"**组织**: {obj.get('organization', 'N/A')}")
                    st.write(f"**项目**: {obj.get('program', 'N/A')}")
                    if obj.get('sources'):
                        st.write(f"**来源**: {', '.join(obj['sources'])}")
                    if obj.get('events'):
                        st.write("**已创建的情报事件**:")
                        for evt in obj['events']:
                            st.write(f"  - {evt}")
                    st.markdown("---")
                    st.markdown("#### ➕ 添加更多情报事件")
                    with st.form("ci_step1_append_form"):
                        evt_type = st.selectbox("事件类型", ["regulatory_update", "funding", "acquisition", "partnership", "clinical_trial_update", "patent_event", "pipeline_update"])
                        evt_title = st.text_input("事件标题", value="New event")
                        evt_summary = st.text_area("事件摘要", value="详细描述...")
                        evt_date = st.date_input("事件日期", value=pd.to_datetime("2026-01-01"))
                        submitted_append = st.form_submit_button("➕ 添加此事件", width="stretch")
                    if submitted_append:
                        try:
                            with st.spinner("正在添加事件..."):
                                org_id = st.session_state.ci_context.get("current_org_id")
                                prog_id = st.session_state.ci_context.get("current_program_id")
                                if not org_id or not prog_id:
                                    st.error("缺少组织或项目ID，请重新执行步骤1")
                                else:
                                    src = create_source_artifact(
                                        driver,
                                        source_type="user_input",
                                        title=f"手动添加: {evt_title}",
                                        url="",
                                        published_date=evt_date.strftime("%Y-%m-%d"),
                                        credibility_tier="secondary",
                                        actor_id="test_user"
                                    )
                                    evt_id = capture_intelligence_event(
                                        driver,
                                        event_type=evt_type,
                                        title=evt_title,
                                        factual_summary=evt_summary,
                                        organization_id=org_id,
                                        program_id=prog_id,
                                        event_date=evt_date.strftime("%Y-%m-%d"),
                                        published_at=evt_date.strftime("%Y-%m-%d"),
                                        source_ids=[src],
                                        actor_id="test_user"
                                    )
                                    st.session_state.ci_context["created_objects"]["events"].append(f"{evt_id} ({evt_type})")
                                    st.success(f"✅ 事件 {evt_id} 已添加")
                                    st.rerun()
                        except Exception as e:
                            st.error(f"添加事件失败: {e}")
                    if st.button("➡️ 进入步骤 2（工程策略）", key="step1_continue"):
                        st.session_state.ci_step = 1
                        st.rerun()
                else:
                    # ===== 组织与项目选择区（放在 form 外，支持联动） =====
                    existing = list_organizations(driver)
                    org_options = [""] + [f"{o['name']} ({o['id']})" for o in existing]
                    quick_org = st.selectbox(
                        "选择已有组织或（留空则新建）",
                        options=org_options,
                        key="ci_step1_quick_org"
                    )

                    # 解析已选组织 ID
                    selected_org_id = None
                    if quick_org and quick_org.strip():
                        parts = quick_org.split("(")
                        if len(parts) > 1:
                            selected_org_id = parts[1].rstrip(")")

                    # 根据已选组织动态加载该组织下的项目
                    # ✅ 修复：改用 DEVELOPS 关系（与 program_service.create_development_program 一致）
                    prog_options_existing = []
                    if selected_org_id:
                        with driver.session() as session:
                            progs = session.run("""
                                MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram)
                                RETURN d.program_id AS id, d.canonical_name AS name
                                ORDER BY d.canonical_name
                            """, oid=selected_org_id)
                            prog_options_existing = [f"{r['name']} ({r['id']})" for r in progs]

                    quick_prog_options = [""] + prog_options_existing
                    quick_prog = st.selectbox(
                        "选择已有项目或（留空则新建）",
                        options=quick_prog_options,
                        key="ci_step1_quick_prog"
                    )

                    st.caption("💡 选择已有组织后，下方会自动列出该组织的项目供选择；若都不选，则按下方名称新建。")

                    # ===== 其他字段仍在 form 内 =====
                    with st.form("ci_step1_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            org_name = st.text_input("组织名称（新建时填写）", value="Proteon Pharmaceuticals")
                            org_type = st.selectbox("组织类型", ["biotech", "pharma", "academic", "CRO", "tech"])
                        with col2:
                            prog_name = st.text_input("项目名称（新建时填写）", value="BAFASAL")
                            prog_stage = st.selectbox("研发阶段", ["discovery", "preclinical", "phase_1", "phase_2", "phase_3", "commercial"])

                        st.markdown("---")
                        st.markdown("#### 📝 添加情报事件（可选，可多次添加）")
                        evt_type = st.selectbox("事件类型", ["regulatory_update", "funding", "acquisition", "partnership", "clinical_trial_update", "patent_event", "pipeline_update"], key="evt_type")
                        evt_title = st.text_input("事件标题", value="New event", key="evt_title")
                        evt_summary = st.text_area("事件摘要", value="详细描述...", key="evt_summary")
                        evt_date = st.date_input("事件日期", value=pd.to_datetime("2026-01-01"), key="evt_date")
                        add_clicked = st.form_submit_button("➕ 添加事件到列表", width="content")

                    if add_clicked:
                        temp_event = {
                            "type": evt_type,
                            "title": evt_title,
                            "summary": evt_summary,
                            "date": evt_date.strftime("%Y-%m-%d")
                        }
                        st.session_state.ci_context["temp_events"].append(temp_event)
                        st.success(f"已添加事件: {evt_title}")
                        st.rerun()

                    if st.session_state.ci_context.get("temp_events"):
                        st.write("**已暂存的事件（待提交）:**")
                        for i, evt in enumerate(st.session_state.ci_context["temp_events"]):
                            st.write(f"  {i+1}. [{evt['type']}] {evt['title']} ({evt['date']})")

                    st.caption("💡 情报事件为可选，您可以直接提交而不添加任何事件。")

                    if st.button("🚀 提交并完成步骤1", width="stretch", type="primary"):
                        try:
                            with st.spinner("正在创建组织、项目及事件..."):
                                # ---- 1. 处理组织 ----
                                if quick_org and quick_org.strip():
                                    parts = quick_org.split("(")
                                    org_id = parts[1].rstrip(")") if len(parts) > 1 else None
                                else:
                                    org_id = None

                                if not org_id:
                                    with driver.session() as session:
                                        existing_org = session.run(
                                            "MATCH (o:Organization {canonical_name: $name}) RETURN o.organization_id AS id",
                                            name=org_name
                                        ).single()
                                        if existing_org:
                                            org_id = existing_org["id"]
                                            st.warning(f"组织 '{org_name}' 已存在，将复用该组织 (ID: {org_id})")
                                        else:
                                            org_id = create_organization(
                                                driver,
                                                canonical_name=org_name,
                                                organization_type=org_type,
                                                aliases=[org_name[:8]],
                                                headquarters_country="Poland",
                                                website=f"https://www.{org_name.lower().replace(' ','')}.com",
                                                description=f"{org_name} 是一家专注于噬菌体技术的生物技术公司。",
                                                actor_id="test_user"
                                            )
                                            st.session_state.ci_context["org_ids"][org_name] = org_id

                                st.session_state.ci_context["current_org_id"] = org_id
                                with driver.session() as session:
                                    org_display = session.run(
                                        "MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS name",
                                        oid=org_id
                                    ).single()["name"]

                                # ---- 2. 处理项目 ----
                                prog_id = None
                                prog_display_name = None

                                # 2a. 优先使用"已选项目"
                                if quick_prog and quick_prog.strip():
                                    parts = quick_prog.split("(")
                                    if len(parts) > 1:
                                        prog_id = parts[1].rstrip(")")
                                        prog_display_name = parts[0].strip()

                                # 2b. 否则按名称复用/新建
                                # ✅ 修复：改用 DEVELOPS 关系检查项目是否已存在
                                if not prog_id:
                                    with driver.session() as session:
                                        existing_prog = session.run(
                                            """
                                            MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(d:DevelopmentProgram {canonical_name: $pname})
                                            RETURN d.program_id AS id
                                            """,
                                            pname=prog_name, oid=org_id
                                        ).single()
                                        if existing_prog:
                                            prog_id = existing_prog["id"]
                                            prog_display_name = prog_name
                                            st.warning(f"项目 '{prog_name}' 已存在，将复用该项目 (ID: {prog_id})")
                                        else:
                                            prog_id = create_development_program(
                                                driver,
                                                organization_id=org_id,
                                                canonical_name=prog_name,
                                                program_type="therapeutic",
                                                development_stage=prog_stage,
                                                modality="cocktail",
                                                target_pathogen_species=["Salmonella enterica"],
                                                actor_id="test_user"
                                            )
                                            prog_display_name = prog_name

                                st.session_state.ci_context["program_ids"][prog_display_name] = prog_id
                                st.session_state.ci_context["current_program_id"] = prog_id

                                # ---- 3. 处理情报事件（如果有） ----
                                created_events = []
                                created_sources = []
                                for evt in st.session_state.ci_context["temp_events"]:
                                    src = create_source_artifact(
                                        driver,
                                        source_type="user_input",
                                        title=f"手动添加: {evt['title']}",
                                        url="",
                                        published_date=evt['date'],
                                        credibility_tier="secondary",
                                        actor_id="test_user"
                                    )
                                    created_sources.append(src)
                                    evt_id = capture_intelligence_event(
                                        driver,
                                        event_type=evt['type'],
                                        title=evt['title'],
                                        factual_summary=evt['summary'],
                                        organization_id=org_id,
                                        program_id=prog_id,
                                        event_date=evt['date'],
                                        published_at=evt['date'],
                                        source_ids=[src],
                                        actor_id="test_user"
                                    )
                                    created_events.append(f"{evt_id} ({evt['type']})")

                                # ---- 4. 保存上下文 ----
                                st.session_state.ci_context["created_objects"] = {
                                    "organization": f"{org_display} (ID: {org_id})",
                                    "program": f"{prog_display_name} (ID: {prog_id})",
                                    "sources": created_sources,
                                    "events": created_events
                                }
                                st.session_state.ci_context["temp_events"] = []
                                st.session_state.ci_step_status["step1_done"] = True
                                st.success(f"✅ 步骤1完成！已创建 {len(created_events)} 个事件。")

                                st.session_state.ci_step = 1
                                st.rerun()

                        except Exception as e:
                            st.error(f"❌ 执行失败：{e}")

        # 步骤 2
        elif step == 1:
            with st.container(border=True):
                st.markdown("#### 🧬 步骤 2：创建工程策略与构建体")
                with st.form("ci_step2_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        strategy_type = st.selectbox("策略类型", ["host_range_expansion", "lysis_enhancement", "tail_fiber_engineering",
                                                                 "receptor_binding_engineering", "biofilm_disruption", "payload_delivery"])
                    with col2:
                        construct_name = st.text_input("构建体名称", value="vB_Kpn_HRE_001")
                    submitted = st.form_submit_button("🚀 执行步骤 2", width="stretch", type="primary")

                if submitted:
                    try:
                        with st.spinner("正在创建..."):
                            strategy_id = create_engineering_strategy(driver, strategy_type=strategy_type,
                                                                      description=f"{strategy_type} 策略描述",
                                                                      evidence_maturity="in_vitro", actor_id="test_user")
                            st.session_state.ci_context["strategy_ids"][strategy_type] = strategy_id
                            program_id = st.session_state.ci_context.get("current_program_id")
                            if not program_id:
                                st.error("未找到当前项目，请先执行步骤 1")
                                st.stop()
                            construct_id = create_engineered_construct(driver, public_name=construct_name,
                                                                      construct_code=construct_name.upper().replace("V","ENG"),
                                                                      parent_phage_name="PKP001", intended_effects=[f"{strategy_type} 效果"],
                                                                      target_pathogen_ids=["PATH-003"], strategy_ids=[strategy_id],
                                                                      construct_status="in_vitro_tested", first_public_date="2025-06-15",
                                                                      actor_id="test_user")
                            st.session_state.ci_context["construct_ids"][construct_name] = construct_id
                            link_program_to_construct(driver, program_id, construct_id, actor_id="test_user")
                            tech_assess_id = create_technology_assessment(
                                driver,
                                subject_type="construct",
                                subject_id=construct_id,
                                evidence_maturity="in_vitro",
                                technical_relevance="high",
                                translational_potential="medium",
                                manufacturability_risk="medium",
                                safety_uncertainty="low",
                                ip_relevance="medium",
                                internal_capability_gap="low",
                                assessment_summary="该构建体展示了宿主范围扩展潜力，但可制造性和转化风险尚需进一步验证。",
                                actor_id="test_user"
                            )
                            st.session_state.ci_context["technology_assessment_id"] = tech_assess_id
                            st.session_state.ci_step_status["step2_done"] = True
                            st.success("✅ 步骤 2 完成！已自动创建技术评估。")
                            go_to_step(2)
                    except Exception as e:
                        st.error(f"❌ 执行失败：{e}")

        # 步骤 3
        elif step == 2:
            with st.container(border=True):
                st.markdown("#### 📝 步骤 3：创建技术主张与结果")
                with st.form("ci_step3_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        claim_type = st.selectbox("主张类型", ["host_range", "efficacy", "safety", "manufacturability", "mechanism"])
                        claim_text = st.text_area("主张文本", value="", height=80)
                    with col2:
                        result_type = st.selectbox("结果类型", ["host_range", "lysis", "biofilm", "safety", "in_vivo", "computational"])
                        metric_value = st.number_input("结果值", value=0.85, step=0.05)
                    submitted = st.form_submit_button("🚀 执行步骤 3", width="stretch", type="primary")

                if submitted:
                    try:
                        with st.spinner("正在创建..."):
                            construct_id = list(st.session_state.ci_context["construct_ids"].values())[0] if st.session_state.ci_context["construct_ids"] else None
                            if not construct_id:
                                st.error("请先执行步骤 2 创建构建体")
                                st.stop()
                            claim_id = create_technical_claim(driver, claim_type=claim_type, claim_text=claim_text,
                                                              exact_quote=claim_text[:50], claimant_type="publication",
                                                              evidence_context="in_vitro", construct_id=construct_id,
                                                              actor_id="test_user")
                            st.session_state.ci_context["claim_ids"]["claim1"] = claim_id
                            result_id = create_technical_result(driver, result_type=result_type, study_context="in_vitro",
                                                               outcome_direction="positive", metric_name=result_type,
                                                               metric_value=float(metric_value), metric_unit="%",
                                                               comparator="亲本噬菌体", sample_size=12,
                                                               limitation_summary="需进一步验证", construct_id=construct_id,
                                                               actor_id="test_user")
                            st.session_state.ci_context["result_ids"]["result1"] = result_id
                            st.session_state.ci_step_status["step3_done"] = True
                            st.success("✅ 步骤 3 完成！")
                            go_to_step(3)
                    except Exception as e:
                        st.error(f"❌ 执行失败：{e}")

        # 步骤 4
        elif step == 3:
            with st.container(border=True):
                st.markdown("#### 📄 步骤 4：生成竞争简报并完成审核")

                if "brief_id" in st.session_state.ci_context and st.session_state.ci_context["brief_id"]:
                    st.info(f"当前简报 ID: {st.session_state.ci_context['brief_id']}，状态: {'已审核' if st.session_state.ci_step_status['step4_done'] else '待审核'}")
                else:
                    org_list = list_organizations(driver)
                    org_options = [f"{o['name']} ({o['id']})" for o in org_list]
                    if not org_options:
                        st.warning("⚠️ 暂无组织，请先执行步骤 1")
                    else:
                        current_org_id = st.session_state.ci_context.get("current_org_id")
                        default_index = 0
                        if current_org_id:
                            for idx, opt in enumerate(org_options):
                                if current_org_id in opt:
                                    default_index = idx
                                    break
                        selected_org = st.selectbox("选择要分析的组织", options=org_options, index=default_index)
                        parts = selected_org.split("(")
                        org_id = parts[1].rstrip(")") if len(parts)>1 else None
                        if org_id:
                            with st.expander("🧬 该组织的工程化噬菌体情报", expanded=True):
                                with driver.session() as session:
                                    engineering_data = session.run("""
                                        MATCH (o:Organization {organization_id: $oid})-[:DEVELOPS]->(p:DevelopmentProgram)
                                        OPTIONAL MATCH (c:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(p)
                                        OPTIONAL MATCH (p)-[:USES_CONSTRUCT]->(c2:EngineeredPhageConstruct)
                                        WITH p, COLLECT(DISTINCT c) + COLLECT(DISTINCT c2) AS constructs
                                        UNWIND (CASE WHEN size(constructs) = 0 THEN [null] ELSE constructs END) AS c
                                        OPTIONAL MATCH (c)-[:IMPLEMENTS]->(s:EngineeringStrategy)
                                        OPTIONAL MATCH (c)-[:CLAIMS_ABOUT]-(cl:TechnicalClaim)
                                        OPTIONAL MATCH (c)-[:RESULT_FOR]-(r:TechnicalResult)
                                        RETURN p.canonical_name AS program,
                                            collect(DISTINCT s.strategy_type) AS strategies,
                                            collect(DISTINCT c.public_name) AS constructs,
                                            collect(DISTINCT cl.claim_type) AS claims,
                                            collect(DISTINCT r.result_type) AS results
                                    """, oid=org_id)
                                    rows = list(engineering_data)
                                    if rows:
                                        for row in rows:
                                            st.write(f"**项目**: {row['program']}")
                                            st.write(f"  策略: {row['strategies'] if row['strategies'] else '无'}")
                                            st.write(f"  构建体: {row['constructs'] if row['constructs'] else '无'}")
                                            st.write(f"  技术主张: {row['claims'] if row['claims'] else '无'}")
                                            st.write(f"  实验结果: {row['results'] if row['results'] else '无'}")
                                    else:
                                        st.info("该组织暂无工程化噬菌体对象。")
                            with st.form("ci_step4_form"):
                                days_back = st.number_input("回溯天数", min_value=30, max_value=730, value=365)
                                submitted = st.form_submit_button("📄 生成简报", width="stretch", type="primary")
                            if submitted:
                                try:
                                    with st.spinner("生成简报中..."):
                                        brief = generate_competitor_brief(driver, org_id, days_back=days_back, persist=True)
                                        brief_id = brief.get("brief_id")
                                        if brief_id:
                                            st.session_state.ci_context["brief_id"] = brief_id
                                            st.session_state.ci_context["current_brief_id"] = brief_id
                                            st.session_state.ci_step_status["step4_done"] = False
                                            st.success(f"✅ 简报已生成，ID: {brief_id}")
                                            st.rerun()
                                except Exception as e:
                                    st.error(f"生成失败：{e}")

                if "brief_id" in st.session_state.ci_context and st.session_state.ci_context["brief_id"]:
                    brief_id = st.session_state.ci_context["brief_id"]
                    if not st.session_state.ci_step_status["step4_done"]:
                        with st.form("ci_step4_review_form"):
                            st.subheader("📌 创建评估（内部判断）")
                            col1, col2 = st.columns(2)
                            with col1:
                                assess_type = st.selectbox("竞争评估类型", ["threat", "opportunity", "capability", "uncertainty"])
                                impact_level = st.selectbox("影响程度", ["high", "medium", "low"])
                                confidence = st.selectbox("置信度", ["high", "medium", "low"])
                            with col2:
                                tech_relevance = st.selectbox("技术相关性", ["high", "medium", "low"])
                                evidence_maturity = st.selectbox("证据成熟度", ["conceptual", "in_vitro", "in_vivo", "clinical"])
                                translational_potential = st.selectbox("转化潜力", ["high", "medium", "low", "unknown"])
                            assessment_summary = st.text_area("评估摘要", value="该竞争对手在工程化噬菌体领域布局积极，但转化证据尚不充分。")
                            assumptions = st.text_input("假设条件（逗号分隔）", value="产品商业化顺利, 专利壁垒较低")
                            unknowns = st.text_input("未知项（逗号分隔）", value="市场接受度, 监管路径")
                            decision_choice = st.selectbox("审核决策", ["approved", "rejected"], index=0)
                            submitted_review = st.form_submit_button("✅ 提交审核（创建评估+决策）", width="stretch", type="primary")

                        if submitted_review:
                            try:
                                with st.spinner("审核中..."):
                                    org_id = st.session_state.ci_context.get("current_org_id")
                                    with driver.session() as session:
                                        result = session.run("MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS name", oid=org_id).single()
                                        org_name = result["name"] if result else "Unknown"
                                    assess_id = create_competitor_assessment(
                                        driver,
                                        assessment_type=assess_type,
                                        subject_type="organization",
                                        subject_id=org_id,
                                        impact_area="market",
                                        impact_level=impact_level,
                                        assessment_summary=assessment_summary,
                                        confidence=confidence,
                                        analyst_id="analyst_zhang",
                                        time_horizon="short",
                                        assumptions=assumptions.split(",") if assumptions else [],
                                        unknowns=unknowns.split(",") if unknowns else [],
                                        actor_id="system"
                                    )
                                    construct_id = list(st.session_state.ci_context.get("construct_ids", {}).values())[0] if st.session_state.ci_context.get("construct_ids") else None
                                    if construct_id:
                                        tech_assess_id = create_technology_assessment(
                                            driver,
                                            subject_type="construct",
                                            subject_id=construct_id,
                                            evidence_maturity=evidence_maturity,
                                            technical_relevance=tech_relevance,
                                            translational_potential=translational_potential,
                                            manufacturability_risk="medium",
                                            safety_uncertainty="low",
                                            ip_relevance="medium",
                                            internal_capability_gap="low",
                                            assessment_summary=f"技术评估: {assessment_summary[:50]}...",
                                            actor_id="system"
                                        )
                                    review_brief_id = create_review(
                                        driver,
                                        review_type="intelligence_product_review",
                                        target_object_type="IntelligenceProduct",
                                        target_object_id=brief_id,
                                        reviewer_id="expert_wang",
                                        decision=decision_choice,
                                        comment=f"简报审核 {decision_choice}",
                                        update_target_status=True,
                                        actor_id="system"
                                    )
                                    review_assess_id = create_review(
                                        driver,
                                        review_type="intelligence_product_review",
                                        target_object_type="CompetitorAssessment",
                                        target_object_id=assess_id,
                                        reviewer_id="expert_wang",
                                        decision=decision_choice,
                                        comment=f"评估审核 {decision_choice}",
                                        update_target_status=True,
                                        actor_id="system"
                                    )
                                    dec_id = create_decision_record(
                                        driver,
                                        brief_id=brief_id,
                                        decision_type="monitor",
                                        decision_summary=f"将 {org_name} 列入年度重点监控名单",
                                        rationale=f"审核决策: {decision_choice}",
                                        decision_owner="VP_Strategy",
                                        review_date="2027-01-01",
                                        actor_id="system"
                                    )
                                    st.session_state.ci_context["decision_ids"].append(dec_id)
                                    st.session_state.ci_step_status["step4_done"] = True
                                    st.success("✅ 审核完成！")
                                    go_to_step(4)
                            except Exception as e:
                                st.error(f"审核失败：{e}")
                    else:
                        st.success("🎉 本步骤已完成审核，可继续下一步。")
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            if st.button("➡️ 进入步骤 5（情报消费）", key="go_to_step5"):
                                go_to_step(4)
                        with col2:
                            if st.button("🔄 重新生成简报（重置）"):
                                st.session_state.ci_context.pop("brief_id", None)
                                st.session_state.ci_step_status["step4_done"] = False
                                st.session_state["ci_step6_results"] = None
                                st.rerun()

        # 步骤 5
        elif step == 4:
            with st.container(border=True):
                st.markdown("#### 📊 步骤 5：记录情报消费事件")
                with driver.session() as session:
                    briefs = session.run("""
                        MATCH (b:IntelligenceProduct)
                        RETURN b.brief_id AS brief_id, b.title AS title
                        ORDER BY b.created_at DESC LIMIT 10
                    """)
                    brief_options = [f"{r['title']} ({r['brief_id']})" for r in briefs]
                if not brief_options:
                    st.warning("⚠️ 暂无简报，请先执行步骤 4")
                else:
                    selected = st.selectbox("选择要消费的简报", options=brief_options)
                    brief_id = selected.split("(")[-1].rstrip(")")
                    with st.form("ci_step5_form"):
                        col1, col2 = st.columns(2)
                        with col1:
                            consumer_type = st.selectbox("消费方类型", ["IPD", "RD", "BD", "Strategy", "Clinical", "Management"])
                        with col2:
                            use_purpose = st.selectbox("使用目的", ["go_no_go_decision", "roadmap_planning", "competitor_monitoring",
                                                                  "portfolio_review", "due_diligence", "strategic_planning"])
                        submitted = st.form_submit_button("📌 记录消费", width="stretch", type="primary")

                    if submitted:
                        try:
                            with st.spinner("记录中..."):
                                dec_id = st.session_state.ci_context["decision_ids"][-1] if st.session_state.ci_context["decision_ids"] else None
                                use_id = record_intelligence_use(driver, product_id=brief_id, consumer_type=consumer_type,
                                                                consumer_id=f"{consumer_type.lower()}_team", use_purpose=use_purpose,
                                                                context_note=f"{consumer_type} 团队使用简报进行 {use_purpose}",
                                                                referenced_decision_id=dec_id, actor_id="test_user")
                                st.session_state.ci_context["use_event_ids"].append(use_id)
                                st.session_state.ci_step_status["step5_done"] = True
                                st.success(f"✅ 消费事件记录成功，ID: {use_id}")
                                go_to_step(5)
                        except Exception as e:
                            st.error(f"记录失败：{e}")

        # 步骤 6
        elif step == 5:
            with st.container(border=True):
                st.markdown("#### 🔗 步骤 6：验证归因链")

                if st.button("🔍 执行归因验证", width="stretch", type="primary"):
                    try:
                        with st.spinner("验证中..."):
                            query = """
                            MATCH (brief:IntelligenceProduct)-[:COVERS]->(org:Organization)
                            MATCH (review:Review)-[:REVIEWS]->(brief)
                            WHERE review.decision = 'approved'
                            MATCH (dec:DecisionRecord)-[:BASED_ON]->(brief)
                            MATCH (use:IntelligenceUseEvent)-[:CONSUMES]->(brief)

                            OPTIONAL MATCH (src:SourceArtifact)<-[:HAS_SOURCE]-(evt:IntelligenceEvent)-[:AFFECTS]->(prog:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen)
                            WHERE evt.organization_id = org.organization_id

                            OPTIONAL MATCH (prog)-[:USES_CONSTRUCT|ASSOCIATED_WITH]-(con:EngineeredPhageConstruct)
                            OPTIONAL MATCH (con)-[:IMPLEMENTS]->(strat:EngineeringStrategy)
                            OPTIONAL MATCH (con)<-[:CLAIMS_ABOUT]-(claim:TechnicalClaim)
                            OPTIONAL MATCH (con)<-[:RESULT_FOR]-(res:TechnicalResult)

                            WITH org,
                                COLLECT(DISTINCT brief) AS briefs,
                                COLLECT(DISTINCT review) AS reviews,
                                COLLECT(DISTINCT dec) AS decs,
                                COLLECT(DISTINCT use) AS uses,
                                COLLECT(DISTINCT src.title) AS evidence_sources,
                                COLLECT(DISTINCT src.credibility_tier) AS credibility_tiers,
                                COLLECT(DISTINCT evt.title) AS events,
                                COLLECT(DISTINCT p.species) AS pathogens,
                                COLLECT(DISTINCT strat.strategy_type) AS strategies,
                                COLLECT(DISTINCT con.public_name) AS constructs,
                                COLLECT(DISTINCT claim.claim_type) AS claim_types,
                                COLLECT(DISTINCT res.result_type) AS result_types

                            RETURN org.canonical_name AS competitor,
                                org.organization_id AS org_id,
                                [b IN briefs | b.brief_id] AS brief_ids,
                                [r IN reviews | r.decision] AS review_decisions,
                                [d IN decs | d.decision_type] AS decision_types,
                                [u IN uses | u.consumer_type] AS consumers,
                                [u IN uses | u.use_purpose] AS purposes,
                                evidence_sources,
                                credibility_tiers,
                                events,
                                pathogens,
                                strategies,
                                constructs,
                                claim_types,
                                result_types
                            """
                            with driver.session() as session:
                                results = list(session.run(query))

                            st.session_state["ci_step6_results"] = [dict(r) for r in results]
                            st.session_state.ci_step_status["step6_done"] = True
                        st.rerun()
                    except Exception as e:
                        st.error(f"验证失败：{e}")

                results = st.session_state.get("ci_step6_results")
                if results is not None:
                    if not results:
                        st.warning("未找到完整归因链路。请确保至少有一个组织已完成简报审核并记录消费。")
                    else:
                        st.success(f"✅ 找到 {len(results)} 个组织具备完整归因链路")

                        rows = []
                        for row in results:
                            rows.append({
                                "组织": row['competitor'],
                                "组织ID": row['org_id'],
                                "简报ID": ', '.join(row['brief_ids']) if row['brief_ids'] else '',
                                "审核决策": ', '.join(row['review_decisions']) if row['review_decisions'] else '',
                                "决策类型": ', '.join(row['decision_types']) if row['decision_types'] else '',
                                "消费方": ', '.join(row['consumers']) if row['consumers'] else '',
                                "用途": ', '.join(row['purposes']) if row['purposes'] else '',
                                "证据来源数": len(row['evidence_sources']) if row['evidence_sources'] else 0,
                                "事件数": len(row['events']) if row['events'] else 0,
                                "靶向病原": ', '.join(row['pathogens']) if row['pathogens'] else '',
                                "策略": ', '.join(row['strategies']) if row['strategies'] else '',
                                "构建体": ', '.join(row['constructs']) if row['constructs'] else '',
                                "主张": ', '.join(row['claim_types']) if row['claim_types'] else '',
                                "结果": ', '.join(row['result_types']) if row['result_types'] else '',
                            })
                        df = pd.DataFrame(rows)
                        st.dataframe(df, width="stretch", hide_index=True)

                        st.markdown("---")
                        st.markdown("#### 📌 查看单个组织完整详情")
                        org_names = [row['competitor'] for row in results]
                        selected_org = st.selectbox("选择组织", org_names, key="ci_step6_org_select")
                        if selected_org:
                            for row in results:
                                if row['competitor'] == selected_org:
                                    st.json({
                                        "组织": row['competitor'],
                                        "简报ID列表": row['brief_ids'],
                                        "审核决策列表": row['review_decisions'],
                                        "决策类型列表": row['decision_types'],
                                        "消费方列表": row['consumers'],
                                        "用途列表": row['purposes'],
                                        "证据来源": row['evidence_sources'],
                                        "可信度等级": row['credibility_tiers'],
                                        "情报事件": row['events'],
                                        "靶向病原": row['pathogens'],
                                        "工程策略": row['strategies'],
                                        "构建体": row['constructs'],
                                        "技术主张": row['claim_types'],
                                        "实验结果": row['result_types']
                                    }, expanded=True)
                                    break

        with st.expander("📊 当前上下文状态"):
            st.json({
                "current_org_id": st.session_state.ci_context.get("current_org_id"),
                "current_program_id": st.session_state.ci_context.get("current_program_id"),
                "current_brief_id": st.session_state.ci_context.get("current_brief_id"),
                "decision_count": len(st.session_state.ci_context.get("decision_ids", [])),
                "use_event_count": len(st.session_state.ci_context.get("use_event_ids", [])),
                "technology_assessment_id": st.session_state.ci_context.get("technology_assessment_id"),
            })

    # ========== Tab2: 情报查询 ==========
    with ci_tab2:
        st.markdown("### 🔍 智能语义检索")
        st.caption("输入名称、缩写或关联关键词，系统将自动匹配已有本体实体，未匹配时可触发全网情报检索")

        search_query = st.text_input(
            "搜索本体实体",
            placeholder="例如: APT, BiomX, BX211, Salmonella, Klebsiella...",
            key="ci_search_input",
            value=""
        )

        col_search_btn, _ = st.columns([1, 5])
        with col_search_btn:
            search_clicked = st.button("🔍 搜索", key="ci_search_btn", width="stretch")

        if search_query or (search_query and st.session_state.get("ci_search_input")):
            query = search_query.strip()
            if len(query) >= 2:
                with st.spinner("搜索本体中..."):
                    with driver.session() as session:
                        results = {
                            "Organization": [],
                            "DevelopmentProgram": [],
                            "IntelligenceEvent": [],
                            "Pathogen": []
                        }
                        org_result = session.run("""
                            MATCH (o:Organization)
                            WHERE o.canonical_name CONTAINS toLower($q)
                               OR ANY(alias IN o.aliases WHERE alias CONTAINS toLower($q))
                            RETURN o.organization_id AS id,
                                   o.canonical_name AS name,
                                   o.organization_type AS type,
                                   o.headquarters_country AS country
                            LIMIT 10
                        """, q=query)
                        results["Organization"] = [dict(r) for r in org_result]

                        prog_result = session.run("""
                            MATCH (d:DevelopmentProgram)
                            WHERE d.canonical_name CONTAINS toLower($q)
                               OR ANY(alias IN d.aliases WHERE alias CONTAINS toLower($q))
                            RETURN d.program_id AS id,
                                   d.canonical_name AS name,
                                   d.development_stage AS stage,
                                   d.program_type AS type
                            LIMIT 10
                        """, q=query)
                        results["DevelopmentProgram"] = [dict(r) for r in prog_result]

                        event_result = session.run("""
                            MATCH (e:IntelligenceEvent)
                            WHERE e.title CONTAINS toLower($q)
                               OR e.event_type CONTAINS toLower($q)
                            RETURN e.event_id AS id,
                                   e.title AS name,
                                   e.event_type AS type,
                                   e.event_date AS date
                            ORDER BY e.event_date DESC
                            LIMIT 10
                        """, q=query)
                        results["IntelligenceEvent"] = [dict(r) for r in event_result]

                        path_result = session.run("""
                            MATCH (p:Pathogen)
                            WHERE p.species CONTAINS toLower($q)
                               OR ANY(alias IN p.aliases WHERE alias CONTAINS toLower($q))
                            RETURN p.pathogen_id AS id,
                                   p.species AS name,
                                   p.pathogen_type AS type
                            LIMIT 10
                        """, q=query)
                        results["Pathogen"] = [dict(r) for r in path_result]

                    total_matches = sum(len(v) for v in results.values())
                    if total_matches > 0:
                        st.success(f"✅ 在 Ontology 中找到 {total_matches} 个匹配实体")
                        for label, items in results.items():
                            if items:
                                with st.expander(f"📌 {label} ({len(items)})", expanded=True):
                                    for item in items:
                                        if label == "Organization":
                                            st.write(f"**{item['name']}** ({item.get('type','')}) - {item.get('country','')}  `{item['id']}`")
                                        elif label == "DevelopmentProgram":
                                            st.write(f"**{item['name']}** ({item.get('stage','')}) - {item.get('type','')}  `{item['id']}`")
                                        elif label == "IntelligenceEvent":
                                            st.write(f"**{item['name']}** ({item.get('type','')}) - {item.get('date','')}  `{item['id']}`")
                                        elif label == "Pathogen":
                                            st.write(f"**{item['name']}** ({item.get('type','')})  `{item['id']}`")
                    else:
                        st.warning(f"⚠️ 未在 Ontology 中找到与「{query}」匹配的实体")
                        col_trigger1, _ = st.columns([1, 4])
                        with col_trigger1:
                            if st.button("🌐 触发全网情报检索", key="ci_trigger_retrieval"):
                                write_audit_event(
                                    driver,
                                    action_type="CREATE",
                                    object_type="IntelligenceRetrievalRequest",
                                    object_id=f"REQ-{query.upper().replace(' ', '_')}",
                                    actor_id="system",
                                    delta={"query": query, "source": "ci_search"},
                                    reason=f"用户搜索「{query}」未命中，触发全网情报检索"
                                )
                                st.success(f"🚀 情报检索任务已提交，正在全网搜索「{query}」...")
                                st.info("💡 检索完成后将自动创建新情报事件，请稍后刷新查看。")
            else:
                st.info("请输入至少 2 个字符开始搜索")

        st.markdown("---")

        st.markdown("#### 组织列表（按事件数排序）")
        try:
            orgs = list_organizations(driver)
            if not orgs:
                st.info("暂无组织数据，请先执行步骤1创建组织。")
            else:
                org_with_events = []
                for org in orgs:
                    org_id = org["id"]
                    with driver.session() as session:
                        event_count = session.run("""
                            MATCH (e:IntelligenceEvent {organization_id: $oid})
                            RETURN count(e) AS cnt
                        """, oid=org_id).single()["cnt"]
                    org_with_events.append({**org, "event_count": event_count})
                org_sorted = sorted(org_with_events, key=lambda x: x["event_count"], reverse=True)[:10]

                cols = st.columns(2)
                for idx, org in enumerate(org_sorted):
                    with cols[idx % 2]:
                        org_id = org["id"]
                        name = org["name"]
                        org_type = org["type"]
                        country = org.get("country", "未知")
                        profile = build_competitor_profile(driver, org_id)
                        if "error" in profile:
                            detail = "无法加载详情"
                        else:
                            progs = profile.get('active_programs', [])
                            detail = f"项目数: {len(progs)} | 事件数: {len(profile.get('recent_events', []))} | 数据截止: {profile.get('as_of_date', 'N/A')}"
                        st.markdown(f"""
                        <div style="background:white; border-radius:10px; padding:1rem 1.2rem; border:1px solid #e9edf2; margin-bottom:0.8rem; box-shadow:0 1px 4px rgba(0,0,0,0.02);">
                            <div style="display:flex; justify-content:space-between; align-items:center;">
                                <span style="font-weight:600; font-size:1.05rem;">{name}</span>
                                <span style="background:#eef2ff; padding:0.1rem 0.6rem; border-radius:12px; font-size:0.7rem; color:#1e40af;">{org_type}</span>
                            </div>
                            <div style="font-size:0.85rem; color:#64748b; margin-top:0.2rem;">{country}</div>
                            <div style="font-size:0.8rem; margin-top:0.4rem;">{detail}</div>
                        </div>
                        """, unsafe_allow_html=True)
        except Exception as e:
            st.error(f"加载组织列表失败: {e}")

        st.markdown("---")

        st.markdown("#### 最新情报事件")
        try:
            with driver.session() as session:
                events = session.run("""
                    MATCH (e:IntelligenceEvent)
                    RETURN e.event_id AS 事件ID,
                           e.title AS 标题,
                           e.event_type AS 类型,
                           e.event_date AS 日期,
                           e.review_status AS 审核状态
                    ORDER BY e.event_date DESC
                    LIMIT 10
                """)
                event_records = [dict(r) for r in events]
                if event_records:
                    df_events = pd.DataFrame(event_records)
                    st.dataframe(df_events, width="stretch", hide_index=True)
                else:
                    st.info("暂无事件记录。")
        except Exception as e:
            st.error(f"加载事件失败: {e}")

        st.markdown("#### 最新情报简报")
        try:
            with driver.session() as session:
                briefs = session.run("""
                    MATCH (b:IntelligenceProduct)
                    RETURN b.brief_id AS 简报ID,
                           b.title AS 标题,
                           b.brief_type AS 类型,
                           b.as_of_date AS 截止日期,
                           b.review_status AS 审核状态
                    ORDER BY b.created_at DESC
                    LIMIT 10
                """)
                brief_records = [dict(r) for r in briefs]
                if brief_records:
                    df_briefs = pd.DataFrame(brief_records)
                    st.dataframe(df_briefs, width="stretch", hide_index=True)
                else:
                    st.info("暂无简报记录。")
        except Exception as e:
            st.error(f"加载简报失败: {e}")

ci_mode(driver)