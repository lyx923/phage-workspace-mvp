# app.py
import streamlit as st
import pandas as pd
import random
import json
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from config import get_driver
from src.validator import (
    query_phages_for_host,
    batch_validate_hosts,
    query_l3_evidence,
    query_hosts_for_phage,
    cluster_strains_from_csv,
    query_phages_by_pseudo_type_from_mapping
)
from src.package_builder import (
    build_evidence_package_from_db,
    rule_based_evidence_package
)
from src.retriever import analyze_cross_case_reuse_simple, find_matching_phages, find_similar_cases
from src.curation import curate_case_by_id
from src.data_loader import load_phages_from_lysis_csv_simple

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体配型系统", layout="wide")
st.title(" 噬菌体配型智能助手")
st.markdown("基于知识图谱的循证噬菌体推荐，支持裂解谱数据 + 临床验证")

# ---------- 缓存数据库连接 ----------
@st.cache_resource
def get_db():
    return get_driver()

driver = get_db()

# ---------- 侧边栏 ----------
with st.sidebar:
    st.header("📊 数据总览")
    
    with driver.session() as session:
        stats = session.run("""
            MATCH (phi:PhageHostInteraction)
            WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
            RETURN count(DISTINCT phi.phage_id) AS phage_count,
                   count(DISTINCT phi.notes) AS host_count,
                   count(phi) AS interaction_count
        """).single()
        col1, col2, col3 = st.columns(3)
        col1.metric("噬菌体", stats["phage_count"])
        col2.metric("宿主菌株", stats["host_count"])
        col3.metric("互作关系", stats["interaction_count"])
    
    st.markdown("---")
    
    # ===== 数据管理区域 =====
    st.subheader("🔄 数据管理")
    
    if st.button("🗑️ 清空并重新导入全部数据", type="secondary"):
        with st.status("执行数据导入...", expanded=True) as status:
            from src.data_loader import clear_database, load_cases_from_csv, load_phages_from_csv
            from src.schema import create_schema

            status.update(label="正在清空数据库...")
            clear_database()
            st.write("✅ 数据库已清空")

            status.update(label="创建约束和索引...")
            create_schema(driver)
            st.write("✅ 约束和索引已创建")

            status.update(label="导入噬菌体互作...")
            load_phages_from_csv("../data/phage_interactions.csv")
            st.write("✅ 噬菌体互作导入完成")

            status.update(label="导入临床病例...")
            load_cases_from_csv("../data/cases.csv")
            st.write("✅ 病例导入完成")

            status.update(label="导入裂解谱数据...")
            result = load_phages_from_lysis_csv_simple("../data/肺克数据脱敏.csv")
            st.write(f"✅ 裂解谱导入完成，新增 {result['positive_interactions']} 条记录")

            status.update(label="全部完成！", state="complete")
        st.success("🎉 所有数据已重新导入！")
        st.rerun()
    
    if st.button("🔄 重新导入裂解谱数据"):
        with st.spinner("导入中..."):
            result = load_phages_from_lysis_csv_simple()
        st.success(f"✅ 新增 {result['positive_interactions']} 条记录")
        st.rerun()
    
    # 新增：独立导入互作数据（FR-2）
    if st.button("📄 重新导入互作数据"):
        with st.spinner("导入中..."):
            from src.data_loader import load_phages_from_csv
            load_phages_from_csv("../data/phage_interactions.csv")
        st.success("✅ 互作数据导入完成！")
        st.rerun()
    
    # ===== 黄金配型管理 =====
    if st.button("📄 导入黄金配型知识库"):
        with st.status("导入黄金配型...", expanded=True) as status:
            from src.data_loader import get_driver as get_driver_dl
            
            validated_rules = [
                {
                    "rule_id": "RULE_CRAB_KL2",
                    "pathogen_species": "Acinetobacter baumannii",
                    "strain_type": "KL2",
                    "phage_name": "ΦK2-v3",
                    "treatment": "ΦK2-v3 单用",
                    "outcome": "第14天微生物清除，第6个月未复发",
                    "evidence_from": "肖易倍团队第N次配型"
                },
                {
                    "rule_id": "RULE_CRKP_KL47",
                    "pathogen_species": "Klebsiella pneumoniae",
                    "strain_type": "KL47",
                    "phage_name": "ΦK47-w7",
                    "treatment": "ΦK47-w7 + 碳青霉烯类",
                    "outcome": "第3个月未复发",
                    "evidence_from": "肖易倍团队第N次配型"
                },
                {
                    "rule_id": "RULE_ECOLI_O25",
                    "pathogen_species": "Escherichia coli",
                    "strain_type": "O25",
                    "phage_name": "CP-p-EC-23086",
                    "treatment": "膀胱灌注（局部递送）",
                    "outcome": "48小时内细菌计数断崖式下降",
                    "evidence_from": "临床验证（结合CASE-001及既往数据）"
                }
            ]
            
            with get_driver_dl() as d:
                with d.session() as s:
                    for rule in validated_rules:
                        result = s.run("""
                            MERGE (r:KnowledgeRule {rule_id: $rule_id})
                            SET r.strain_type = $strain_type,
                                r.treatment = $treatment,
                                r.outcome = $outcome,
                                r.evidence_from = $evidence_from
                            WITH r
                            MERGE (p:Pathogen {species: $pathogen_species})
                            ON CREATE SET p.resistance_mechanism = 'Unknown'
                            MERGE (p)-[:HAS_VALIDATED_RULE]->(r)
                            WITH r
                            MERGE (ph:Phage {name: $phage_name})
                            ON CREATE SET ph.family = 'Unknown'
                            MERGE (r)-[:RECOMMENDS_PHAGE]->(ph)
                            RETURN r.rule_id AS id
                        """,
                        rule_id=rule["rule_id"],
                        pathogen_species=rule["pathogen_species"],
                        strain_type=rule["strain_type"],
                        phage_name=rule["phage_name"],
                        treatment=rule["treatment"],
                        outcome=rule["outcome"],
                        evidence_from=rule["evidence_from"])
                        st.write(f"✅ {result.single()['id']}")
            status.update(label="全部完成！", state="complete")
        st.success("🎉 黄金配型知识库导入完成！")
        st.rerun()

    # ===== 测试用例管理 =====
    if st.button("📄 创建测试病例 CASE-998/999"):
        with st.status("创建测试病例...", expanded=True) as status:
            from src.data_loader import get_driver as get_driver_dl
            
            with get_driver_dl() as d:
                with d.session() as s:
                    # 创建 CASE-999 (CRAB KL2)
                    s.run("""
                        MERGE (p:Pathogen {species: "Acinetobacter baumannii"})
                        SET p.resistance_mechanism = "Carbapenem-resistant",
                            p.strain_type = "KL2",
                            p.verification_status = "MICROBIOLOGY_LAB_VERIFIED"
                        WITH p
                        CREATE (c:ClinicalCase {
                            case_id: "CASE-999",
                            infection_type: "Pneumonia",
                            infection_site: "Lung",
                            specimen_type: "Sputum",
                            patient_age_group: "65-75",
                            comorbidities: ["COPD", "Diabetes"],
                            prior_antibiotics: ["Meropenem", "Colistin"],
                            phage_treatment: null,
                            clinical_outcome: null,
                            microbiological_outcome: null,
                            curated_by: "FDE-TEST",
                            curation_date: date()
                        })
                        WITH c, p
                        MERGE (c)-[:INVOLVES_PATHOGEN]->(p)
                        MATCH (r:KnowledgeRule {rule_id: "RULE_CRAB_KL2"})
                        MERGE (p)-[:HAS_VALIDATED_RULE]->(r)
                        RETURN "CASE-999" AS case_id
                    """)
                    st.write("✅ CASE-999 (CRAB KL2) 创建成功")
                    
                    # 创建 CASE-998 (CRKP KL47)
                    s.run("""
                        MERGE (p:Pathogen {species: "Klebsiella pneumoniae"})
                        SET p.resistance_mechanism = "Carbapenem-resistant",
                            p.strain_type = "KL47",
                            p.verification_status = "MICROBIOLOGY_LAB_VERIFIED"
                        WITH p
                        CREATE (c:ClinicalCase {
                            case_id: "CASE-998",
                            infection_type: "VAP",
                            infection_site: "Lung",
                            specimen_type: "BALF",
                            patient_age_group: "55-65",
                            comorbidities: ["Diabetes", "Immunosuppression"],
                            prior_antibiotics: ["Meropenem"],
                            phage_treatment: null,
                            clinical_outcome: null,
                            microbiological_outcome: null,
                            curated_by: "FDE-TEST",
                            curation_date: date()
                        })
                        WITH c, p
                        MERGE (c)-[:INVOLVES_PATHOGEN]->(p)
                        MATCH (r:KnowledgeRule {rule_id: "RULE_CRKP_KL47"})
                        MERGE (p)-[:HAS_VALIDATED_RULE]->(r)
                        RETURN "CASE-998" AS case_id
                    """)
                    st.write("✅ CASE-998 (CRKP KL47) 创建成功")
            status.update(label="全部完成！", state="complete")
        st.success("🎉 测试病例创建完成！")
        st.rerun()

    st.markdown("---")
    
    # ===== V1 验证 =====
    st.subheader("📋 V1 数据完整性验证")
    if st.button("运行 V1 验证（必填字段填充率）"):
        with st.spinner("验证中..."):
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
                    
                    st.metric("必填字段填充率", f"{rate:.1f}%")
                    for field, count in filled.items():
                        st.write(f"   - {field}: {count}/{total} ({count/total*100:.0f}%)")
                    if rate >= 90:
                        st.success("🎉 V1 验证通过！填充率 ≥ 90%")
                    else:
                        st.warning(f"⚠️ V1 验证未通过（{rate:.1f}% < 90%）")
                else:
                    st.warning("数据库中无病例数据")
    
    # ===== 知识网络分析（折叠） =====
    with st.expander("📊 知识网络分析"):
        st.markdown("**网络规模**")
        with driver.session() as session:
            result = session.run("""
                MATCH (phi:PhageHostInteraction)
                WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                RETURN count(DISTINCT phi.phage_id) AS phage_count,
                       count(DISTINCT phi.notes) AS host_count,
                       count(phi) AS interaction_count
            """)
            stats = result.single()
            col1, col2, col3 = st.columns(3)
            col1.metric("噬菌体", stats["phage_count"])
            col2.metric("菌株", stats["host_count"])
            col3.metric("互作", stats["interaction_count"])
        
        st.markdown("裂解谱最广的噬菌体（Top5）")
        with driver.session() as session:
            result = session.run("""
                MATCH (phi:PhageHostInteraction)
                WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                WITH phi.phage_id AS phage_id, count(phi) AS host_count
                RETURN phage_id, host_count
                ORDER BY host_count DESC
                LIMIT 5
            """)
            for record in result:
                st.write(f"   - {record['phage_id']}: {record['host_count']} 个菌株")

    st.markdown("---")

    try:
        from config import Config
        if Config.DS_API_KEY and Config.DS_API_KEY != "your_api_key_here":
            st.caption("✅ DeepSeek API 已配置")
        else:
            st.caption("⚠️ DeepSeek API 未配置，LLM 功能不可用")
    except:
        st.caption("⚠️ 无法读取配置")

