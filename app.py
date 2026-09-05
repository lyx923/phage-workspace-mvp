# app.py
import streamlit as st
import pandas as pd
import random
import json
import numpy as np
import os
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from config import get_driver
from src.scientific.validator_service import (
    query_phages_for_host,
    batch_validate_hosts,
    query_l3_evidence,
    query_hosts_for_phage,
    validate_without_sequencing,
)
from src.scientific.evidence_package_service import (
    build_evidence_package_from_db,
    rule_based_evidence_package,
    verify_llm_effectiveness
)
from src.scientific.retriever_service import (
    analyze_cross_case_reuse_simple,
    find_matching_phages,
    find_similar_cases,
    analyze_and_persist_reuse,
    confirm_knowledge_reuse
)
from src.scientific.evidence_upgrade_service import (
    curate_case_by_id,
    review_evidence_upgrade_proposal,
    review_scientific_evidence_package,
    review_assay_qc
)
from src.scientific.import_service import (
    load_phages_from_lysis_csv_simple,
    import_golden_rules,
    clear_database,
    load_cases_from_csv,
    load_phages_from_csv,
    load_patients_from_csv,
    load_organizations_from_csv,
    load_programs_from_csv,
    load_events_from_csv
)
from src.foundation.schema import create_schema, create_ontology_modules, create_controlled_vocabularies
from shared.audit_service import write_audit_event  # 修改点1：替换 log_action

# ---------- CI 相关导入 ----------
from src.ci.organization_service import create_organization, detect_material_changes, get_organizations_with_recent_changes
from src.ci.program_service import create_development_program
from src.ci.event_service import capture_intelligence_event
from src.shared.source_artifact_service import create_source_artifact
from src.ci.competitor_profile import build_competitor_profile, list_organizations
from src.ci.competitor_brief import generate_competitor_brief
from src.shared.review import create_review, get_latest_review
from src.decision_support.decision_record import create_decision_record, get_decision_record
from src.ci.use_event_service import record_intelligence_use
from src.ci.intelligence_product_service import update_intelligence_product_review_status
from src.engineering_intelligence.strategy_classifier import create_engineering_strategy, get_all_strategies
from src.engineering_intelligence.construct_service import create_engineered_construct, get_constructs_by_strategy
from src.engineering_intelligence.claim_extractor import (
    create_technical_claim,
    create_technical_result,
    get_claims_by_construct,
    get_results_by_construct,
    detect_claim_evidence_gaps
)
from src.engineering_intelligence.technology_assessment import (
    create_technology_assessment,
    get_assessment_for_subject,
    get_assessments_by_strategy,
    suggest_assessment_from_evidence
)
from src.ci.competitor_assessment import create_competitor_assessment, get_assessment

# ---------- 获取项目根目录 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体智能平台", layout="wide")

# ---------- 缓存数据库连接 ----------
@st.cache_resource
def get_db():
    return get_driver()

try:
    driver = get_db()
    with driver.session() as session:
        session.run("RETURN 1")
except Exception as e:
    st.error(f"⚠️ 无法连接 Neo4j 数据库，请检查 config.py 配置。错误: {str(e)}")
    st.stop()

