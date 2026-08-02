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
from src.validator import (
    query_phages_for_host,
    batch_validate_hosts,
    query_l3_evidence,
    query_hosts_for_phage,
)
from src.package_builder import (
    build_evidence_package_from_db,
    rule_based_evidence_package
)
from src.retriever import analyze_cross_case_reuse_simple, find_matching_phages, find_similar_cases
from src.curation import curate_case_by_id
from src.data_loader import (
    load_phages_from_lysis_csv_simple,
    import_golden_rules
)

# ---------- 获取项目根目录 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体配型系统", layout="wide")
st.title("噬菌体配型智能助手")
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
    
    if st.button("🔄 清空并重新导入全部数据", type="secondary"):
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
            load_phages_from_csv(os.path.join(BASE_DIR, "data", "phage_interactions.csv"))
            st.write("✅ 噬菌体互作导入完成")

            status.update(label="导入临床病例...")
            load_cases_from_csv(os.path.join(BASE_DIR, "data", "cases.csv"))
            st.write("✅ 病例导入完成")

            status.update(label="导入裂解谱数据...")
            result = load_phages_from_lysis_csv_simple(os.path.join(BASE_DIR, "data", "肺克数据脱敏.csv"))
            st.write(f"✅ 裂解谱导入完成，新增 {result['positive_interactions']} 条记录")

            status.update(label="导入黄金配型知识库...")
            result = import_golden_rules()
            st.write(f"✅ 黄金配型知识库导入完成")

            status.update(label="全部完成！", state="complete")
        st.success("🎉 所有数据已重新导入！")
        st.rerun()
    
    st.markdown("---")
    
    # ===== 数据管理区域 =====
    st.subheader("📄 数据管理")
    
    # ===== 裂解谱最广的噬菌体（折叠） =====
    with st.expander("🔬 裂解谱最广的噬菌体（Top 5）"):
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
    
    # ===== V1 验证（折叠，无按钮，自动显示） =====
    with st.expander("📄 V1 数据完整性验证"):
        @st.cache_data(ttl=600)  # 缓存 10 分钟
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
                st.success("🎉 V1 验证通过！填充率 ≥ 90%")
            else:
                st.warning(f"⚠️ V1 验证未通过（{v1_data['rate']:.1f}% < 90%）")
    
    st.markdown("---")
    
    # ===== 系统状态 =====
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
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 菌株配型查询",
    "📊 批量菌株配型",
    "📦 证据包生成",
    "🔄 跨病例复用",
    "📈 聚类分析",
    "📝 知识策展"
])

# ================== 标签页 1：菌株配型查询 ==================
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
    
    # ===== 匹配噬菌体查询（独立折叠） =====
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
    
    # ===== 相似病例查询（独立折叠） =====
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
    
    # ===== 噬菌体宿主谱查询（反向查询） =====
    with st.expander("🔄 噬菌体宿主谱查询（反向查询）"):
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
                    cols[idx].metric(f"L{level}", count)
            else:
                st.warning(f"未找到噬菌体 **{phage_input}** 的宿主记录，请确认名称是否正确")

# ================== 标签页 2：批量菌株配型 ==================
with tab2:
    st.subheader("批量菌株配型覆盖度")
    if st.button("运行随机 15 个菌株"):
        strains = random.sample([f"B-KP{i}" for i in range(1, 244)], 15)
        with st.spinner("验证中..."):
            df = batch_validate_hosts(strains)
            st.session_state.batch_result = df
    if "batch_result" in st.session_state:
        st.dataframe(st.session_state.batch_result, use_container_width=True)
        st.metric("平均匹配数", f"{st.session_state.batch_result['总匹配'].mean():.1f}")

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
                st.session_state.ep_result = result
            else:
                result = rule_based_evidence_package(species, resistance, infection_type)
                st.session_state.ep_result = result
    if "ep_result" in st.session_state:
        st.json(st.session_state.ep_result)

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
            st.session_state.reuse_result = analyze_cross_case_reuse_simple(case_a, case_b)
    if "reuse_result" in st.session_state:
        st.json(st.session_state.reuse_result)

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