# ---------- 主界面：多标签页（已调整标题） ----------
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 菌株配型查询",
    "📊 批量菌株配型",
    "📦 证据包生成",
    "🔄 跨病例复用",
    "📈 聚类分析",
    "📝 知识策展"
])

# ================== 标签页 1：菌株配型查询（反向查询） ==================
with tab1:
    st.subheader("单个菌株配型查询")
    col1, col2 = st.columns([3, 1])
    with col1:
        host_input = st.text_input("输入菌株编号", value="B-KP136")
    with col2:
        limit = st.number_input("数量上限", min_value=1, max_value=100, value=20)
    
    if st.button("查询配型", type="primary"):
        with st.spinner("查询中..."):
            result = query_phages_for_host(host_input, limit)
        if result:
            # 显示详细列表
            df = pd.DataFrame(result)
            st.success(f"✅ 找到 {len(result)} 个候选噬菌体")
            st.dataframe(df[["phage_name", "evidence_level", "evidence_ref"]],
                         use_container_width=True)
            st.markdown("**详细列表**")
            for p in result:
                st.markdown(f"- **{p['phage_name']}** (L{p['evidence_level']}) 来源: {p['evidence_ref']}")
            
            # ===== 五级配型总结 =====
            st.markdown("---")
            st.subheader("🧬 配型总结（不依赖测序数据）")
            
            l5_count = sum(1 for p in result if p['evidence_level'] == 'L5')
            l4_count = sum(1 for p in result if p['evidence_level'] == 'L4')
            l3_count = sum(1 for p in result if p['evidence_level'] == 'L3')
            l2_count = sum(1 for p in result if p['evidence_level'] == 'L2')
            l1_count = sum(1 for p in result if p['evidence_level'] == 'L1')
            total = len(result)
            
            conclusion = f"✅ 不依赖测序数据，仅凭菌株编号即可推荐 {total} 个候选噬菌体"
            if l2_count > 0:
                conclusion += f"（其中 {l2_count} 个来自裂解谱证据 L2）"
            elif l3_count > 0:
                conclusion += f"（其中 {l3_count} 个来自临床验证 L3）"
            st.success(conclusion)
            
            # 五级证据等级展示
            col_a, col_b, col_c, col_d, col_e = st.columns(5)
            col_a.metric("L1 文献", l1_count)
            col_b.metric("L2 体外", l2_count)
            col_c.metric("L3 临床", l3_count)
            col_d.metric("L4 多中心", l4_count)
            col_e.metric("L5 闭环", l5_count)
            
            # 各等级详细列表（仅显示有数据的等级）
            if l5_count > 0:
                l5_phages = [p['phage_name'] for p in result if p['evidence_level'] == 'L5']
                st.write(f"**L5 组织学习闭环噬菌体**：{', '.join(l5_phages)}")
            if l4_count > 0:
                l4_phages = [p['phage_name'] for p in result if p['evidence_level'] == 'L4']
                st.write(f"**L4 多中心临床验证噬菌体**：{', '.join(l4_phages)}")
            if l3_count > 0:
                l3_phages = [p['phage_name'] for p in result if p['evidence_level'] == 'L3']
                st.write(f"**L3 单例临床验证噬菌体**：{', '.join(l3_phages)}")
            if l2_count > 0:
                l2_phages = [p['phage_name'] for p in result if p['evidence_level'] == 'L2']
                st.write(f"**L2 体外验证噬菌体**：{', '.join(l2_phages[:5])}{' ...' if len(l2_phages) > 5 else ''}")
            if l1_count > 0:
                l1_phages = [p['phage_name'] for p in result if p['evidence_level'] == 'L1']
                st.write(f"**L1 文献报道噬菌体**：{', '.join(l1_phages[:5])}{' ...' if len(l1_phages) > 5 else ''}")
            
            st.caption("💡 证据等级说明：L1(文献) → L2(体外) → L3(单例临床) → L4(多中心) → L5(组织学习闭环)")
            
            # ===== 底层检索函数展示（折叠） =====
            with st.expander("🔬 查看原始检索结果（find_matching_phages / find_similar_cases）"):
                col_ret1, col_ret2 = st.columns(2)
                with col_ret1:
                    st.markdown("**匹配噬菌体（E. coli MDR）**")
                    with st.spinner("查询中..."):
                        phages_raw = find_matching_phages(driver, "Escherichia coli", "MDR", limit=10)
                    st.write(f"找到 {len(phages_raw)} 个匹配噬菌体：")
                    for p in phages_raw[:5]:
                        st.write(f"   - {p['name']} (L{p['evidence_level']}) 概率: {p['infection_probability']}")
                    if len(phages_raw) > 5:
                        st.write(f"   ... 还有 {len(phages_raw)-5} 个")
                
                with col_ret2:
                    st.markdown("**相似病例（E. coli UTI）**")
                    with st.spinner("查询中..."):
                        cases_raw = find_similar_cases(driver, "Escherichia coli", "UTI", limit=5)
                    st.write(f"找到 {len(cases_raw)} 个相似病例：")
                    for c in cases_raw:
                        st.write(f"   - {c['case_id']}: 结局 {c['clinical_outcome']}, 噬菌体: {c.get('phages_used', [])}")
            
            # ===== 噬菌体宿主谱查询（反向查询） =====
            with st.expander("🔄 噬菌体宿主谱查询（反向查询）"):
                st.caption("输入噬菌体名称，查看它能裂解哪些宿主菌株")
                
                col_phage1, col_phage2 = st.columns([3, 1])
                with col_phage1:
                    phage_input = st.text_input("输入噬菌体名称（如 PKP014 或 PHAGE-PKP014）", value="PKP014")
                with col_phage2:
                    phage_limit = st.number_input("返回数量", min_value=1, max_value=200, value=20, key="phage_limit")
                
                if st.button("🔍 查询噬菌体宿主谱", key="query_phage_hosts"):
                    with st.spinner("查询中..."):
                        from src.validator import query_hosts_for_phage
                        result = query_hosts_for_phage(phage_input, limit=phage_limit)
                    
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
                        
                        # 统计各证据等级数量
                        level_counts = df_hosts['evidence_level'].value_counts().to_dict()
                        st.write("**📊 证据等级分布**")
                        cols = st.columns(len(level_counts))
                        for idx, (level, count) in enumerate(level_counts.items()):
                            cols[idx].metric(f"L{level}", count)
                    else:
                        st.warning(f"未找到噬菌体 **{phage_input}** 的宿主记录，请确认名称是否正确")
        else:
            st.warning("未找到匹配噬菌体")

