# _legacy_streamlit/app.py
import os
import sys

# ---------- 自动查找项目根目录 ----------
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = CURRENT_DIR
while PROJECT_ROOT != os.path.dirname(PROJECT_ROOT):
    if os.path.exists(os.path.join(PROJECT_ROOT, 'config.py')) and \
       os.path.exists(os.path.join(PROJECT_ROOT, 'pages')):
        break
    PROJECT_ROOT = os.path.dirname(PROJECT_ROOT)

# 把项目根目录加入 sys.path，以便导入 config、src、scripts 等
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

BASE_DIR = PROJECT_ROOT

# ---------- 现在可以正常导入了 ----------
import streamlit as st
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

# ★ 新增：监控源相关
from scripts.monitor_runner import add_global_source, _list_global_sources_raw

# ---------- 页面设置 ----------
st.set_page_config(page_title="噬菌体智能平台", page_icon="", layout="wide")


# ---------- 缓存数据库连接 ----------
@st.cache_resource
def get_db():
    return get_driver()


# ---------- 连接数据库 ----------
try:
    driver = get_db()
    with driver.session() as session:
        session.run("RETURN 1")
except Exception as e:
    st.error(f"⚠️ 无法连接 Neo4j 数据库，请检查 config.py 配置。错误: {str(e)}")
    st.stop()


# ---------- 定义页面路由（使用绝对路径）----------
pg = st.navigation(
    [
        st.Page(os.path.join(BASE_DIR, "_legacy_streamlit", "home.py"), title="首页", icon=":material/dashboard:", default=True),
        st.Page(os.path.join(BASE_DIR, "_legacy_streamlit", "phage.py"), title="噬菌体配型", icon=":material/science:"),
        st.Page(os.path.join(BASE_DIR, "_legacy_streamlit", "ci.py"), title="CI竞争情报", icon=":material/analytics:"),
    ]
)


# ============================================================
# 侧边栏（全局）
# ============================================================
with st.sidebar:
    st.markdown(
        """
        <div style="
            font-size: 1.8rem; font-weight: 700; color: #0068c9;
            padding: 0.5rem 0 0.2rem 0; letter-spacing: -0.5px;
            border-bottom: 2px solid #e6e9ef; margin-bottom: 0.8rem;
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

            status.update(label="创建约束、索引...")
            create_schema(driver)
            create_ontology_modules(driver)
            create_controlled_vocabularies(driver)
            st.write("✅ 约束、索引已创建")

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

            # ============================================================
            # ★ 新增：添加默认监控源
            # ============================================================
            status.update(label="添加默认监控源...")
            DEFAULT_SOURCES = [
                {
                    "url": (
                        "https://weixin.sogou.com/weixin?type=2&s_from=input"
                        "&query=创噬纪CreatiPhage&ie=utf8&_sug_=n&_sug_type_="
                    ),
                    "type": "sogou_wechat",
                    "label": "创噬纪 CreatiPhage",
                },
            ]

            # 先读取已有监控源，做幂等去重
            try:
                existing_urls = {
                    (g.get("url") or "").strip()
                    for g in _list_global_sources_raw(driver)
                }
            except Exception:
                existing_urls = set()

            added_src, skipped_src = 0, 0
            for src in DEFAULT_SOURCES:
                if src["url"] in existing_urls:
                    skipped_src += 1
                    st.write(f"⏭️ 监控源已存在，跳过：{src['label']}")
                    continue
                try:
                    add_global_source(src["url"], src["type"], src["label"])
                    added_src += 1
                    st.write(f"✅ 已添加监控源：{src['label']}")
                except Exception as e:
                    st.write(f"⚠️ 监控源 '{src['label']}' 添加失败：{e}")

            st.write(f"✅ 监控源添加完成（新增 {added_src}，跳过 {skipped_src}）")

            status.update(label="全部完成！", state="complete")

        st.success("🎉 所有数据已重新导入！")
        st.rerun()

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