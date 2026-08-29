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
    load_patients_from_csv
)
from src.foundation.schema import create_schema, create_ontology_modules, create_controlled_vocabularies
from src.foundation.audit_service import log_action

# ---------- 获取项目根目录 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体配型系统", layout="wide")
st.title("噬菌体配型智能助手")
st.markdown("基于知识图谱的循证噬菌体推荐，支持裂解谱数据 + 临床验证（新模型 LysisAssay + HostStrain）")

# ---------- 缓存数据库连接 ----------
@st.cache_resource
def get_db():
    return get_driver()

try:
    driver = get_db()
    # 测试数据库连接
    with driver.session() as session:
        session.run("RETURN 1")
except Exception as e:
    st.error(f"⚠️ 无法连接 Neo4j 数据库，请检查 config.py 配置。错误: {str(e)}")
    st.stop()

# ---------- 侧边栏 ----------
with st.sidebar:
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

            status.update(label="全部完成！", state="complete")
        st.success("🎉 所有数据已重新导入！")
        st.rerun()
    
    st.markdown("---")
    st.subheader("📄 数据管理")
    
    with st.expander("📄 裂解谱最广的噬菌体（Top 5）"):
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

# ---------- 主界面：多标签页 ----------
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🔍 噬菌体配型查询",
    "📊 批量菌株配型",
    "📦 证据包生成",
    "🔄 跨病例复用",
    "📈 聚类分析",
    "📝 知识策展",
    "📋 审计日志"
])

# ================== 标签页 1：噬菌体配型查询 ==================
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

# ================== 标签页 2：批量菌株配型 ==================
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

# ================== 标签页 3：证据包生成 ==================
with tab3:
    st.subheader("生成 Evidence Package")
    col1, col2 = st.columns(2)
    with col1:
        species = st.text_input("病原菌物种", value="Acinetobacter baumannii")
        resistance = st.text_input("耐药机制（留空表示不限）", value="")
    with col2:
        infection_type = st.text_input("感染类型", value="Pneumonia")
        use_llm = st.checkbox("使用 LLM (DeepSeek)", value=True)
    
    # 修复 Bug 1：使用关键字参数显式传参，避免参数顺序错误
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
    
    # ===== 新功能 4：LLM 推荐效果验证 =====
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

# ================== 标签页 4：跨病例知识复用 ==================
with tab4:
    st.subheader("跨病例复用分析")
    col1, col2 = st.columns(2)
    with col1:
        case_a = st.text_input("病例 A ID", value="CASE-002")
    with col2:
        case_b = st.text_input("病例 B ID", value="CASE-003")
    
    # 修复 Bug 3：动态获取可用的 ScientificEvidencePackage
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
    
    # 审核待确认的复用事件
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

# ================== 标签页 5：聚类分析 ==================
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

# ================== 标签页 6：知识策展 ==================
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
    
        # ===== 新功能 1：证据包审核面板 =====
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
    
    # ===== 新功能 2：Assay QC 审核面板 =====
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
    
    # ----- 验证升级结果 -----
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
    
    # ----- L3 证据查询 -----
    with st.expander("📊 查看 L3 证据"):
        with st.spinner("查询中..."):
            records = query_l3_evidence()
        if records:
            df = pd.DataFrame(records)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("暂无 L3 临床验证记录")
    
    # ----- 管理病例-噬菌体治疗关系 -----
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

# ================== 标签页 7：审计日志 ==================
with tab7:
    st.subheader("📋 审计日志")
    
    # 生成测试审计事件
    if st.button("📝 生成测试审计事件"):
        with st.spinner("生成审计事件..."):
            event_id = log_action(
                driver,
                domain="scientific",
                action_type="DEMO_ACTION",
                object_type="ClinicalCase",
                object_id="DEMO-001",
                actor_id="demo_user",
                before_snapshot={"status": "before"},
                after_snapshot={"status": "after"},
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
                RETURN a.audit_event_id AS event_id,
                       a.domain AS domain,
                       a.action_type AS action_type,
                       a.object_type AS object_type,
                       a.object_id AS object_id,
                       a.actor_id AS actor_id,
                       a.occurred_at AS occurred_at,
                       a.reason AS reason,
                       a.before_snapshot AS before,
                       a.after_snapshot AS after
                ORDER BY a.occurred_at DESC
                LIMIT 10
            """
            result = session.run(query, action_filter=filter_action, object_filter=filter_object)
            logs = [dict(r) for r in result]
    
    if not logs:
        st.info("暂无审计日志记录")
    else:
        st.write(f"共显示 {len(logs)} 条最新记录")
        df_log = pd.DataFrame(logs)
        display_cols = ["occurred_at", "domain", "action_type", "object_type", "object_id", "actor_id", "reason"]
        df_display = df_log[display_cols].copy()
        # 修复 Neo4j DateTime 转换问题
        df_display['occurred_at'] = df_display['occurred_at'].apply(
            lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x)
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        
        with st.expander("查看详细变更（快照）"):
            for log in logs[:10]:
                time_str = log['occurred_at'].isoformat() if hasattr(log['occurred_at'], 'isoformat') else str(log['occurred_at'])
                st.write(f"**{time_str} - {log['action_type']}**")
                if log['before']:
                    st.write("变更前:", log['before'])
                if log['after']:
                    st.write("变更后:", log['after'])
                st.write("---")

# ---------- 底部信息 ----------
st.markdown("---")
st.caption("⚠️ 演示版本，所有操作基于本地 Neo4j 数据库，LLM 调用需配置 DeepSeek API Key")