# ================== 标签页 2：批量菌株配型 ==================
with tab2:
    st.subheader("批量菌株配型覆盖度")
    if st.button("运行随机 15 个菌株"):
        strains = random.sample([f"B-KP{i}" for i in range(1, 244)], 15)
        with st.spinner("验证中..."):
            df = batch_validate_hosts(strains)
        st.dataframe(df, use_container_width=True)
        st.metric("平均匹配数", f"{df['总匹配'].mean():.1f}")

# ================== 标签页 3：证据包生成 ==================
with tab3:
    st.subheader("生成 Evidence Package (LLM)")
    col1, col2 = st.columns(2)
    with col1:
        species = st.text_input("病原菌物种", value="Acinetobacter baumannii")
        resistance = st.text_input("耐药机制", value="Carbapenem-resistant")
    with col2:
        infection_type = st.text_input("感染类型", value="Pneumonia")
        use_llm = st.checkbox("使用 LLM (DeepSeek)", value=True)
    if st.button("生成证据包"):
        with st.spinner("生成中..."):
            if use_llm:
                result = build_evidence_package_from_db(species, resistance, infection_type)
                st.json(result)
            else:
                result = rule_based_evidence_package(species, resistance, infection_type)
                st.json(result)

# ================== 标签页 4：跨病例复用 ==================
with tab4:
    st.subheader("跨病例复用分析")
    col1, col2 = st.columns(2)
    with col1:
        case_a = st.text_input("病例 A ID", value="CASE-001")
    with col2:
        case_b = st.text_input("病例 B ID", value="CASE-003")
    if st.button("分析复用"):
        with st.spinner("分析中..."):
            result = analyze_cross_case_reuse_simple(case_a, case_b)
        st.json(result)

