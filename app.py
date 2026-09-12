# app.py
import streamlit as st
import os
from config import get_driver

# 数据导入相关
from src.scientific.import_service import (
    load_phages_from_lysis_csv_simple,
    import_golden_rules,
    clear_database,
    load_cases_from_csv,
    load_phages_from_csv,
    load_patients_from_csv,
    load_organizations_from_csv,
    load_programs_from_csv,
    load_events_from_csv,
)
from src.foundation.schema import (
    create_schema,
    create_ontology_modules,
    create_controlled_vocabularies,
)

# ---------- 获取项目根目录 ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体智能平台", page_icon="", layout="wide")

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

# ---------- 定义页面路由 ----------
pg = st.navigation(
    [
        st.Page("pages/home.py", title="首页", icon=":material/dashboard:", default=True),
        st.Page("pages/phage.py", title="噬菌体配型", icon=":material/science:"),
        st.Page("pages/ci.py", title="CI竞争情报", icon=":material/analytics:"),
    ]
)

# ============================================================
# 侧边栏（全局）
# ============================================================
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

    # ---- 清空并重新导入全部数据 ----
    if st.button("🔄 清空并重新导入全部数据", type="secondary", width="stretch"):
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
            result = load_phages_from_lysis_csv_simple(
                os.path.join(BASE_DIR, "data", "肺克数据脱敏.csv")
            )
            st.write(f"✅ 裂解谱导入完成，新增 {result['positive_interactions']} 条记录")

            status.update(label="导入黄金配型知识库...")
            import_golden_rules()
            st.write("✅ 黄金配型知识库导入完成")

            status.update(label="导入组织...")
            load_organizations_from_csv(
                driver, os.path.join(BASE_DIR, "data", "ci_organizations.csv")
            )
            st.write("✅ 组织导入完成")

            status.update(label="导入项目...")
            load_programs_from_csv(
                driver, os.path.join(BASE_DIR, "data", "ci_programs.csv")
            )
            st.write("✅ 项目导入完成")

            status.update(label="导入事件...")
            load_events_from_csv(
                driver, os.path.join(BASE_DIR, "data", "ci_events.csv")
            )
            st.write("✅ 事件导入完成")

            status.update(label="全部完成！", state="complete")

        st.success("🎉 所有数据已重新导入！")
        st.rerun()

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

    # ---- 系统状态 ----
    st.subheader("⚙️ 系统状态")
    try:
        from config import Config
        if Config.DS_API_KEY and Config.DS_API_KEY != "your_api_key_here":
            st.caption("✅ DeepSeek API 已配置")
        else:
            st.caption("⚠️ DeepSeek API 未配置，LLM 功能不可用")
    except Exception:
        st.caption("⚠️ 无法读取配置")

    st.caption("演示版本，基于本地 Neo4j 数据库")

pg.run()