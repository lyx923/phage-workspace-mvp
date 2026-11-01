# make_docx.py
import os
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

BLUE = (0x1B, 0x6C, 0xA8)

def f(run, name="微软雅黑", size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    if color: run.font.color.rgb = RGBColor(*color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts")) or OxmlElement("w:rFonts")
    if rFonts.getparent() is None: rPr.append(rFonts)
    for k in ("w:eastAsia", "w:ascii", "w:hAnsi"): rFonts.set(qn(k), name)

def h(doc, text, level=1):
    p = doc.add_heading(level=level); r = p.add_run(text)
    sizes = {0: 22, 1: 16, 2: 13.5, 3: 12}
    f(r, size=sizes.get(level, 12), bold=True,
      color=BLUE if level <= 2 else (0x1E, 0x29, 0x3B))
    return p

def p(doc, text, size=10.5, bold=False, align=None, color=None):
    par = doc.add_paragraph()
    if align == "center": par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    f(par.add_run(text), size=size, bold=bold, color=color)
    par.paragraph_format.space_after = Pt(6)
    return par

def b(doc, text, level=0):
    par = doc.add_paragraph(style="List Bullet" if level == 0 else "List Bullet 2")
    f(par.add_run(text), size=10.5)
    par.paragraph_format.space_after = Pt(3)
    return par

def code(doc, text):
    par = doc.add_paragraph()
    f(par.add_run(text), name="Consolas", size=9)
    par.paragraph_format.left_indent = Cm(0.5)
    par.paragraph_format.space_after = Pt(6)
    pPr = par._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), "F4F7FA")
    pPr.append(shd)