# ================== 标签页 5：聚类分析 ==================
with tab5:
    st.subheader("基于裂解谱的伪型别聚类推荐")
    st.info("💡 聚类基于数据库中已有的裂解谱互作数据")
    
    n_clusters = st.slider("聚类数", min_value=2, max_value=15, value=8)
    
    if st.button("运行聚类"):
        with st.spinner("聚类中..."):
            with driver.session() as session:
                result = session.run("""
                    MATCH (phi:PhageHostInteraction)
                    WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                    RETURN phi.phage_id AS phage,
                           split(phi.notes, ': ')[1] AS host,
                           1 AS value
                """)
                records = [dict(r) for r in result]
            
            if not records:
                st.warning("⚠️ 数据库中无裂解谱数据，请先导入数据")
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
                
                st.write(f"📊 共分为 **{len(clusters)}** 个簇")
                for label, strains in sorted(clusters.items()):
                    st.write(f"**簇 {label+1}**：{len(strains)} 个菌株，示例 {strains[:5]}")
                
                cluster_label = st.number_input(
                    "输入簇编号（从 1 开始）", 
                    min_value=1, 
                    max_value=len(clusters), 
                    value=1
                )
                
                if st.button("推荐该簇的噬菌体"):
                    target_label = cluster_label - 1
                    if target_label in clusters:
                        strains_in_cluster = clusters[target_label]
                        st.write(f"🔍 簇 {cluster_label} 包含 {len(strains_in_cluster)} 个菌株")
                        
                        with driver.session() as session:
                            result = session.run("""
                                MATCH (phi:PhageHostInteraction)<-[:HAS_INTERACTION]-(ph:Phage)
                                WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                                WITH ph, phi, $strains AS strains
                                WITH ph, phi, 
                                     REDUCE(s = 0, strain IN strains | 
                                         s + CASE WHEN phi.notes CONTAINS strain THEN 1 ELSE 0 END
                                     ) AS host_count
                                WHERE host_count >= $min_host_count
                                RETURN ph.name AS phage_name,
                                       ph.phage_id AS phage_id,
                                       phi.evidence_level AS evidence_level,
                                       host_count
                                ORDER BY host_count DESC
                                LIMIT 10
                            """, strains=strains_in_cluster, min_host_count=2)
                            phages = [dict(r) for r in result]
                        
                        if phages:
                            df = pd.DataFrame(phages)
                            st.dataframe(df[["phage_name", "host_count", "evidence_level"]], use_container_width=True)
                        else:
                            st.warning("该簇中无满足条件的噬菌体")
    
    # ===== 单个菌株型别级推荐 =====
    st.markdown("---")
    st.subheader("🔍 单个菌株型别级推荐")
    st.caption("输入菌株编号，系统自动定位所属簇，推荐该簇内覆盖多菌株的噬菌体")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        strain_input = st.text_input("输入菌株编号", value="B-KP11")
    with col2:
        min_host_count = st.number_input("最小覆盖菌株数", min_value=2, max_value=20, value=2)
    
    if st.button("🔍 针对该菌株进行型别级推荐", type="primary"):
        with st.spinner("分析中..."):
            with driver.session() as session:
                result = session.run("""
                    MATCH (phi:PhageHostInteraction)
                    WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                    RETURN phi.phage_id AS phage,
                           split(phi.notes, ': ')[1] AS host,
                           1 AS value
                """)
                records = [dict(r) for r in result]
            
            if not records:
                st.warning("⚠️ 数据库中无裂解谱数据，请先导入数据")
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
                
                strain_to_cluster = {host: label for host, label in zip(hosts, labels)}
                
                if strain_input not in strain_to_cluster:
                    st.warning(f"⚠️ 未找到菌株 {strain_input}，请检查编号是否正确")
                else:
                    target_label = strain_to_cluster[strain_input]
                    strains_in_cluster = [h for h, label in strain_to_cluster.items() if label == target_label]
                    
                    st.success(f"✅ 菌株 **{strain_input}** 属于簇 {target_label+1}（共 {len(strains_in_cluster)} 个菌株）")
                    st.write(f"同簇菌株示例：{strains_in_cluster[:10]}{'...' if len(strains_in_cluster) > 10 else ''}")
                    
                    with driver.session() as session:
                        result = session.run("""
                            MATCH (phi:PhageHostInteraction)<-[:HAS_INTERACTION]-(ph:Phage)
                            WHERE phi.evidence_ref CONTAINS '合作方裂解谱数据'
                            WITH ph, phi, $strains AS strains
                            WITH ph, phi, 
                                 REDUCE(s = 0, strain IN strains | 
                                     s + CASE WHEN phi.notes CONTAINS strain THEN 1 ELSE 0 END
                                 ) AS host_count
                            WHERE host_count >= $min_host_count
                            RETURN ph.name AS phage_name,
                                   ph.phage_id AS phage_id,
                                   phi.evidence_level AS evidence_level,
                                   host_count
                            ORDER BY host_count DESC
                            LIMIT 10
                        """, strains=strains_in_cluster, min_host_count=min_host_count)
                        recommended_phages = [dict(r) for r in result]
                    
                    if recommended_phages:
                        st.subheader("💊 推荐噬菌体（该簇内至少覆盖 2 个菌株）")
                        df_rec = pd.DataFrame(recommended_phages)
                        st.dataframe(
                            df_rec[["phage_name", "host_count", "evidence_level"]],
                            column_config={
                                "phage_name": "噬菌体名称",
                                "host_count": "覆盖菌株数",
                                "evidence_level": "证据等级"
                            },
                            use_container_width=True
                        )
                        st.caption("💡 这些噬菌体在该菌株所属的伪型别（簇）中具有广谱裂解能力")
                    else:
                        st.warning(f"该簇中无噬菌体同时覆盖 {min_host_count} 个以上菌株")