# ---------- 侧边栏 ----------
with st.sidebar:
    # ---- 自定义侧边栏标题 ----
    st.markdown(
        """
        <div style="
            font-size: 1.8rem;
            font-weight: 700;
            color: #0068c9;
            padding: 0.5rem 0 0.2rem 0;
            letter-spacing: -0.5px;
            border-bottom: 2px solid #e6e9ef;
            margin-bottom: 0.8rem;
        ">
             噬菌体智能平台
        </div>
        """,
        unsafe_allow_html=True
    )

    # ---- 美化纵向单选按钮（模式切换） ----
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > label {
        display: none !important;
    }
    div[data-testid="stRadio"] > div {
        flex-direction: column !important;
        gap: 0.5rem !important;
    }
    div[data-testid="stRadio"] > div > label {
        display: flex !important;
        align-items: center;
        justify-content: center;
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        border-radius: 0.75rem;
        padding: 0.7rem 0.5rem;
        margin: 0 !important;
        cursor: pointer;
        transition: all 0.2s ease;
        font-weight: 500;
        font-size: 1.05rem;
        width: 100%;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    div[data-testid="stRadio"] > div > label > div:first-child {
        display: none !important;
    }
    div[data-testid="stRadio"] > div > label[data-baseweb="radio"] {
        background-color: #f8f9fa;
        border-color: #dee2e6;
        color: #495057;
    }
    div[data-testid="stRadio"] > div > label[data-baseweb="radio"][aria-checked="true"] {
        background-color: #0068c9 !important;
        border-color: #0068c9 !important;
        color: white !important;
        box-shadow: 0 4px 8px rgba(0,104,201,0.25);
    }
    div[data-testid="stRadio"] > div > label:hover:not([aria-checked="true"]) {
        background-color: #e9ecef;
        border-color: #adb5bd;
        transform: translateY(-1px);
    }
    </style>
    """, unsafe_allow_html=True)

    mode = st.radio(
        label="",
        options=["噬菌体配型", "CI竞争情报"],
        index=0,
        key="app_mode"
    )

    st.markdown("---")

    if mode == "噬菌体配型":
        st.header("📊 数据总览")
        try:
            with driver.session() as session:
                stats = session.run("""
                    MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
                    WHERE ANY(ref IN a.evidence_ref WHERE ref CONTAINS '合作方裂解谱数据')
                    RETURN count(DISTINCT ph) AS phage_count,
                           count(DISTINCT h.strain_label) AS host_count,
                           count(a) AS interaction_count
                """).single()
                col1, col2, col3 = st.columns(3)
                col1.metric("噬菌体", stats["phage_count"])
                col2.metric("菌株", stats["host_count"])
                col3.metric("互作关系", stats["interaction_count"])
        except Exception as e:
            st.error(f"⚠️ 数据总览加载失败: {str(e)}")

        if st.button("🔄 清空并重新导入全部数据", type="secondary"):
            with st.status("执行数据导入...", expanded=True) as status:
                status.update(label="正在清空数据库...")
                clear_database()
                st.write("✅ 数据库已清空")

                status.update(label="创建约束、索引及 Foundation 对象...")
                create_schema(driver)
                create_ontology_modules(driver)
                create_controlled_vocabularies(driver)
                st.write("✅ 约束、索引、OntologyModule、ControlledVocabulary 已创建")

                status.update(label="导入患者主数据...")
                load_patients_from_csv(os.path.join(BASE_DIR, "data", "patients.csv"))
                st.write("✅ 患者主数据导入完成")

                status.update(label="导入噬菌体互作...")
                load_phages_from_csv(os.path.join(BASE_DIR, "data", "phage_interactions.csv"))
                st.write("✅ 噬菌体互作导入完成")

                status.update(label="导入临床病例...")
                load_cases_from_csv(os.path.join(BASE_DIR, "data", "cases.csv"))
                st.write("✅ 病例导入完成")

                status.update(label="导入裂解谱数据...")
                result = load_phages_from_lysis_csv_simple(os.path.join(BASE_DIR, "data", "肺克数据脱敏.csv"))
                st.write(f"✅ 裂解谱导入完成，新增 {result['positive_interactions']} 条记录")

                status.update(label="导入黄金配型知识库...")
                import_golden_rules()
                st.write("✅ 黄金配型知识库导入完成")

                status.update(label="导入组织...")
                load_organizations_from_csv(driver, os.path.join(BASE_DIR, "data", "ci_organizations.csv"))
                st.write("✅ 组织导入完成")

                status.update(label="导入项目...")
                load_programs_from_csv(driver, os.path.join(BASE_DIR, "data", "ci_programs.csv"))
                st.write("✅ 项目导入完成")

                status.update(label="导入事件...")
                load_events_from_csv(driver, os.path.join(BASE_DIR, "data", "ci_events.csv"))
                st.write("✅ 事件导入完成")

                status.update(label="全部完成！", state="complete")
            st.success("🎉 所有数据已重新导入！")
            st.rerun()

        st.markdown("---")
        st.subheader("📄 数据管理")
        with st.expander("📄 裂解谱最广的噬菌体"):
            with driver.session() as session:
                result = session.run("""
                    MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
                    WHERE ANY(ref IN a.evidence_ref WHERE ref CONTAINS '合作方裂解谱数据')
                    WITH ph.phage_id AS phage_id, count(a) AS host_count
                    RETURN phage_id, host_count
                    ORDER BY host_count DESC
                    LIMIT 5
                """)
                for record in result:
                    st.write(f"   - {record['phage_id']}: {record['host_count']} 个菌株")

        with st.expander("📄 数据完整性验证"):
            @st.cache_data(ttl=600)
            def get_v1_validation():
                with driver.session() as session:
                    result = session.run("""
                        MATCH (c:ClinicalCase)-[:INVOLVES_PATHOGEN]->(p:Pathogen)
                        RETURN count(c) AS total,
                               count(c.case_id) AS case_id_filled,
                               count(c.infection_type) AS infection_type_filled,
                               count(c.infection_site) AS infection_site_filled,
                               count(c.specimen_type) AS specimen_type_filled,
                               count(p.pathogen_id) AS pathogen_id_filled,
                               count(p.species) AS species_filled,
                               count(p.resistance_mechanism) AS resistance_filled,
                               count(p.verification_status) AS verification_filled
                    """)
                    stats = result.single()
                    total = stats['total']
                    if total > 0:
                        filled = {
                            "case_id": stats['case_id_filled'],
                            "infection_type": stats['infection_type_filled'],
                            "infection_site": stats['infection_site_filled'],
                            "specimen_type": stats['specimen_type_filled'],
                            "pathogen_id": stats['pathogen_id_filled'],
                            "species": stats['species_filled'],
                            "resistance_mechanism": stats['resistance_filled'],
                            "verification_status": stats['verification_filled']
                        }
                        total_fields = len(filled) * total
                        total_filled = sum(filled.values())
                        rate = (total_filled / total_fields) * 100
                        return {"total": total, "filled": filled, "rate": rate}
                    else:
                        return {"error": "数据库中无病例数据"}

            v1_data = get_v1_validation()
            if "error" in v1_data:
                st.warning(v1_data["error"])
            else:
                st.metric("必填字段填充率", f"{v1_data['rate']:.1f}%")
                for field, count in v1_data['filled'].items():
                    st.write(f"   - {field}: {count}/{v1_data['total']} ({count/v1_data['total']*100:.0f}%)")
                if v1_data['rate'] >= 90:
                    st.success("验证通过！填充率 ≥ 90%")
                else:
                    st.warning(f"⚠️ V1 验证未通过（{v1_data['rate']:.1f}% < 90%）")

        st.markdown("---")
        st.subheader("⚙️ 系统状态")
        try:
            from config import Config
            if Config.DS_API_KEY and Config.DS_API_KEY != "your_api_key_here":
                st.caption("✅ DeepSeek API 已配置")
            else:
                st.caption("⚠️ DeepSeek API 未配置，LLM 功能不可用")
        except:
            st.caption("⚠️ 无法读取配置")
    else:
        # CI 模式侧边栏
        st.header("📊 数据总览")
        try:
            with driver.session() as session:
                org_count = session.run("MATCH (o:Organization) RETURN count(o) AS cnt").single()['cnt']
                event_count = session.run("MATCH (e:IntelligenceEvent) RETURN count(e) AS cnt").single()['cnt']
                brief_count = session.run("MATCH (b:IntelligenceProduct) RETURN count(b) AS cnt").single()['cnt']
                c1, c2, c3 = st.columns(3)
                c1.metric("组织数", org_count)
                c2.metric("事件数", event_count)
                c3.metric("简报数", brief_count)
        except Exception as e:
            st.error(f"加载CI数据失败: {e}")

# ---------- 主界面 ----------
if mode == "噬菌体配型":
    # 原有的全部 tab 布局（保持不变）
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "🔍 噬菌体配型查询",
        "📊 批量菌株配型",
        "📦 证据包生成",
        "🔄 跨病例复用",
        "📈 聚类分析",
        "📝 知识策展",
        "📋 审计日志"
    ])

    with tab1:
        st.subheader("单个菌株配型查询")
        col1, col2 = st.columns([3, 1])
        with col1:
            host_input = st.text_input("输入菌株编号", value="B-KP136")
        with col2:
            limit = st.number_input("数量上限", min_value=1, max_value=100, value=20)

        if st.button("查询配型", type="primary"):
            with st.spinner("查询中..."):
                st.session_state.primary_result = query_phages_for_host(host_input, limit)

        if "primary_result" in st.session_state and st.session_state.primary_result:
            result = st.session_state.primary_result
            summary = validate_without_sequencing(host_input)
            st.success(summary["conclusion"])

            l5_count = sum(1 for p in result if p['evidence_level'] == 'L5')
            l4_count = sum(1 for p in result if p['evidence_level'] == 'L4')
            l3_count = sum(1 for p in result if p['evidence_level'] == 'L3')
            l2_count = sum(1 for p in result if p['evidence_level'] == 'L2')
            l1_count = sum(1 for p in result if p['evidence_level'] == 'L1')

            col_a, col_b, col_c, col_d, col_e = st.columns(5)
            col_a.metric("L1 文献", l1_count)
            col_b.metric("L2 体外", l2_count)
            col_c.metric("L3 临床", l3_count)
            col_d.metric("L4 多中心", l4_count)
            col_e.metric("L5 闭环", l5_count)
            df = pd.DataFrame(result)
            st.dataframe(df[["phage_name", "evidence_level", "evidence_ref"]],
                         use_container_width=True)
            st.caption("💡 证据等级说明：L1(文献) → L2(体外) → L3(单例临床) → L4(多中心) → L5(组织学习闭环)")
        else:
            if "primary_result" in st.session_state:
                st.warning("未找到匹配噬菌体")

        st.markdown("---")
        with st.expander("🔬 匹配噬菌体查询"):
            st.markdown("#### 匹配噬菌体查询")
            col_species, col_resistance = st.columns(2)
            with col_species:
                search_species = st.text_input("菌种 (species)", value="Escherichia coli", key="ret_species")
            with col_resistance:
                search_resistance = st.text_input("耐药机制 (resistance)", value="MDR", key="ret_resistance")
            search_phage_limit = st.number_input("返回数量", min_value=1, max_value=100, value=10, key="ret_phage_limit")
            if st.button("查询匹配噬菌体", key="ret_phage_btn"):
                with st.spinner("查询中..."):
                    st.session_state.ret_phage_result = find_matching_phages(driver, search_species, search_resistance, limit=search_phage_limit)
            if "ret_phage_result" in st.session_state and st.session_state.ret_phage_result is not None:
                phages_raw = st.session_state.ret_phage_result
                st.write(f"找到 {len(phages_raw)} 个匹配噬菌体：")
                for p in phages_raw[:5]:
                    st.write(f"   - {p['name']} (L{p['evidence_level']}) 概率: {p['infection_probability']}")
                if len(phages_raw) > 5:
                    st.write(f"   ... 还有 {len(phages_raw)-5} 个")

        with st.expander("🔬 相似病例查询"):
            st.markdown("#### 相似病例查询")
            col_sim_species, col_sim_type = st.columns(2)
            with col_sim_species:
                sim_species = st.text_input("菌种 (species)", value="Escherichia coli", key="sim_species")
            with col_sim_type:
                sim_infection_type = st.text_input("感染类型 (infection_type)", value="UTI", key="sim_infection_type")
            sim_limit = st.number_input("返回数量", min_value=1, max_value=100, value=5, key="sim_limit")
            if st.button("查询相似病例", key="sim_btn"):
                with st.spinner("查询中..."):
                    st.session_state.sim_result = find_similar_cases(driver, sim_species, sim_infection_type, limit=sim_limit)
            if "sim_result" in st.session_state and st.session_state.sim_result is not None:
                cases_raw = st.session_state.sim_result
                st.write(f"找到 {len(cases_raw)} 个相似病例：")
                for c in cases_raw:
                    st.write(f"   - {c['case_id']}: 结局 {c['clinical_outcome']}, 噬菌体: {c.get('phages_used', [])}")

        with st.expander("🔬 噬菌体宿主谱查询（反向查询）"):
            st.caption("输入噬菌体名称，查看它能裂解哪些宿主菌株")
            col_phage1, col_phage2 = st.columns([3, 1])
            with col_phage1:
                phage_input = st.text_input("输入噬菌体名称（如 PKP014 或 PHAGE-PKP014）", value="PKP014", key="phage_input_reverse")
            with col_phage2:
                phage_limit = st.number_input("返回数量", min_value=1, max_value=200, value=20, key="phage_limit_reverse")
            if st.button("🔍 查询噬菌体宿主谱", key="query_phage_hosts"):
                with st.spinner("查询中..."):
                    st.session_state.reverse_result = query_hosts_for_phage(phage_input, limit=phage_limit)
            if "reverse_result" in st.session_state and st.session_state.reverse_result:
                result = st.session_state.reverse_result
                if result:
                    df_hosts = pd.DataFrame(result)
                    st.success(f"✅ 噬菌体 **{phage_input}** 能裂解 {len(result)} 个宿主菌株")
                    st.dataframe(
                        df_hosts[["host_strain", "evidence_level"]],
                        column_config={
                            "host_strain": "宿主菌株",
                            "evidence_level": "证据等级"
                        },
                        use_container_width=True
                    )
                    level_counts = df_hosts['evidence_level'].value_counts().to_dict()
                    st.write("**📊 证据等级分布**")
                    cols = st.columns(len(level_counts))
                    for idx, (level, count) in enumerate(level_counts.items()):
                        cols[idx].metric(f"{level}", count)
                else:
                    st.warning(f"未找到噬菌体 **{phage_input}** 的宿主记录，请确认名称是否正确")

    with tab2:
        st.subheader("批量菌株配型覆盖度")
        if st.button("运行随机 10 个菌株"):
            strains = random.sample([f"B-KP{i}" for i in range(1, 244)], 10)
            with st.spinner("验证中..."):
                df = batch_validate_hosts(strains)
                st.session_state.batch_result = df
        if "batch_result" in st.session_state:
            st.dataframe(st.session_state.batch_result, use_container_width=True)
            st.metric("平均匹配数", f"{st.session_state.batch_result['总匹配'].mean():.1f}")

    with tab3:
        st.subheader("生成 Evidence Package")
        col1, col2 = st.columns(2)
        with col1:
            species = st.text_input("病原菌物种", value="Acinetobacter baumannii")
            resistance = st.text_input("耐药机制（留空表示不限）", value="")
        with col2:
            infection_type = st.text_input("感染类型", value="Pneumonia")
            use_llm = st.checkbox("使用 LLM (DeepSeek)", value=True)

        if st.button("生成证据包", type="primary"):
            with st.spinner("生成中..."):
                resistance_val = resistance.strip() if resistance.strip() else None
                if use_llm:
                    result = build_evidence_package_from_db(
                        species=species,
                        resistance=resistance_val,
                        infection_type=infection_type
                    )
                    st.session_state.ep_result = result
                else:
                    result = rule_based_evidence_package(
                        species=species,
                        resistance=resistance_val,
                        infection_type=infection_type
                    )
                    st.session_state.ep_result = result
        if "ep_result" in st.session_state:
            st.json(st.session_state.ep_result)

        st.markdown("---")
        st.markdown("#### 🎯 LLM 推荐效果验证")
        st.caption("对比 LLM 推荐结果 vs 真实临床方案，评估推荐覆盖率")
        verify_case_id_input = st.text_input("验证病例 ID", value="CASE-001", key="verify_llm_case")
        if st.button("验证 LLM 推荐效果", key="verify_llm_btn"):
            with st.spinner("验证中..."):
                try:
                    result = verify_llm_effectiveness(verify_case_id_input)
                    st.session_state.verify_result = result
                except Exception as e:
                    st.error(f"验证失败: {e}")
        if "verify_result" in st.session_state and st.session_state.verify_result:
            v_result = st.session_state.verify_result
            if "error" in v_result:
                st.warning(v_result["error"])
            else:
                verification = v_result.get("_verification", {})
                if verification:
                    coverage = verification.get("coverage", "none")
                    if coverage == "full":
                        st.success(f"✅ 覆盖率: **完整** — LLM 推荐完全覆盖实际情况")
                    elif coverage == "partial":
                        st.warning(f"⚠️ 覆盖率: **部分** — 匹配到 {verification.get('matched_phages', [])}")
                    else:
                        st.error(f"❌ 覆盖率: **无** — LLM 推荐未匹配到实际情况")
                    st.write(f"实际治疗: {verification.get('actual_treatment', 'N/A')}")
                    st.write(f"实际结局: {verification.get('actual_outcome', 'N/A')}")
                    if verification.get("rule_cited"):
                        st.success("✅ 黄金规则引用正确")
                st.subheader("📄 完整验证结果")
                st.json(v_result)

    with tab4:
        st.subheader("跨病例复用分析")
        col1, col2 = st.columns(2)
        with col1:
            case_a = st.text_input("病例 A ID", value="CASE-002")
        with col2:
            case_b = st.text_input("病例 B ID", value="CASE-003")

        try:
            with driver.session() as session:
                pkg_result = session.run("""
                    MATCH (p:ScientificEvidencePackage)
                    RETURN p.package_id AS package_id
                    ORDER BY p.created_at DESC
                    LIMIT 10
                """)
                available_packages = [r["package_id"] for r in pkg_result]
        except Exception:
            available_packages = []

        if available_packages:
            target_pkg = st.selectbox(
                "目标证据包 (TARGETS_PACKAGE)",
                available_packages,
                key="target_pkg_select"
            )
        else:
            st.warning("⚠️ 数据库中没有已生成的证据包，请先在【证据包生成】页生成一个用于关联。")
            target_pkg = None

        if st.button("分析并持久化复用", type="primary"):
            if not target_pkg:
                st.error("请先生成一个证据包再进行跨病例复用分析")
            else:
                with st.spinner("分析中..."):
                    result = analyze_and_persist_reuse(driver, case_a, case_b, target_package_id=target_pkg)
                    st.session_state.reuse_result = result
                    if result['persistence']['success']:
                        st.success(result['persistence']['message'])
                    else:
                        st.info(result['persistence']['message'])

        if "reuse_result" in st.session_state:
            st.json(st.session_state.reuse_result["analysis"])

        st.markdown("---")
        st.markdown("#### 🧾 审核待确认的复用事件")
        with driver.session() as session:
            pending_reuse = session.run("""
                MATCH (kre:KnowledgeReuseEvent)
                WHERE kre.status = 'detected'
                RETURN kre.reuse_event_id AS reuse_event_id,
                       kre.source_object_id AS source_case,
                       kre.target_package_id AS target_package,
                       kre.reuse_type AS reuse_type,
                       kre.retrieval_reason AS reason,
                       kre.created_at AS created_at
                ORDER BY kre.created_at
            """)
            pending_list = [dict(r) for r in pending_reuse]

        if not pending_list:
            st.info("✅ 当前没有待审核的复用事件")
        else:
            st.write(f"共 **{len(pending_list)}** 个复用事件待审核")
            for evt in pending_list:
                with st.container(border=True):
                    cols = st.columns([3, 1, 1])
                    with cols[0]:
                        st.write(f"**{evt['reuse_event_id']}**")
                        st.write(f"来源病例: `{evt['source_case']}` → 目标包: `{evt['target_package']}`")
                        st.write(f"复用类型: {evt['reuse_type']}")
                        st.caption(f"理由: {evt['reason'][:80]}..." if evt['reason'] and len(evt['reason']) > 80 else f"理由: {evt['reason']}")
                        st.caption(f"创建于: {evt['created_at']}")
                    with cols[1]:
                        if st.button("✅ 确认", key=f"confirm_reuse_{evt['reuse_event_id']}"):
                            try:
                                review_id = confirm_knowledge_reuse(
                                    driver, evt['reuse_event_id'], "expert_001", "confirmed", "人工确认复用有效"
                                )
                                st.success(f"已确认，Review ID: {review_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"确认失败: {e}")
                    with cols[2]:
                        if st.button("❌ 拒绝", key=f"reject_reuse_{evt['reuse_event_id']}"):
                            try:
                                review_id = confirm_knowledge_reuse(
                                    driver, evt['reuse_event_id'], "expert_001", "rejected", "人工拒绝复用"
                                )
                                st.success(f"已拒绝，Review ID: {review_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"拒绝失败: {e}")

    with tab5:
        st.subheader("基于裂解谱的伪型别聚类推荐")
        st.info("💡 聚类基于数据库中已有的裂解谱互作数据")

        n_clusters = st.slider("聚类数", min_value=2, max_value=15, value=8)

        if st.button("运行聚类"):
            with st.spinner("聚类中..."):
                with driver.session() as session:
                    result = session.run("""
                        MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
                        WHERE ANY(ref IN a.evidence_ref WHERE ref CONTAINS '合作方裂解谱数据')
                        RETURN ph.phage_id AS phage,
                               h.strain_label AS host,
                               1 AS value
                    """)
                    records = [dict(r) for r in result]

                if not records:
                    st.warning("⚠️ 数据库中无裂解谱数据，请先导入数据")
                    st.session_state.clusters = None
                else:
                    phages = sorted(set(r['phage'] for r in records))
                    hosts = sorted(set(r['host'] for r in records))

                    host_to_idx = {h: i for i, h in enumerate(hosts)}
                    phage_to_idx = {p: j for j, p in enumerate(phages)}

                    matrix = np.zeros((len(hosts), len(phages)), dtype=int)
                    for r in records:
                        if r['host'] in host_to_idx and r['phage'] in phage_to_idx:
                            matrix[host_to_idx[r['host']], phage_to_idx[r['phage']]] = 1

                    scaler = StandardScaler()
                    matrix_scaled = scaler.fit_transform(matrix)
                    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                    labels = kmeans.fit_predict(matrix_scaled)

                    clusters = {}
                    for host, label in zip(hosts, labels):
                        clusters.setdefault(label, []).append(host)

                    st.session_state.clusters = clusters
                    st.write(f"📊 共分为 **{len(clusters)}** 个簇")
                    for label, strains in sorted(clusters.items()):
                        st.write(f"**簇 {label+1}**：{len(strains)} 个菌株，示例 {strains[:5]}")

        if "clusters" in st.session_state and st.session_state.clusters:
            clusters = st.session_state.clusters

            st.markdown("---")
            st.subheader("推荐簇内广谱噬菌体")

            col1, col2 = st.columns(2)
            with col1:
                cluster_label = st.number_input(
                    "簇编号",
                    min_value=1,
                    max_value=len(clusters),
                    value=1,
                    key="cluster_select"
                )
            with col2:
                min_host_count_cluster = st.number_input(
                    "最小覆盖菌株数",
                    min_value=1,
                    max_value=20,
                    value=2,
                    key="cluster_min_host"
                )

            if st.button("推荐该簇的噬菌体", key="recommend_cluster_phages"):
                target_label = cluster_label - 1
                if target_label in clusters:
                    strains_in_cluster = clusters[target_label]
                    st.write(f"🔍 簇 {cluster_label} 包含 {len(strains_in_cluster)} 个菌株")

                    with driver.session() as session:
                        result = session.run("""
                            MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
                            WHERE ANY(ref IN a.evidence_ref WHERE ref CONTAINS '合作方裂解谱数据')
                            WITH ph, a, h, $strains AS strains
                            WITH ph, a, h, REDUCE(s = 0, strain IN strains |
                                     s + CASE WHEN h.strain_label CONTAINS strain THEN 1 ELSE 0 END
                                 ) AS host_count
                            WHERE host_count >= $min_host_count
                            RETURN ph.name AS phage_name,
                                   ph.phage_id AS phage_id,
                                   a.evidence_level AS evidence_level,
                                   host_count
                            ORDER BY host_count DESC
                            LIMIT 10
                        """, strains=strains_in_cluster, min_host_count=min_host_count_cluster)
                        phages = [dict(r) for r in result]

                    if phages:
                        df = pd.DataFrame(phages)
                        st.dataframe(
                            df[["phage_name", "host_count", "evidence_level"]],
                            column_config={
                                "phage_name": st.column_config.TextColumn("噬菌体名称", width="large"),
                                "host_count": st.column_config.NumberColumn("覆盖菌株数", width="small"),
                                "evidence_level": st.column_config.TextColumn("证据等级", width="small"),
                            },
                            use_container_width=True
                        )
                    else:
                        st.warning(f"该簇中无噬菌体同时覆盖 {min_host_count_cluster} 个以上菌株，请尝试降低阈值。")
                else:
                    st.error("无效的簇编号，请重新运行聚类。")

            st.markdown("---")
            st.subheader("🔍 单个菌株型别级推荐")
            st.caption("输入菌株编号，系统自动定位所属簇，推荐该簇内覆盖多菌株的噬菌体")

            col1, col2 = st.columns([3, 1])
            with col1:
                strain_input = st.text_input("输入菌株编号", value="B-KP11", key="strain_input_individual")
            with col2:
                min_host_count_individual = st.number_input(
                    "最小覆盖菌株数",
                    min_value=2,
                    max_value=20,
                    value=2,
                    key="individual_min_host"
                )

            if st.button("🔍 针对该菌株进行型别级推荐", type="primary", key="individual_recommend"):
                with st.spinner("分析中..."):
                    if "clusters" in st.session_state and st.session_state.clusters:
                        clusters = st.session_state.clusters
                        strain_to_cluster = {}
                        for label, strains in clusters.items():
                            for s in strains:
                                strain_to_cluster[s] = label

                        if strain_input not in strain_to_cluster:
                            st.warning(f"⚠️ 未找到菌株 {strain_input}，请检查编号是否正确")
                        else:
                            target_label = strain_to_cluster[strain_input]
                            strains_in_cluster = clusters[target_label]

                            st.success(f"✅ 菌株 **{strain_input}** 属于簇 {target_label+1}（共 {len(strains_in_cluster)} 个菌株）")
                            st.write(f"同簇菌株示例：{strains_in_cluster[:10]}{'...' if len(strains_in_cluster) > 10 else ''}")

                            with driver.session() as session:
                                result = session.run("""
                                    MATCH (ph:Phage)-[:USED_IN]->(a:LysisAssay)-[:TESTED_AGAINST]->(h:HostStrain)
                                    WHERE ANY(ref IN a.evidence_ref WHERE ref CONTAINS '合作方裂解谱数据')
                                    WITH ph, a, h, $strains AS strains
                                    WITH ph, a, h, REDUCE(s = 0, strain IN strains |
                                             s + CASE WHEN h.strain_label CONTAINS strain THEN 1 ELSE 0 END
                                         ) AS host_count
                                    WHERE host_count >= $min_host_count
                                    RETURN ph.name AS phage_name,
                                           ph.phage_id AS phage_id,
                                           a.evidence_level AS evidence_level,
                                           host_count
                                    ORDER BY host_count DESC
                                    LIMIT 10
                                """, strains=strains_in_cluster, min_host_count=min_host_count_individual)
                                recommended_phages = [dict(r) for r in result]

                            if recommended_phages:
                                st.subheader("💊 推荐噬菌体（该簇内至少覆盖 2 个菌株）")
                                df_rec = pd.DataFrame(recommended_phages)
                                st.dataframe(
                                    df_rec[["phage_name", "host_count", "evidence_level"]],
                                    column_config={
                                        "phage_name": st.column_config.TextColumn("噬菌体名称", width="large"),
                                        "host_count": st.column_config.NumberColumn("覆盖菌株数", width="small"),
                                        "evidence_level": st.column_config.TextColumn("证据等级", width="small"),
                                    },
                                    use_container_width=True
                                )
                                st.caption("💡 这些噬菌体在该菌株所属的伪型别（簇）中具有广谱裂解能力")
                            else:
                                st.warning(f"该簇中无噬菌体同时覆盖 {min_host_count_individual} 个以上菌株")
                    else:
                        st.warning("请先运行聚类，生成簇分布。")

    with tab6:
        # ----- 步骤 1：查找可升级的互作记录 -----
        st.markdown("#### 🔍 步骤 1：查找可升级的互作记录")

        target_level_selector = st.selectbox(
            "目标证据等级",
            ["L3", "L4", "L5"],
            index=0,
            key="target_level_selector"
        )
        level_map = {
            "L3": ["L1", "L2"],
            "L4": ["L3"],
            "L5": ["L4"]
        }
        source_levels = level_map.get(target_level_selector, ["L1", "L2"])
        source_levels_str = "', '".join(source_levels)

        if st.button(f"查找 {', '.join(source_levels)} → {target_level_selector} 可升级记录"):
            with st.spinner("查询中..."):
                with driver.session() as session:
                    result = session.run(f"""
                        MATCH (c:ClinicalCase)-[:TREATED_WITH]->(ph:Phage)-[:USED_IN]->(a:LysisAssay)
                        WHERE a.evidence_level IN ['{source_levels_str}']
                        RETURN DISTINCT c.case_id AS case_id,
                               ph.phage_id AS phage_id,
                               ph.name AS phage_name,
                               a.evidence_level AS evidence_level
                    """)
                    records = [dict(r) for r in result]

            if records:
                df = pd.DataFrame(records)
                st.dataframe(df[["case_id", "phage_name", "evidence_level"]], use_container_width=True)
            else:
                st.info(f"当前没有 {', '.join(source_levels)} → {target_level_selector} 可升级记录")

        st.caption("💡 证据等级说明：L1(文献) → L2(体外) → L3(单例临床) → L4(多中心) → L5(组织学习闭环)")

        # ----- 步骤 2：升级证据等级 -----
        st.markdown("---")
        st.markdown("#### ⚡ 步骤 2：升级证据等级")

        col1, col2, col3 = st.columns(3)
        with col1:
            case_id = st.text_input("病例 ID", value="CASE-002")
        with col2:
            clinical_outcome = st.selectbox(
                "临床结局",
                ["Improved", "Not improved", "Clinical improvement at Day 7", "其他"]
            )
        with col3:
            microbiological_outcome = st.selectbox(
                "微生物学结局",
                ["Clearance", "Persistent", "Bacteria decreased", "其他"]
            )

        target_level_exec = st.selectbox(
            "目标证据等级",
            ["L3", "L4", "L5"],
            index=0,
            key="target_level_exec"
        )

        if st.button("执行策展升级", type="primary"):
            with st.spinner("策展中..."):
                summary = curate_case_by_id(
                    driver,
                    case_id,
                    clinical_outcome,
                    microbiological_outcome,
                    target_level_exec
                )
            st.success(summary)

        # ----- 审核 EvidenceUpgradeProposal -----
        st.markdown("---")
        st.markdown("#### 🧾 步骤 3：审核待处理的升级提案")

        with driver.session() as session:
            pending_proposals = session.run("""
                MATCH (p:EvidenceUpgradeProposal)
                WHERE p.status = 'pending_review'
                RETURN p.proposal_id AS proposal_id,
                       p.assay_id AS assay_id,
                       p.source_case_id AS source_case_id,
                       p.current_level AS current_level,
                       p.proposed_level AS proposed_level,
                       p.reason AS reason,
                       p.proposed_by AS proposed_by,
                       p.proposed_at AS proposed_at
                ORDER BY p.proposed_at
            """)
            pending_list = [dict(r) for r in pending_proposals]

        if not pending_list:
            st.info("✅ 当前没有待审核的升级提案")
        else:
            st.write(f"共 **{len(pending_list)}** 个提案待审核")
            for prop in pending_list:
                with st.container(border=True):
                    cols = st.columns([3, 1, 1, 1])
                    with cols[0]:
                        st.write(f"**{prop['proposal_id']}**")
                        st.write(f"Assay: `{prop['assay_id']}`  病例: `{prop['source_case_id']}`")
                        st.write(f"{prop['current_level']} → {prop['proposed_level']}")
                        st.caption(f"理由: {prop['reason'][:80]}..." if prop['reason'] and len(prop['reason']) > 80 else f"理由: {prop['reason']}")
                        st.caption(f"提议人: {prop['proposed_by']} 于 {prop['proposed_at']}")
                    with cols[1]:
                        if st.button("✅ 批准", key=f"approve_{prop['proposal_id']}"):
                            try:
                                review_id = review_evidence_upgrade_proposal(
                                    driver, prop['proposal_id'], "expert_001", "approved", "界面审核通过"
                                )
                                st.success(f"已批准，Review ID: {review_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"审核失败: {e}")
                    with cols[2]:
                        if st.button("❌ 拒绝", key=f"reject_{prop['proposal_id']}"):
                            try:
                                review_id = review_evidence_upgrade_proposal(
                                    driver, prop['proposal_id'], "expert_001", "rejected", "界面审核拒绝"
                                )
                                st.success(f"已拒绝，Review ID: {review_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"审核失败: {e}")
                    with cols[3]:
                        if st.button("📝 需修改", key=f"revise_{prop['proposal_id']}"):
                            try:
                                review_id = review_evidence_upgrade_proposal(
                                    driver, prop['proposal_id'], "expert_001", "needs_revision", "需补充数据"
                                )
                                st.success(f"已标记为需修改，Review ID: {review_id}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"操作失败: {e}")

            # 证据包审核
            st.markdown("---")
            st.markdown("#### 📦 步骤 4：审核生成的证据包")
            st.caption("对 ScientificEvidencePackage 执行批准/拒绝操作")

            try:
                with driver.session() as session:
                    pending_pkgs = session.run("""
                        MATCH (p:ScientificEvidencePackage)
                        WHERE p.review_status = 'pending' OR p.status = 'draft'
                        RETURN p.package_id AS package_id,
                               p.package_type AS package_type,
                               p.generated_by AS generated_by,
                               p.created_at AS created_at,
                               p.summary AS summary
                        ORDER BY p.created_at DESC
                        LIMIT 20
                    """)
                    pkg_list = [dict(r) for r in pending_pkgs]
            except Exception as e:
                st.warning(f"无法加载证据包列表: {e}")
                pkg_list = []

            if not pkg_list:
                st.info("✅ 当前没有待审核的证据包")
            else:
                st.write(f"共 **{len(pkg_list)}** 个证据包待审核")
                for pkg in pkg_list:
                    with st.container(border=True):
                        cols = st.columns([3, 1, 1])
                        with cols[0]:
                            st.write(f"**{pkg['package_id']}**")
                            st.write(f"类型: {pkg['package_type']}  生成者: {pkg['generated_by']}")
                            summary_text = pkg.get('summary') or '无摘要'
                            st.caption(f"摘要: {summary_text[:100]}{'...' if len(summary_text) > 100 else ''}")
                            created_at = pkg.get('created_at')
                            time_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                            st.caption(f"创建于: {time_str}")
                        with cols[1]:
                            if st.button("✅ 批准", key=f"approve_pkg_{pkg['package_id']}"):
                                try:
                                    review_id = review_scientific_evidence_package(
                                        driver, pkg['package_id'], "expert_001", "approved", "界面审核通过"
                                    )
                                    st.success(f"已批准，Review ID: {review_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"审核失败: {e}")
                        with cols[2]:
                            if st.button("❌ 拒绝", key=f"reject_pkg_{pkg['package_id']}"):
                                try:
                                    review_id = review_scientific_evidence_package(
                                        driver, pkg['package_id'], "expert_001", "rejected", "界面审核拒绝"
                                    )
                                    st.success(f"已拒绝，Review ID: {review_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"审核失败: {e}")

            # Assay QC 审核
            st.markdown("---")
            st.markdown("#### 🧪 步骤 5：Assay QC 审核")
            st.caption("对 LysisAssay 实验进行质量审核（passed/failed）")

            try:
                with driver.session() as session:
                    pending_assays = session.run("""
                        MATCH (a:LysisAssay)
                        WHERE a.qc_status = 'pending' OR a.validation_status = 'unreviewed'
                        RETURN a.assay_id AS assay_id,
                               a.pathogen_id AS pathogen_id,
                               a.evidence_level AS evidence_level,
                               a.qc_status AS qc_status,
                               a.created_at AS created_at
                        ORDER BY a.created_at DESC
                        LIMIT 20
                    """)
                    assay_list = [dict(r) for r in pending_assays]
            except Exception as e:
                st.warning(f"无法加载待审核实验列表: {e}")
                assay_list = []

            if not assay_list:
                st.info("✅ 当前没有待审核的实验")
            else:
                st.write(f"共 **{len(assay_list)}** 个实验待审核（显示前 10 条）")
                for assay in assay_list[:10]:
                    with st.container(border=True):
                        cols = st.columns([3, 1, 1, 1])
                        with cols[0]:
                            st.write(f"**{assay['assay_id']}**")
                            st.write(f"Pathogen: `{assay['pathogen_id']}`  证据等级: {assay['evidence_level']}")
                            created_at = assay.get('created_at')
                            time_str = created_at.isoformat() if hasattr(created_at, 'isoformat') else str(created_at)
                            st.caption(f"QC 状态: {assay['qc_status']}  创建于: {time_str}")
                        with cols[1]:
                            if st.button("✅ 通过", key=f"qc_pass_{assay['assay_id']}"):
                                try:
                                    review_id = review_assay_qc(
                                        driver, assay['assay_id'], "expert_001", "passed", "QC 审核通过"
                                    )
                                    st.success(f"已通过，Review ID: {review_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"操作失败: {e}")
                        with cols[2]:
                            if st.button("❌ 未通过", key=f"qc_fail_{assay['assay_id']}"):
                                try:
                                    review_id = review_assay_qc(
                                        driver, assay['assay_id'], "expert_001", "failed", "QC 审核未通过"
                                    )
                                    st.success(f"已标记失败，Review ID: {review_id}")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"操作失败: {e}")
                        with cols[3]:
                            if st.button("🔍 详情", key=f"qc_detail_{assay['assay_id']}"):
                                try:
                                    with driver.session() as session:
                                        detail = session.run("""
                                            MATCH (a:LysisAssay {assay_id: $assay_id})
                                            OPTIONAL MATCH (ph:Phage)-[:USED_IN]->(a)
                                            OPTIONAL MATCH (a)-[:TESTED_AGAINST]->(h:HostStrain)
                                            RETURN a.assay_id AS assay_id,
                                                   ph.name AS phage_name,
                                                   h.strain_label AS host_strain,
                                                   a.result_value AS probability,
                                                   a.evidence_ref AS evidence_ref,
                                                   a.qc_status AS qc_status
                                        """, assay_id=assay['assay_id']).single()
                                        if detail:
                                            st.json(dict(detail))
                                        else:
                                            st.warning("未找到该实验的详细信息")
                                except Exception as e:
                                    st.error(f"加载详情失败: {e}")

            # 验证升级结果
            st.markdown("---")
            st.markdown("#### ✅ 步骤 6：验证升级结果")

            col1, col2 = st.columns(2)
            with col1:
                verify_case_id = st.text_input("验证病例 ID", value="CASE-002")
            with col2:
                verify_phage_id = st.text_input("验证噬菌体 ID（可选，留空则查所有）", value="")

            if st.button("验证升级结果"):
                with st.spinner("验证中..."):
                    with driver.session() as session:
                        if verify_phage_id.strip():
                            result = session.run("""
                                MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage {phage_id: $phage_id})
                                MATCH (ph)-[:USED_IN]->(a:LysisAssay)
                                RETURN DISTINCT ph.name AS phage_name,
                                       a.evidence_level AS evidence_level,
                                       a.evidence_ref AS evidence_ref
                            """, case_id=verify_case_id, phage_id=verify_phage_id)
                        else:
                            result = session.run("""
                                MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage)
                                MATCH (ph)-[:USED_IN]->(a:LysisAssay)
                                RETURN DISTINCT ph.name AS phage_name,
                                       ph.phage_id AS phage_id,
                                       a.evidence_level AS evidence_level,
                                       a.evidence_ref AS evidence_ref
                            """, case_id=verify_case_id)

                        records = [dict(r) for r in result]

                if records:
                    df = pd.DataFrame(records)
                    st.dataframe(df, use_container_width=True)

                    for r in records:
                        if r['evidence_level'] in ['L3', 'L4', 'L5']:
                            st.success(f"✅ {r['phage_name']} 已升级至 {r['evidence_level']}，来源: {r['evidence_ref']}")
                        else:
                            st.warning(f"⚠️ {r['phage_name']} 仍为 {r['evidence_level']}，尚未升级")
                else:
                    st.warning("未找到该病例的互作记录")

            # L3 证据查询
            with st.expander("📊 查看 L3 证据"):
                with st.spinner("查询中..."):
                    records = query_l3_evidence()
                if records:
                    df = pd.DataFrame(records)
                    st.dataframe(df, use_container_width=True)
                else:
                    st.info("暂无 L3 临床验证记录")

            # 管理病例-噬菌体治疗关系
            with st.expander("📌 病例-噬菌体关联"):
                st.caption("选择病例，查看并编辑其使用的噬菌体（可多选添加或删除）")

                with driver.session() as session:
                    cases_result = session.run("MATCH (c:ClinicalCase) RETURN c.case_id AS case_id ORDER BY case_id")
                    case_ids = [record["case_id"] for record in cases_result]

                if not case_ids:
                    st.warning("暂无病例数据，请先导入病例")
                else:
                    selected_case = st.selectbox("选择病例", case_ids, key="case_select_for_phage")

                    with driver.session() as session:
                        current_phages = session.run("""
                            MATCH (c:ClinicalCase {case_id: $case_id})-[:TREATED_WITH]->(p:Phage)
                            OPTIONAL MATCH (p)-[:USED_IN]->(a:LysisAssay)
                            RETURN p.phage_id AS phage_id, p.name AS name,
                                   collect(DISTINCT a.evidence_level) AS evidence_levels
                        """, case_id=selected_case)
                        current_list = []
                        for r in current_phages:
                            levels = r["evidence_levels"]
                            level_display = next((lvl for lvl in levels if lvl and lvl.strip()), "无互作")
                            current_list.append((r["phage_id"], r["name"], level_display))

                    st.write(f"**当前关联的噬菌体（{len(current_list)} 个）**")
                    if current_list:
                        current_df = pd.DataFrame(current_list, columns=["噬菌体ID", "名称", "互作证据等级"])
                        st.dataframe(current_df, use_container_width=True, hide_index=True)
                    else:
                        st.info("该病例尚未关联任何噬菌体")

                    if current_list:
                        delete_options = {f"{pid} ({name})": pid for pid, name, _ in current_list}
                        to_delete = st.multiselect(
                            "选择要删除的噬菌体（可多选）",
                            options=list(delete_options.keys()),
                            key="delete_phage_multiselect"
                        )
                        if st.button("🗑️ 删除选中的噬菌体", key="delete_phage_btn"):
                            if not to_delete:
                                st.warning("请至少选择一个噬菌体")
                            else:
                                with st.spinner("删除中..."):
                                    for item in to_delete:
                                        phage_id = delete_options[item]
                                        with driver.session() as session:
                                            session.run("""
                                                MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(p:Phage {phage_id: $phage_id})
                                                DELETE r
                                            """, case_id=selected_case, phage_id=phage_id)
                                st.success(f"已删除 {len(to_delete)} 个噬菌体关系")
                                st.rerun()

                    st.markdown("---")
                    current_ids = {pid for pid, _, _ in current_list}
                    with driver.session() as session:
                        all_phages = session.run("MATCH (p:Phage) RETURN p.phage_id AS phage_id, p.name AS name ORDER BY phage_id")
                        all_list = [(r["phage_id"], r["name"]) for r in all_phages]
                    available = [(pid, name) for pid, name in all_list if pid not in current_ids]
                    if available:
                        add_options = {f"{pid} ({name})": pid for pid, name in available}
                        to_add = st.multiselect(
                            "选择要添加的噬菌体（可多选）",
                            options=list(add_options.keys()),
                            key="add_phage_multiselect"
                        )
                        if st.button("➕ 添加选中的噬菌体", key="add_phage_btn"):
                            if not to_add:
                                st.warning("请至少选择一个噬菌体")
                            else:
                                with st.spinner("添加中..."):
                                    for item in to_add:
                                        phage_id = add_options[item]
                                        with driver.session() as session:
                                            existing = session.run("""
                                                MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(p:Phage {phage_id: $phage_id})
                                                RETURN r
                                            """, case_id=selected_case, phage_id=phage_id).single()
                                            if not existing:
                                                session.run("""
                                                    MATCH (c:ClinicalCase {case_id: $case_id})
                                                    MATCH (p:Phage {phage_id: $phage_id})
                                                    CREATE (c)-[:TREATED_WITH]->(p)
                                                """, case_id=selected_case, phage_id=phage_id)
                                st.success(f"已添加 {len(to_add)} 个噬菌体关系")
                                st.rerun()
                    else:
                        st.info("所有噬菌体均已关联，无更多可添加")

    with tab7:
        st.subheader("📋 审计日志")
        if st.button("📝 生成测试审计事件"):
            with st.spinner("生成审计事件..."):
                # 修改点2：使用 write_audit_event 替代 log_action
                event_id = write_audit_event(
                    driver,
                    action_type="CREATE",
                    object_type="ClinicalCase",
                    object_id="DEMO-001",
                    actor_id="demo_user",
                    delta={"before": {"status": "before"}, "after": {"status": "after"}},
                    reason="演示审计事件"
                )
                st.success(f"✅ 已生成测试审计事件: {event_id}")
                st.rerun()

        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            filter_action = st.text_input("按动作类型筛选（留空显示全部）", value="")
        with col_filter2:
            filter_object = st.text_input("按对象 ID 筛选（留空显示全部）", value="")

        with st.spinner("加载审计日志..."):
            with driver.session() as session:
                # 修改点3：适配实际 AuditEvent 属性
                query = """
                    MATCH (a:AuditEvent)
                    WHERE ($action_filter = '' OR a.action_type CONTAINS $action_filter)
                    AND ($object_filter = '' OR a.object_id CONTAINS $object_filter)
                    RETURN a.audit_id AS event_id,
                           a.action_type AS action_type,
                           a.object_type AS object_type,
                           a.object_id AS object_id,
                           a.actor_id AS actor_id,
                           a.timestamp AS occurred_at,
                           a.reason AS reason,
                           a.delta AS delta
                    ORDER BY a.timestamp DESC
                    LIMIT 10
                """
                result = session.run(query, action_filter=filter_action, object_filter=filter_object)
                logs = [dict(r) for r in result]

        if not logs:
            st.info("暂无审计日志记录")
        else:
            st.write(f"共显示 {len(logs)} 条最新记录")
            df_log = pd.DataFrame(logs)
            display_cols = ["occurred_at", "action_type", "object_type", "object_id", "actor_id", "reason"]
            df_display = df_log[display_cols].copy()
            df_display['occurred_at'] = df_display['occurred_at'].apply(
                lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x)
            )
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            with st.expander("查看详细变更（快照）"):
                for log in logs[:10]:
                    time_str = log['occurred_at'].isoformat() if hasattr(log['occurred_at'], 'isoformat') else str(log['occurred_at'])
                    st.write(f"**{time_str} - {log['action_type']}**")
                    if log['delta']:
                        # 解析 JSON 字符串
                        try:
                            delta_obj = json.loads(log['delta']) if isinstance(log['delta'], str) else log['delta']
                            st.json(delta_obj)
                        except:
                            st.write(log['delta'])
                    st.write("---")

# ================== CI 竞争情报模块 ==================
else:
    # CI 模式主界面
    if "ci_context" not in st.session_state:
        st.session_state.ci_context = {
            "org_ids": {},
            "program_ids": {},
            "source_ids": {},
            "event_ids": {},
            "strategy_ids": {},
            "construct_ids": {},
            "claim_ids": {},
            "result_ids": {},
            "tech_assessment_ids": {},
            "brief_ids": {},
            "decision_ids": [],
            "use_event_ids": [],
        }

    ci_tab1, ci_tab2 = st.tabs(["📋 情报流程", "🔍 情报查询"])

    with ci_tab1:
        st.markdown("模拟完整的竞争情报流程：情报来源 → 事件 → 简报 → 审核 → 决策 → 消费记录")
        # ---------- 步骤 1 ----------
        st.subheader("1. 创建组织、项目、事件")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("执行步骤1 (创建组织/项目/事件)", key="ci_step1"):
                try:
                    with st.spinner("创建组织、项目、事件..."):
                        org_id = create_organization(
                            driver,
                            canonical_name="Proteon Pharmaceuticals",
                            organization_type="biotech",
                            aliases=["Proteon"],
                            headquarters_country="Poland",
                            website="https://www.proteonpharma.com",
                            description="Developing bacteriophage-based solutions for animal health and food safety."
                        )
                        st.session_state.ci_context["org_ids"]["Proteon"] = org_id
                        st.write(f"✅ 组织创建成功: {org_id}")

                        prog_id = create_development_program(
                            driver,
                            organization_id=org_id,
                            canonical_name="BAFASAL",
                            program_type="therapeutic",
                            development_stage="commercial",
                            modality="cocktail",
                            target_pathogen_species=["Salmonella enterica"]
                        )
                        st.session_state.ci_context["program_ids"]["BAFASAL"] = prog_id
                        st.write(f"✅ 项目创建成功: {prog_id}")

                        src1 = create_source_artifact(
                            driver,
                            source_type="regulatory_filing",
                            title="BAFASAL EU Authorization — EMA Decision",
                            url="https://www.ema.europa.eu/...",
                            published_date="2022-03-15",
                            credibility_tier="primary",
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["source_ids"]["src1"] = src1
                        st.write(f"✅ SourceArtifact 1 创建成功: {src1}")

                        src2 = create_source_artifact(
                            driver,
                            source_type="press_release",
                            title="Proteon Series B funding announcement",
                            url="https://www.proteonpharma.com/news/series-b",
                            published_date="2023-05-10",
                            credibility_tier="secondary",
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["source_ids"]["src2"] = src2
                        st.write(f"✅ SourceArtifact 2 创建成功: {src2}")

                        event1 = capture_intelligence_event(
                            driver,
                            event_type="regulatory_update",
                            title="BAFASAL® receives EU authorization for Salmonella control in poultry",
                            factual_summary="Proteon Pharmaceuticals' BAFASAL® product received EU authorization...",
                            organization_id=org_id,
                            program_id=prog_id,
                            event_date="2022-03-15",
                            published_at="2022-03-16",
                            source_ids=[src1],
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["event_ids"]["event1"] = event1
                        st.write(f"✅ 事件1创建成功: {event1}")

                        event2 = capture_intelligence_event(
                            driver,
                            event_type="funding",
                            title="Proteon Pharmaceuticals secures €15M Series B funding",
                            factual_summary="Proteon Pharmaceuticals closed a €15 million Series B financing...",
                            organization_id=org_id,
                            program_id=prog_id,
                            event_date="2023-05-10",
                            published_at="2023-05-11",
                            source_ids=[src2],
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["event_ids"]["event2"] = event2
                        st.write(f"✅ 事件2创建成功: {event2}")

                        st.success("步骤1执行完成！")
                except Exception as e:
                    st.error(f"步骤1执行失败: {e}")

        st.markdown("---")

        # ---------- 步骤 2 ----------
        st.subheader("2. 创建工程策略与构建体")
        if st.button("执行步骤2 (创建策略/构建体)", key="ci_step2"):
            try:
                with st.spinner("创建工程策略和构建体..."):
                    strategy_id = create_engineering_strategy(
                        driver,
                        strategy_type="host_range_expansion",
                        description="通过改造尾纤维或受体结合蛋白来扩展宿主范围",
                        evidence_maturity="in_vitro"
                    )
                    st.session_state.ci_context["strategy_ids"]["host_range_expansion"] = strategy_id
                    st.write(f"✅ 策略创建成功: {strategy_id}")

                    construct_id = create_engineered_construct(
                        driver,
                        public_name="vB_Kpn_HRE_001",
                        construct_code="HRE-001",
                        parent_phage_name="PKP001",
                        intended_effects=["宿主范围扩展", "针对KL47型肺炎克雷伯菌"],
                        target_pathogen_ids=["PATH-003"],
                        strategy_ids=[strategy_id],
                        construct_status="in_vitro_tested",
                        first_public_date="2025-06-15"
                    )
                    st.session_state.ci_context["construct_ids"]["vB_Kpn_HRE_001"] = construct_id
                    st.write(f"✅ 构建体创建成功: {construct_id}")

                    st.success("步骤2执行完成！")
            except Exception as e:
                st.error(f"步骤2执行失败: {e}")

        st.markdown("---")

        # ---------- 步骤 3 ----------
        st.subheader("3. 创建技术主张和结果")
        if st.button("执行步骤3", key="ci_step3"):
            try:
                with st.spinner("创建技术主张和结果..."):
                    construct_id = st.session_state.ci_context["construct_ids"].get("vB_Kpn_HRE_001")
                    if not construct_id:
                        st.error("请先执行步骤2创建构建体")
                    else:
                        claim1 = create_technical_claim(
                            driver,
                            claim_type="host_range",
                            claim_text="该工程化构建体成功将宿主范围从KL1型扩展到KL47型肺炎克雷伯菌",
                            exact_quote="The engineered phage showed expanded host range to KL47 K. pneumoniae strains",
                            claimant_type="publication",
                            evidence_context="in_vitro",
                            construct_id=construct_id,
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["claim_ids"]["claim1"] = claim1
                        st.write(f"✅ 主张1创建成功: {claim1}")

                        claim2 = create_technical_claim(
                            driver,
                            claim_type="efficacy",
                            claim_text="该构建体对多重耐药肺炎克雷伯菌具有高效裂解活性且安全性良好",
                            claimant_type="company",
                            evidence_context="in_vitro",
                            construct_id=construct_id,
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["claim_ids"]["claim2"] = claim2
                        st.write(f"✅ 主张2创建成功: {claim2}")

                        result1 = create_technical_result(
                            driver,
                            result_type="host_range",
                            study_context="in_vitro",
                            outcome_direction="positive",
                            metric_name="host_coverage",
                            metric_value=0.85,
                            metric_unit="%",
                            comparator="亲本噬菌体",
                            sample_size=12,
                            limitation_summary="仅测试了12株KL47型菌株，需进一步验证",
                            construct_id=construct_id,
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["result_ids"]["result1"] = result1
                        st.write(f"✅ 结果1创建成功: {result1}")

                        result2 = create_technical_result(
                            driver,
                            result_type="lysis",
                            study_context="in_vitro",
                            outcome_direction="positive",
                            metric_name="lysis_efficiency",
                            metric_value=98.5,
                            metric_unit="%",
                            comparator="对照组",
                            sample_size=3,
                            limitation_summary="仅进行了3次重复实验",
                            construct_id=construct_id,
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["result_ids"]["result2"] = result2
                        st.write(f"✅ 结果2创建成功: {result2}")

                        st.success("步骤3执行完成！")
            except Exception as e:
                st.error(f"步骤3执行失败: {e}")

        st.markdown("---")

        # ---------- 步骤 4 ----------
        st.subheader("4. 生成竞争简报并审核")
        if st.button("执行步骤4", key="ci_step4"):
            try:
                with st.spinner("生成简报并审核..."):
                    org_id = st.session_state.ci_context["org_ids"].get("Proteon")
                    if not org_id:
                        st.error("请先执行步骤1创建组织")
                    else:
                        # 修改点4：获取组织名称用于摘要
                        with driver.session() as session:
                            result = session.run(
                                "MATCH (o:Organization {organization_id: $oid}) RETURN o.canonical_name AS name",
                                oid=org_id
                            ).single()
                            org_name = result["name"] if result else org_id

                        brief = generate_competitor_brief(driver, org_id, days_back=365, persist=True)
                        brief_id = brief.get("brief_id")
                        if not brief_id:
                            st.error("简报生成失败")
                        else:
                            st.session_state.ci_context["brief_ids"]["test"] = brief_id
                            st.write(f"✅ 简报已生成，ID: {brief_id}")

                            review_brief_id = create_review(
                                driver,
                                review_type="intelligence_product_review",
                                target_object_type="IntelligenceProduct",
                                target_object_id=brief_id,
                                reviewer_id="expert_wang",
                                decision="approved",
                                comment="简报内容准确，批准作为决策依据。",
                                update_target_status=True,
                                actor_id="system"
                            )
                            st.write(f"✅ 简报审核通过，Review ID: {review_brief_id}")

                            # 创建竞争评估（使用组织名称）
                            assess_id = create_competitor_assessment(
                                driver,
                                assessment_type="threat",
                                subject_type="organization",
                                subject_id=org_id,
                                impact_area="market",
                                impact_level="high",
                                assessment_summary=f"{org_name} 近期在噬菌体领域取得进展，可能形成竞争。",
                                confidence="medium",
                                analyst_id="analyst_zhang",
                                time_horizon="short",
                                assumptions=["产品商业化顺利"],
                                unknowns=["市场接受度"],
                                actor_id="system"
                            )
                            st.write(f"✅ 竞争评估创建成功: {assess_id}")

                            review_id = create_review(
                                driver,
                                review_type="intelligence_product_review",
                                target_object_type="CompetitorAssessment",
                                target_object_id=assess_id,
                                reviewer_id="expert_wang",
                                decision="approved",
                                comment="评估合理，批准。",
                                update_target_status=True,
                            )
                            st.write(f"✅ 评估审核通过，Review ID: {review_id}")

                            # 创建决策记录（使用组织名称）
                            dec_id = create_decision_record(
                                driver,
                                brief_id=brief_id,
                                decision_type="monitor",
                                decision_summary=f"将 {org_name} 列入年度重点监控名单，每季度更新管线进展",
                                rationale="基于竞争评估和专家审核结论",
                                decision_owner="VP_Strategy",
                                review_date="2027-01-01",
                            )
                            st.session_state.ci_context["decision_ids"].append(dec_id)
                            st.write(f"✅ 决策已记录，ID: {dec_id}")

                            st.success("步骤4执行完成！")
            except Exception as e:
                st.error(f"步骤4执行失败: {e}")

        st.markdown("---")

        # ---------- 步骤 5 ----------
        st.subheader("5. 记录情报消费事件")
        if st.button("执行步骤5", key="ci_step5"):
            try:
                with st.spinner("记录消费事件..."):
                    brief_id = st.session_state.ci_context["brief_ids"].get("test")
                    dec_id = st.session_state.ci_context["decision_ids"][-1] if st.session_state.ci_context["decision_ids"] else None
                    if not brief_id:
                        st.error("请先执行步骤4生成简报")
                    else:
                        use_event_id = record_intelligence_use(
                            driver,
                            product_id=brief_id,
                            consumer_type="IPD",
                            consumer_id="ipd_team",
                            use_purpose="go_no_go_decision",
                            context_note="IPD团队在评估噬菌体工程化产品立项可行性时参考了该简报（已审核通过）。",
                            referenced_decision_id=dec_id,
                            actor_id="test_user"
                        )
                        st.session_state.ci_context["use_event_ids"].append(use_event_id)
                        st.write(f"✅ 使用事件记录成功: {use_event_id}")
                        st.success("步骤5执行完成！")
            except Exception as e:
                st.error(f"步骤5执行失败: {e}")

        st.markdown("---")

        # ---------- 步骤 6 ----------
        st.subheader("6. 验证归因链")
        if st.button("执行步骤6", key="ci_step6"):
            try:
                with st.spinner("验证归因链..."):
                    verification_query = """
                    MATCH
                    (src:SourceArtifact)<-[:HAS_SOURCE]-(evt:IntelligenceEvent)-[:AFFECTS]->(prog:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen),
                    (brief:IntelligenceProduct)-[:COVERS]->(org:Organization),
                    (review:Review)-[:REVIEWS]->(brief),
                    (dec:DecisionRecord)-[:BASED_ON]->(brief),
                    (use:IntelligenceUseEvent)-[:CONSUMES]->(brief)
                    WHERE review.decision = 'approved'
                    RETURN
                    src.title AS evidence_source,
                    src.credibility_tier AS credibility,
                    evt.title AS intelligence_event,
                    p.species AS target_pathogen,
                    org.canonical_name AS competitor,
                    brief.brief_id AS brief_id,
                    review.decision AS review_status,
                    dec.decision_type AS decision_type,
                    use.consumer_type AS consumed_by,
                    use.use_purpose AS use_purpose
                    LIMIT 3
                    """
                    with driver.session() as session:
                        results = list(session.run(verification_query))
                    if results:
                        st.success(f"✅ 验证通过！共 {len(results)} 条完整归因链路")
                        for i, row in enumerate(results, 1):
                            st.write(f"**链路 {i}**")
                            st.write(f"证据来源: {row['evidence_source']}")
                            st.write(f"情报事件: {row['intelligence_event']}")
                            st.write(f"靶向病原: {row['target_pathogen']}")
                            st.write(f"竞争对手: {row['competitor']}")
                            st.write(f"简报ID: {row['brief_id']} [审核:{row['review_status']}]")
                            st.write(f"决策类型: {row['decision_type']}")
                            st.write(f"消费方: {row['consumed_by']} / 用途: {row['use_purpose']}")
                            st.write("---")
                    else:
                        st.warning("未找到完整的归因链路，请检查各步骤是否完整执行。")
            except Exception as e:
                st.error(f"验证失败: {e}")

    # ========== 情报查询 Tab ==========
    with ci_tab2:
        # ---- 组织列表 ----
        st.markdown("#### 组织列表")
        try:
            orgs = list_organizations(driver)
            if not orgs:
                st.info("暂无组织数据，请先执行步骤1创建组织。")
            else:
                rows = []
                for org in orgs:
                    org_id = org["id"]
                    name = org["name"]
                    org_type = org["type"]
                    country = org.get("country", "未知")

                    profile = build_competitor_profile(driver, org_id)
                    if "error" in profile:
                        detail_html = "无法加载详情"
                    else:
                        progs = profile.get('active_programs', [])
                        prog_list = "<br>".join([f"• {p['name']} ({p['stage']})" for p in progs[:5]]) or "无"
                        detail_html = f"""
                        <b>名称</b>: {profile['organization']['name']}<br>
                        <b>类型</b>: {profile['organization']['org_type']}<br>
                        <b>国家</b>: {profile['organization']['country'] or '未知'}<br>
                        <b>项目数</b>: {len(progs)}<br>
                        <b>事件数</b>: {len(profile.get('recent_events', []))}<br>
                        <b>数据截止</b>: {profile.get('as_of_date', 'N/A')}<br>
                        <b>研发项目</b>:<br>{prog_list}
                        """

                    row = f"""
                    <tr>
                        <td>{name}</td>
                        <td>{org_type}</td>
                        <td>{country}</td>
                        <td style="position:relative; overflow:visible;">
                            <span class="detail-trigger">📋 详情</span>
                            <div class="detail-popup">
                                {detail_html}
                            </div>
                        </td>
                    </tr>
                    """
                    rows.append(row)

                table_html = f"""
                <style>
                .org-table {{
                    width: 100%;
                    table-layout: fixed;
                    border-collapse: collapse;
                    font-size: 0.85rem;
                    border: 1px solid #e0e4e8;
                    border-radius: 10px;
                    overflow: visible;
                }}
                .org-table th,
                .org-table td {{
                    padding: 8px 10px;
                    text-align: left;
                    vertical-align: middle;
                    border-bottom: 1px solid #f1f5f9;
                    word-break: break-word;
                    overflow-wrap: break-word;
                }}
                .org-table th {{
                    background: #f7f9fc;
                    font-weight: 600;
                    border-bottom: 1.5px solid #e2e8f0;
                }}
                .org-table tr:last-child td {{
                    border-bottom: none;
                }}
                .org-table tr:hover td {{
                    background: #f8faff;
                }}
                .org-table th:nth-child(1),
                .org-table td:nth-child(1) {{ width: 40%; }}
                .org-table th:nth-child(2),
                .org-table td:nth-child(2) {{ width: 18%; }}
                .org-table th:nth-child(3),
                .org-table td:nth-child(3) {{ width: 18%; }}
                .org-table th:nth-child(4),
                .org-table td:nth-child(4) {{ width: 24%; }}
                .detail-trigger {{
                    display: inline-block;
                    background: #eef2ff;
                    color: #1e40af;
                    border-radius: 10px;
                    padding: 0 10px;
                    font-size: 0.75rem;
                    line-height: 1.8;
                    cursor: default;
                    position: relative;
                    z-index: 1;
                    white-space: nowrap;
                }}
                .detail-popup {{
                    visibility: hidden;
                    opacity: 0;
                    position: absolute;
                    left: 0;
                    top: 100%;
                    margin-top: 6px;
                    background: white;
                    border: 1px solid #cbd5e1;
                    border-radius: 8px;
                    padding: 10px 14px;
                    min-width: 200px;
                    max-width: 320px;
                    box-shadow: 0 6px 16px rgba(0,0,0,0.12);
                    font-size: 0.78rem;
                    line-height: 1.5;
                    white-space: normal;
                    z-index: 9999;
                    transition: opacity 0.2s ease, visibility 0.2s ease;
                    pointer-events: none;
                }}
                .detail-trigger:hover + .detail-popup,
                .detail-trigger:focus + .detail-popup {{
                    visibility: visible;
                    opacity: 1;
                }}
                td:hover .detail-popup {{
                    visibility: visible;
                    opacity: 1;
                }}
                </style>
                <table class="org-table">
                    <thead>
                        <tr>
                            <th>名称</th>
                            <th>类型</th>
                            <th>国家</th>
                            <th style="text-align:center;">操作</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(rows)}
                    </tbody>
                </table>
                """
                from streamlit.components.v1 import html
                html(table_html, height=400, scrolling=True)
        except Exception as e:
            st.error(f"加载组织列表失败: {e}")

        st.markdown("---")

        # ---- 最新事件 ----
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
                    st.dataframe(df_events, use_container_width=True, hide_index=True)
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
                    st.dataframe(df_briefs, use_container_width=True, hide_index=True)
                else:
                    st.info("暂无简报记录。")
        except Exception as e:
            st.error(f"加载简报失败: {e}")

# ---------- 底部信息 ----------
st.markdown("---")
st.caption("⚠️ 演示版本，所有操作基于本地 Neo4j 数据库，LLM 调用需配置 DeepSeek API Key")