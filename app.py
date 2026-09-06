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
from src.shared.audit_service import write_audit_event

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
from src.engineering_intelligence.construct_service import create_engineered_construct, get_constructs_by_strategy, link_program_to_construct
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
        label=" ",
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

# ============================================================
# 两个核心功能函数
# ============================================================

def phage_typing_mode(driver):
    """噬菌体配型模式的所有界面"""
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
                        try:
                            delta_obj = json.loads(log['delta']) if isinstance(log['delta'], str) else log['delta']
                            st.json(delta_obj)
                        except:
                            st.write(log['delta'])
                    st.write("---")


def ci_mode(driver):
    """CI竞争情报模式的所有界面"""
    # ---- 自定义 CSS 样式（提升视觉档次） ----
    st.markdown("""
    <style>
    .ci-main-title { font-size: 1.8rem; font-weight: 700; color: #0f172a; margin-bottom: 0.2rem; }
    .ci-subtitle { color: #64748b; margin-bottom: 1.5rem; }
    .ci-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.5rem 1.8rem;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
        border: 1px solid #f0f2f6;
        margin-bottom: 1.5rem;
        transition: box-shadow 0.2s ease;
    }
    .ci-card:hover { box-shadow: 0 4px 20px rgba(0,0,0,0.08); }
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
    .mermaid-container {
        background: white;
        border-radius: 12px;
        padding: 0.2rem 0.5rem !important;
        border: 1px solid #e9edf2;
        margin-bottom: 0.5rem;
        text-align: center;
    }
    .mermaid-container .mermaid {
        display: flex;
        justify-content: center;
    }
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

    # ---- 创建三个 Tab ----
    ci_tab0, ci_tab1, ci_tab2 = st.tabs(["📊 决策链图", "📋 情报流程", "🔍 情报查询"])

    # ========== Tab0: 决策链图（独立） ==========
    with ci_tab0:
        st.markdown("### 🧭 情报与决策 Ontology 链路")
        st.caption("下图展示了从情报源到组织决策的完整数据链路，包括市场情报与工程情报的融合。")
        st.markdown('<div class="mermaid-container">', unsafe_allow_html=True)
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
        st.components.v1.html(mermaid_html, height=310)
        
        st.markdown('</div>', unsafe_allow_html=True)
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
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
                st.markdown("#### 🏢 步骤 1：创建组织、项目与情报事件")

                if st.session_state.ci_step_status.get("step1_done", False):
                    # 已完成状态：显示已创建对象，并提供“添加更多事件”和“进入下一步”
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
                        submitted_append = st.form_submit_button("➕ 添加此事件", use_container_width=True)
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
                        # 手动跳转
                        st.session_state.ci_step = 1
                        st.rerun()
                else:
                    # 未完成状态：表单
                    with st.form("ci_step1_form"):
                        # 已有组织列表
                        existing = list_organizations(driver)
                        org_options = [""] + [f"{o['name']} ({o['id']})" for o in existing]
                        quick_org = st.selectbox("或选择已有组织（留空则新建）", options=org_options)

                        col1, col2 = st.columns(2)
                        with col1:
                            org_name = st.text_input("组织名称（新建时填写）", value="Proteon Pharmaceuticals")
                            org_type = st.selectbox("组织类型", ["biotech", "pharma", "academic", "CRO", "tech"])
                        with col2:
                            prog_name = st.text_input("项目名称", value="BAFASAL")
                            prog_stage = st.selectbox("研发阶段", ["discovery", "preclinical", "phase_1", "phase_2", "phase_3", "commercial"])

                        st.markdown("---")
                        st.markdown("#### 📝 添加情报事件（可选，可多次添加）")
                        evt_type = st.selectbox("事件类型", ["regulatory_update", "funding", "acquisition", "partnership", "clinical_trial_update", "patent_event", "pipeline_update"], key="evt_type")
                        evt_title = st.text_input("事件标题", value="New event", key="evt_title")
                        evt_summary = st.text_area("事件摘要", value="详细描述...", key="evt_summary")
                        evt_date = st.date_input("事件日期", value=pd.to_datetime("2026-01-01"), key="evt_date")
                        add_clicked = st.form_submit_button("➕ 添加事件到列表", use_container_width=False)

                    # 处理添加事件（在表单外，因为需要 rerun）
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

                    # 显示已暂存事件
                    if st.session_state.ci_context.get("temp_events"):
                        st.write("**已暂存的事件（待提交）:**")
                        for i, evt in enumerate(st.session_state.ci_context["temp_events"]):
                            st.write(f"  {i+1}. [{evt['type']}] {evt['title']} ({evt['date']})")

                    st.caption("💡 情报事件为可选，您可以直接提交而不添加任何事件。")

                    # 提交按钮（统一处理）
                    if st.button("🚀 提交并完成步骤1", use_container_width=True, type="primary"):
                        try:
                            with st.spinner("正在创建组织、项目及事件..."):
                                # ---- 1. 处理组织 ----
                                if quick_org and quick_org.strip():
                                    # 解析已有组织ID
                                    parts = quick_org.split("(")
                                    if len(parts) > 1:
                                        org_id = parts[1].rstrip(")")
                                    else:
                                        org_id = None
                                else:
                                    org_id = None

                                # 如果未选择已有组织，则新建
                                if not org_id:
                                    # 检查是否已存在同名组织（避免重复）
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
                                # 检查项目是否已存在（基于组织+名称）
                                with driver.session() as session:
                                    existing_prog = session.run(
                                        """
                                        MATCH (d:DevelopmentProgram {canonical_name: $pname, organization_id: $oid})
                                        RETURN d.program_id AS id
                                        """,
                                        pname=prog_name, oid=org_id
                                    ).single()
                                    if existing_prog:
                                        prog_id = existing_prog["id"]
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
                                st.session_state.ci_context["program_ids"][prog_name] = prog_id
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
                                    "program": f"{prog_name} (ID: {prog_id})",
                                    "sources": created_sources,
                                    "events": created_events
                                }
                                st.session_state.ci_context["temp_events"] = []  # 清空暂存
                                st.session_state.ci_step_status["step1_done"] = True
                                st.success(f"✅ 步骤1完成！已创建 {len(created_events)} 个事件。")

                                # ---- 5. 自动跳转到步骤2 ----
                                st.session_state.ci_step = 1
                                st.rerun()

                        except Exception as e:
                            st.error(f"❌ 执行失败：{e}")

                st.markdown('</div>', unsafe_allow_html=True)

        # 步骤 2
        elif step == 1:
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
                st.markdown("#### 🧬 步骤 2：创建工程策略与构建体")
                with st.form("ci_step2_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        strategy_type = st.selectbox("策略类型", ["host_range_expansion", "lysis_enhancement", "tail_fiber_engineering",
                                                                 "receptor_binding_engineering", "biofilm_disruption", "payload_delivery"])
                    with col2:
                        construct_name = st.text_input("构建体名称", value="vB_Kpn_HRE_001")
                    submitted = st.form_submit_button("🚀 执行步骤 2", use_container_width=True, type="primary")

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
                st.markdown('</div>', unsafe_allow_html=True)

        # 步骤 3
        elif step == 2:
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
                st.markdown("#### 📝 步骤 3：创建技术主张与结果")
                with st.form("ci_step3_form"):
                    col1, col2 = st.columns(2)
                    with col1:
                        claim_type = st.selectbox("主张类型", ["host_range", "efficacy", "safety", "manufacturability", "mechanism"])
                        claim_text = st.text_area("主张文本", value="", height=80)
                    with col2:
                        result_type = st.selectbox("结果类型", ["host_range", "lysis", "biofilm", "safety", "in_vivo", "computational"])
                        metric_value = st.number_input("结果值", value=0.85, step=0.05)
                    submitted = st.form_submit_button("🚀 执行步骤 3", use_container_width=True, type="primary")

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
                st.markdown('</div>', unsafe_allow_html=True)

        # 步骤 4
        elif step == 3:
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
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
                                        OPTIONAL MATCH (p)-[:USES_CONSTRUCT|ASSOCIATED_WITH]-(c:EngineeredPhageConstruct)
                                        OPTIONAL MATCH (c)-[:IMPLEMENTS]-(s:EngineeringStrategy)
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
                                submitted = st.form_submit_button("📄 生成简报", use_container_width=True, type="primary")
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
                            submitted_review = st.form_submit_button("✅ 提交审核（创建评估+决策）", use_container_width=True, type="primary")

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
                                st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)

        # 步骤 5
        elif step == 4:
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
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
                        submitted = st.form_submit_button("📌 记录消费", use_container_width=True, type="primary")

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
                st.markdown('</div>', unsafe_allow_html=True)

        # 步骤 6
        elif step == 5:
            with st.container():
                st.markdown('<div class="ci-card">', unsafe_allow_html=True)
                st.markdown("#### 🔗 步骤 6：验证归因链")
                if st.button("🔍 执行归因验证", use_container_width=True, type="primary"):
                    try:
                        with st.spinner("验证中..."):
                            # ---------- 按组织聚合查询 ----------
                            query = """
                            MATCH (brief:IntelligenceProduct)-[:COVERS]->(org:Organization)
                            MATCH (review:Review)-[:REVIEWS]->(brief)
                            WHERE review.decision = 'approved'
                            MATCH (dec:DecisionRecord)-[:BASED_ON]->(brief)
                            MATCH (use:IntelligenceUseEvent)-[:CONSUMES]->(brief)

                            OPTIONAL MATCH (src:SourceArtifact)<-[:HAS_SOURCE]-(evt:IntelligenceEvent)-[:AFFECTS]->(prog:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p:Pathogen)
                            WHERE evt.organization_id = org.organization_id

                            OPTIONAL MATCH (prog)-[:USES_CONSTRUCT]->(con:EngineeredPhageConstruct)
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
                            st.session_state.ci_step_status["step6_done"] = True
                            if not results:
                                st.warning("未找到完整归因链路。请确保至少有一个组织已完成简报审核并记录消费。")
                            else:
                                st.success(f"✅ 找到 {len(results)} 个组织具备完整归因链路")

                                # ----- 将结果转换为 DataFrame 展示 -----
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
                                st.dataframe(df, use_container_width=True, hide_index=True)

                                # 可选：提供查看单个组织完整详情的功能
                                st.markdown("---")
                                st.markdown("#### 📌 查看单个组织完整详情")
                                org_names = [row['competitor'] for row in results]
                                selected_org = st.selectbox("选择组织", org_names)
                                if selected_org:
                                    # 找到对应的原始行
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
                    except Exception as e:
                        st.error(f"验证失败：{e}")
                st.markdown('</div>', unsafe_allow_html=True)

        if all(st.session_state.ci_step_status.values()):
            st.rerun()

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
            search_clicked = st.button("🔍 搜索", key="ci_search_btn", use_container_width=True)

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

        # ---- 组织列表（按事件数排序，取前10） ----
        st.markdown("#### 组织列表（按事件数排序）")
        try:
            orgs = list_organizations(driver)
            if not orgs:
                st.info("暂无组织数据，请先执行步骤1创建组织。")
            else:
                # 为每个组织获取事件数并排序
                org_with_events = []
                for org in orgs:
                    org_id = org["id"]
                    with driver.session() as session:
                        event_count = session.run("""
                            MATCH (e:IntelligenceEvent {organization_id: $oid})
                            RETURN count(e) AS cnt
                        """, oid=org_id).single()["cnt"]
                    org_with_events.append({**org, "event_count": event_count})
                # 按事件数降序排序，取前10
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

        # ---- 最新事件和简报 ----
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

# ---------- 主界面 ----------
if mode == "噬菌体配型":
    phage_typing_mode(driver)
else:
    ci_mode(driver)

# ---------- 底部信息 ----------
st.markdown("---")
st.caption("⚠️ 演示版本，所有操作基于本地 Neo4j 数据库，LLM 调用需配置 DeepSeek API Key")