# ================== 标签页 6：知识策展（五级完整支持） ==================
with tab6:
    st.subheader("📋 知识策展管理")
    st.caption("证据等级体系：L1(文献) → L2(体外) → L3(单例临床) → L4(多中心) → L5(组织学习闭环)")
    
    # ----- 步骤 1：查找可升级的互作记录 -----
    st.markdown("---")
    st.markdown("#### 🔍 步骤 1：查找可升级的互作记录")
    
    # 目标等级选择
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
                    MATCH (c:ClinicalCase)-[:TREATED_WITH]->(ph:Phage)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)
                    WHERE phi.evidence_level IN ['{source_levels_str}']
                    RETURN c.case_id AS case_id,
                           ph.phage_id AS phage_id,
                           ph.name AS phage_name,
                           phi.evidence_level AS evidence_level
                """)
                records = [dict(r) for r in result]
        
        if records:
            df = pd.DataFrame(records)
            st.dataframe(df, use_container_width=True)
            st.success(f"找到 {len(records)} 条 {', '.join(source_levels)} → {target_level_selector} 可升级记录")
        else:
            st.info(f"当前没有 {', '.join(source_levels)} → {target_level_selector} 可升级记录")
    
    # ----- 步骤 2：执行策展升级 -----
    st.markdown("---")
    st.markdown("#### ⚡ 步骤 2：执行策展升级")
    
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
    
    # 使用与步骤 1 相同的目标等级
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
    
    # ----- 步骤 3：验证升级结果 -----
    st.markdown("---")
    st.markdown("#### ✅ 步骤 3：验证升级结果")
    
    verify_case_id = st.text_input("验证病例 ID", value="CASE-002")
    verify_phage_id = st.text_input("验证噬菌体 ID（可选，留空则查所有）", value="PHAGE-013")
    
    if st.button("验证升级结果"):
        with st.spinner("验证中..."):
            with driver.session() as session:
                if verify_phage_id.strip():
                    result = session.run("""
                        MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage {phage_id: $phage_id})
                        MATCH (ph)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)
                        RETURN ph.name AS phage_name,
                               phi.evidence_level AS evidence_level,
                               phi.evidence_ref AS evidence_ref
                    """, case_id=verify_case_id, phage_id=verify_phage_id)
                else:
                    result = session.run("""
                        MATCH (c:ClinicalCase {case_id: $case_id})-[r:TREATED_WITH]->(ph:Phage)
                        MATCH (ph)-[:HAS_INTERACTION]->(phi:PhageHostInteraction)
                        RETURN ph.name AS phage_name,
                               ph.phage_id AS phage_id,
                               phi.evidence_level AS evidence_level,
                               phi.evidence_ref AS evidence_ref
                    """, case_id=verify_case_id)
                
                records = [dict(r) for r in result]
        
        if records:
            st.success(f"✅ 找到 {len(records)} 条互作记录")
            df = pd.DataFrame(records)
            st.dataframe(df, use_container_width=True)
            
            for r in records:
                if r['evidence_level'] in ['L3', 'L4', 'L5']:
                    st.success(f"✅ {r['phage_name']} 已升级至 {r['evidence_level']}，来源: {r['evidence_ref']}")
                else:
                    st.warning(f"⚠️ {r['phage_name']} 仍为 {r['evidence_level']}，尚未升级")
        else:
            st.warning("未找到该病例的互作记录")
    
    # ----- L3 证据查询（折叠） -----
    with st.expander("📊 查看所有 L3 临床验证证据"):
        with st.spinner("查询中..."):
            records = query_l3_evidence()
        if records:
            df = pd.DataFrame(records)
            st.dataframe(df, use_container_width=True)
        else:
            st.info("暂无 L3 临床验证记录")

# ---------- 底部信息 ----------
st.markdown("---")
st.caption("⚠️ 演示版本，所有操作基于本地 Neo4j 数据库，LLM 调用需配置 DeepSeek API Key")