def tbl(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    for i, hd in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ""
        f(c.paragraphs[0].add_run(hd), size=10, bold=True, color=(0xFF, 0xFF, 0xFF))
        tcPr = c._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:fill"), "1B6CA8")
        tcPr.append(shd)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            f(cells[i].paragraphs[0].add_run(str(v)), size=9.5)
    if widths:
        for i, w in enumerate(widths):
            for r in t.rows: r.cells[i].width = Cm(w)
    doc.add_paragraph()
    return t

def build(out_path):
    doc = Document()
    doc.styles["Normal"].font.name = "微软雅黑"
    doc.styles["Normal"].font.size = Pt(10.5)
    doc.styles["Normal"].element.rPr.rFonts.set(qn("w:eastAsia"), "微软雅黑")
    for sec in doc.sections:
        sec.top_margin = sec.bottom_margin = Cm(2.0)
        sec.left_margin = sec.right_margin = Cm(2.2)

    # ===== 标题 =====
    h(doc, "Phage Intelligence Workspace - MVP v0.8.0-EXP", 0)
    p(doc, "噬菌体精准治疗 + 竞争情报 + 工程化噬菌体情报\n—— 三域一体的 Ontology 驱动决策智能系统", size=12, bold=True, align="center", color=BLUE)

    # ===== 一、项目简介 =====
    h(doc, "一、项目简介", 1)
    p(doc, "Phage Intelligence Workspace 是一个基于知识图谱和大语言模型的企业级 Ontology 驱动决策智能平台。平台覆盖三个相互连接的领域：")
    b(doc, "Scientific Domain：噬菌体-宿主互作、裂解实验、临床病例、证据包")
    b(doc, "Competitive Intelligence (CI) Domain：竞争对手、研发项目、情报事件、专利、临床试验")
    b(doc, "Engineering Intelligence Domain：工程化噬菌体构建体、工程策略、技术主张、实验结果")
    p(doc, "共享 Foundation 层（SourceArtifact / Pathogen / Organization / Review / AuditEvent / OntologyModule），并通过 Decision & Learning Layer 将外部情报连接成可追溯、可审核、可学习的组织知识系统。")
    p(doc, "当前版本为 v0.8.0-EXP，已完成实验集成验证并补齐了基线自动化测试。")

    h(doc, "1.1 核心验证目标", 2)
    tbl(doc, ["目标", "说明", "状态"], [
        ["V1", "Ontology 能否承载真实临床数据？", "✅ 16 例病例，必填字段填充率 100%"],
        ["V2", "历史病例知识能否被复用？", "✅ 跨病例复用验证通过"],
        ["V3", "学习闭环是否可演示？", "✅ 完整链路已跑通"],
        ["CI-V1", "竞争对手情报能否统一映射？", "✅ 22 组织 / 15 项目 / 22 事件"],
        ["CI-V2", "工程化噬菌体策略能否标准化？", "✅ 5 策略 / 10 构建体"],
        ["CI-V3", "跨域决策支持能否闭环？", "✅ 归因链 2 条完整链路"],
    ], widths=[2.5, 7.0, 6.5])

    h(doc, "1.2 核心能力", 2)
    p(doc, "三域知识图谱", bold=True)
    b(doc, "科学域：噬菌体、宿主菌株、裂解实验、临床病例、黄金规则")
    b(doc, "CI 域：组织、研发项目、情报事件、专利族、临床试验、竞争评估")
    b(doc, "工程情报域：工程策略、构建体、技术主张、技术结果、技术评估")
    p(doc, "Ontology 驱动（Palantir-style）", bold=True)
    b(doc, "事实层 / 分析层 / 决策层严格分层")
    b(doc, "所有事实对象 100% 关联 SourceArtifact")
    b(doc, "所有状态变更 100% 写入 AuditEvent")
    b(doc, "所有关键判断须经 Review 审核")
    p(doc, "双引擎推荐", bold=True)
    b(doc, "规则引擎：确定性逻辑，0 成本，0 幻觉")
    b(doc, "LLM 引擎：DeepSeek 仅负责文本组织，不产生未检索事实")
    p(doc, "知识策展闭环", bold=True)
    b(doc, "病例结局录入 → 自动创建 EvidenceUpgradeProposal")
    b(doc, "专家人工审核（Review） → approved / rejected / needs_revision")
    b(doc, "执行升级 → LysisAssay 证据等级从 L1/L2 升级至 L3")
    p(doc, "跨病例复用检测", bold=True)
    b(doc, "自动识别相似病例，推荐复用历史经验")
    b(doc, "创建 KnowledgeReuseEvent，需专家确认后才生效")
    p(doc, "归因链（Learning Engine）", bold=True)
    p(doc, "SourceArtifact → IntelligenceEvent → IntelligenceProduct → Review → DecisionRecord → IntelligenceUseEvent")

    # ===== 二、快速开始 =====
    doc.add_page_break()
    h(doc, "二、快速开始", 1)
    h(doc, "2.1 环境要求", 2)
    tbl(doc, ["组件", "版本要求"], [
        ["Python", "3.11+"],
        ["Neo4j", "5.x（Community Edition）"],
        ["Redis", "7.x（可选，用于监控缓存）"],
        ["内存", "≥ 8GB"],
    ], widths=[4.0, 8.0])

    h(doc, "2.2 克隆与安装", 2)
    code(doc, "git clone https://github.com/lyx923/phage-workspace-mvp.git\ncd phage-workspace-mvp\npip install -r requirements.txt")

    h(doc, "2.3 启动 Neo4j 与 Redis", 2)
    code(doc,
        "docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \\\n"
        "  -e NEO4J_AUTH=neo4j/your-password neo4j:5.26\n\n"
        "docker run -d --name redis -p 6379:6379 redis:7-alpine")

    h(doc, "2.4 配置环境变量", 2)
    p(doc, "复制项目根目录的 .env.example 为 .env，并按实际情况填写。注意：DeepSeek 的变量名以 DS_ 开头，Redis 连接使用 REDIS_HOST 和 REDIS_PORT。")
    code(doc, "cp .env.example .env")

    h(doc, "2.5 初始化数据与验收测试", 2)
    code(doc,
        "# 初始化沙箱数据\n"
        "python scripts/setup_all_stage2.py\n\n"
        "# 运行基础断言测试（确保代码环境正常）\n"
        "python -m pytest tests/test_v08_acceptance.py -v")

    h(doc, "2.6 启动前端", 2)
    code(doc, "python app.py")
    p(doc, "默认前端运行在 http://localhost:8501。Dash 默认端口为 8050，本仓库 app.py 固定 8501，如需改端口请同步修改 config.py 中的 PORT。")

    # ===== 三、项目结构 =====
    doc.add_page_break()
    h(doc, "三、项目结构", 1)
    p(doc, "下方目录树反映当前仓库真实状态：")
    code(doc,
"""phage-workspace-mvp/
├── app.py                      # Dash 应用入口
├── auth.py                     # 认证模块（verify_user / session）
├── config.py                   # 环境变量读取
├── requirements.txt            # 主依赖
├── README.md
├── components/
│   ├── navbar.py
│   ├── sidebar.py
│   ├── confirm_dialog.py
│   └── kpi_card.py
├── data_access/
│   ├── queries.py              # 只读 Cypher 集中层
│   ├── mutations.py            # 写入层（走 src/ 服务）
│   └── audit.py                # AuditEvent 统一写入
├── pages/
│   ├── dashboard.py
│   ├── ai_assistant.py
│   ├── knowledge_graph.py
│   ├── login.py
│   ├── admin/                  # 包含 schema.py, data_import.py, experiment_batch.py 等
│   ├── ci/                     # 包含 events.py, programs.py, strategies.py 等
│   └── scientific/             # 包含 enzyme_gene.py, biofilm_assay.py, lysis_assay.py 等
├── scripts/
│   ├── generate_ontology_docs.py # R-02 生成本体文档
│   ├── verify_requirements.py    # R-05 验证依赖版本
│   ├── separate_legacy_deps.py   # R-08 归档依赖分离
│   └── monitor_runner.py         # 情报抓取脚本
├── src/                          # 后端服务层（包含 foundation/, scientific/, ci/ 等）
├── tests/                        # 验收脚本
│   ├── test_v08_acceptance.py    # R-07 断言起点
│   └── acceptance_stage2.py      # 原验收脚本（改造中）
├── docs/
│   ├── ontology_schema.md        # 自动生成的本体文档
│   └── planned_nodes.md          # 规划中 / 已废弃节点与关系说明
└── _legacy_streamlit/          # 已归档，不参与主应用运行""")

    # ===== 四、核心设计原则 =====
    doc.add_page_break()
    h(doc, "四、核心设计原则", 1)
    tbl(doc, ["原则", "落地方式"], [
        ["P1: AI 从真实业务开始", "使用真实历史病例（已去标识化），不使用合成数据"],
        ["P2: AI 学习经过验证的知识", "所有输入数据均经微生物实验室验证"],
        ["P3: AI 放大不替代", "领域专家对输出做最终评审，LLM 仅做文本组织"],
        ["P4: Evidence-driven", "输出标注证据来源和等级（L1-L5），每条推荐可追溯"],
        ["P5: 学习是终点", "知识策展闭环：新病例 → 新知识 → 更好推荐"],
        ["P6: 人工审核不伪造", "系统从不自动批准升级或确认复用"],
        ["P7: 事实/分析/决策分层", "不允许 AI 幻觉污染事实层"],
        ["P8: 归因链纯净", "单 Brief 的归因链中事件必须属于同组织"],
        ["P9: 时间语义", "所有对象带 valid_from，Brief 必带 as_of_date"],
        ["P10: 来源可信度 ≠ 内容正确性", "来源评级与事实置信度分开记录"],
    ], widths=[6.0, 9.0])

    # ===== 五、技术栈 =====
    h(doc, "五、技术栈", 1)
    tbl(doc, ["层", "技术"], [
        ["数据存储", "Neo4j 5.x + Redis 7.x"],
        ["LLM", "DeepSeek Chat（OpenAI 兼容 SDK）"],
        ["后端", "Python 3.11+"],
        ["前端（当前）", "Dash 2.17+ + dash-bootstrap-components + dash-ag-grid + dash-cytoscape + Plotly"],
        ["前端（归档）", "Streamlit（已归档至 _legacy_streamlit/，不参与主应用运行）"],
        ["数据处理", "pandas / numpy / scikit-learn"],
        ["Notebook", "Jupyter"],
    ], widths=[3.5, 11.5])

    # ===== 六、版本历史 =====
    h(doc, "六、版本历史", 1)
    tbl(doc, ["版本", "日期", "主要变更"], [
        ["v0.1", "—", "早期 MVP 初版"],
        ["v0.2", "—", "沙箱版 / CI 增补 PRD"],
        ["v0.4", "—", "Enterprise Ontology Foundation 设计"],
        ["v0.5", "2026-08-24", "CI Demo 修复；Learning Engine 闭环目标"],
        ["v0.6", "2026-08-31", "修复 v0.5 验收遗留问题；AuditEvent/OntologyModule 强制完成；消除归因链语义污染"],
        ["v0.7", "2026-09-19", "实验集成验证迭代（工程化噬菌体、酶基因、生物膜、实验批次）"],
        ["v0.8", "2026-10-14", "基线修复（依赖澄清、本体文档生成、pytest 断言、Schema 清理）"],
    ], widths=[2.0, 3.0, 10.0])

    # ===== 尾注 =====
    p(doc, "")
    p(doc, "Phage Intelligence Workspace — 让上一个病例的经验，成为下一个病例的起点；让外部情报，成为内部决策的依据。",
      size=11, bold=True, align="center", color=BLUE)

    doc.save(out_path)
    print(f"✅ 已成功生成：{out_path}")


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(root, "")
    os.makedirs(out_dir, exist_ok=True)
    build(os.path.join(out_dir, "Phage_Intelligence_Workspace_v0.8_README.docx"))