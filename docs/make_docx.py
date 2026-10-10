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
    h(doc, "Phage Intelligence Workspace - MVP", 0)
    p(doc, "噬菌体精准治疗 + 竞争情报 + 工程化噬菌体情报\n—— 三域一体的 Ontology 驱动决策智能系统",
      size=12, bold=True, align="center", color=BLUE)

    # ===== 一、项目简介 =====
    h(doc, "一、项目简介", 1)
    p(doc, "Phage Intelligence Workspace 是一个基于知识图谱和大语言模型的企业级 Ontology 驱动决策智能平台。平台覆盖三个相互连接的领域：")
    b(doc, "Scientific Domain：噬菌体-宿主互作、裂解实验、临床病例、证据包")
    b(doc, "Competitive Intelligence (CI) Domain：竞争对手、研发项目、情报事件、专利、临床试验")
    b(doc, "Engineering Intelligence Domain：工程化噬菌体构建体、工程策略、技术主张、实验结果")
    p(doc, "共享 Foundation 层（SourceArtifact / Pathogen / Organization / Review / AuditEvent / OntologyModule），并通过 Decision & Learning Layer 将外部情报连接成可追溯、可审核、可学习的组织知识系统。")
    p(doc, "当前版本为 v0.6（Foundation 稳定版），Stage2 增补 PRD 验收 53/53 全部通过，Learning Engine 归因链闭环已在 Notebook 中验证。")

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
    for title, items in [
        ("三域知识图谱", [
            "科学域：噬菌体、宿主菌株、裂解实验、临床病例、黄金规则",
            "CI 域：组织、研发项目、情报事件、专利族、临床试验、竞争评估",
            "工程情报域：工程策略、构建体、技术主张、技术结果、技术评估"]),
        ("Ontology 驱动（Palantir-style）", [
            "事实层 / 分析层 / 决策层严格分层",
            "所有事实对象 100% 关联 SourceArtifact",
            "所有状态变更 100% 写入 AuditEvent",
            "所有关键判断须经 Review 审核"]),
        ("双引擎推荐", [
            "规则引擎：确定性逻辑，0 成本，0 幻觉",
            "LLM 引擎：DeepSeek 仅负责文本组织，不产生未检索事实"]),
        ("知识策展闭环", [
            "病例结局录入 → 自动创建 EvidenceUpgradeProposal",
            "专家人工审核（Review） → approved / rejected / needs_revision",
            "执行升级 → LysisAssay 证据等级从 L1/L2 升级至 L3"]),
        ("跨病例复用检测", [
            "自动识别相似病例，推荐复用历史经验",
            "创建 KnowledgeReuseEvent，需专家确认后才生效"]),
    ]:
        p(doc, title, bold=True)
        for it in items: b(doc, it)
    p(doc, "归因链（Learning Engine）", bold=True)
    code(doc, "SourceArtifact → IntelligenceEvent → IntelligenceProduct\n→ Review → DecisionRecord → IntelligenceUseEvent")

    # ===== 二、数据模型 =====
    doc.add_page_break()
    h(doc, "二、数据模型", 1)

    h(doc, "2.1 Foundation 层（跨域共享）", 2)
    tbl(doc, ["实体", "说明", "关键属性"], [
        ["Pathogen", "病原菌主数据", "pathogen_id, species, taxonomy_id, aliases"],
        ["Organization", "组织主数据", "organization_id, canonical_name, organization_type, headquarters_country"],
        ["SourceArtifact", "来源制品", "source_id, source_type, title, url, credibility_tier"],
        ["Review", "统一审核记录", "review_id, review_type, decision, reviewer_id"],
        ["AuditEvent", "不可变审计事件", "audit_id, action_type, object_type, object_id, actor_id, delta, timestamp"],
        ["OntologyModule", "本体模块版本", "module_id, module_name, version, schema_hash, status"],
        ["ControlledVocabulary / ControlledTerm", "受控词表", "状态、类型标准化"],
    ], widths=[4.5, 4.5, 7.0])

    h(doc, "2.2 Scientific Domain", 2)
    tbl(doc, ["实体", "说明", "关键属性"], [
        ["Phage", "噬菌体", "phage_id, name, family, receptor_target"],
        ["HostStrain", "宿主菌株（分离株）", "host_strain_id, strain_label"],
        ["LysisAssay", "裂解实验", "assay_id, result, result_value, evidence_level (L1-L5), qc_status"],
        ["ClinicalCase", "临床病例", "case_id, infection_type, phage_treatment, clinical_outcome"],
        ["Patient", "患者主数据", "patient_id, age_group, comorbidities"],
        ["ScientificKnowledgeRule", "黄金规则", "rule_id, strain_type, treatment, outcome, applicability"],
        ["EvidenceUpgradeProposal", "证据升级提案", "proposal_id, assay_id, current_level, proposed_level, status"],
        ["ScientificEvidencePackage", "持久化证据包", "package_id, query_context, summary, review_status"],
        ["KnowledgeReuseEvent", "知识复用事件", "reuse_event_id, source_object_id, status"],
    ], widths=[5.0, 4.0, 7.0])

    h(doc, "2.3 CI Domain", 2)
    tbl(doc, ["实体", "说明", "关键属性"], [
        ["DevelopmentProgram", "研发项目", "program_id, canonical_name, development_stage, program_status, modality"],
        ["IntelligenceEvent", "情报事件", "event_id, event_type, title, event_date, organization_id, deduplication_key"],
        ["IntelligenceSignal", "情报信号（审核前候选）", "signal_id, signal_type, confidence, review_status"],
        ["ClinicalIndication", "临床适应症", "indication_id, name, infection_site, pathogen_scope"],
        ["ClinicalTrial", "临床试验", "trial_id, nct_id, phase, status, indication, sponsor"],
        ["PatentFamily", "专利族", "patent_family_id, title, priority_date, legal_status, claim_scope_summary"],
        ["CompetitorAssessment", "竞争评估", "assessment_id, assessment_type, subject_type, impact_level, confidence"],
        ["ProductAsset", "产品资产", "asset_id, name, asset_type, status"],
    ], widths=[4.5, 4.5, 7.0])

    h(doc, "2.4 Engineering Intelligence Domain", 2)
    tbl(doc, ["实体", "说明", "关键属性"], [
        ["EngineeringStrategy", "工程策略", "strategy_id, strategy_type, description, evidence_maturity"],
        ["EngineeredPhageConstruct", "工程化构建体", "construct_id, public_name, construct_status, intended_effects"],
        ["EngineeringModification", "工程改造", "modification_id, modification_type, modification_summary"],
        ["DeliveryPayload", "递送载荷", "payload_id, payload_type, payload_description"],
        ["TechnicalClaim", "技术主张", "claim_id, claim_type, claim_text, claim_status, confidence"],
        ["TechnicalResult", "技术结果", "result_id, result_type, study_context, outcome_direction"],
        ["TechnologyAssessment", "技术评估", "technology_assessment_id, subject_type, evidence_maturity 等六维"],
    ], widths=[5.0, 4.0, 7.0])

    h(doc, "2.5 Decision & Learning Layer", 2)
    tbl(doc, ["实体", "说明", "关键属性"], [
        ["IntelligenceProduct", "情报产品（简报）", "brief_id, brief_type, title, citations, review_status"],
        ["DecisionBrief", "决策简报", "brief_id, brief_type, key_facts, assessments, generated_by"],
        ["IntelligenceQuestion", "情报问题", "question_id, question_text, question_type, priority"],
        ["DecisionOption", "决策选项", "option_id, option_type, option_summary, risk_level"],
        ["DecisionRecord", "决策记录", "decision_id, decision_type, decision_summary, decision_owner"],
        ["IntelligenceUseEvent", "情报使用记录", "use_event_id, product_id, consumer_type, use_purpose"],
        ["WatchlistItem", "关注项", "watchlist_item_id, target_type, target_id, priority"],
    ], widths=[4.5, 4.5, 7.0])

    h(doc, "2.6 证据等级体系", 2)
    tbl(doc, ["等级", "名称", "含义"], [
        ["L1", "PUBLISHED_LITERATURE", "公开文献报道"],
        ["L2", "IN_VITRO_VERIFIED", "体外实验验证"],
        ["L3", "CLINICAL_SINGLE_CASE", "单例临床验证"],
        ["L4", "CLINICAL_MULTI_CENTER", "多中心临床验证"],
        ["L5", "ORGANIZATIONAL_LEARNING", "组织学习闭环"],
        ["黄金规则", "ScientificKnowledgeRule", "独立于 L1-L5，基于临床验证规则，优先级最高"],
    ], widths=[3.0, 5.5, 7.5])

    h(doc, "2.7 核心关系", 2)
    for title, txt in [
        ("Scientific Domain",
         "(Phage)-[:USED_IN]->(LysisAssay)-[:TESTED_AGAINST]->(HostStrain)\n"
         "(HostStrain)-[:IS_STRAIN_OF]->(Pathogen)\n"
         "(ClinicalCase)-[:INVOLVES_PATHOGEN]->(Pathogen)\n"
         "(ClinicalCase)-[:TREATED_WITH]->(Phage)\n"
         "(ClinicalCase)-[:HAS_ISOLATE]->(HostStrain)\n"
         "(ClinicalCase)-[:BELONGS_TO_PATIENT]->(Patient)\n"
         "(Pathogen)-[:HAS_VALIDATED_RULE]->(ScientificKnowledgeRule)\n"
         "(ScientificKnowledgeRule)-[:RECOMMENDS_PHAGE]->(Phage)\n"
         "(LysisAssay)-[:DERIVED_FROM]->(SourceArtifact)\n"
         "(ScientificEvidencePackage)-[:USES_ASSAY]->(LysisAssay)\n"
         "(ScientificEvidencePackage)-[:REFERENCES_CASE]->(ClinicalCase)\n"
         "(ScientificEvidencePackage)-[:INCLUDES_CANDIDATE]->(Phage)\n"
         "(ScientificEvidencePackage)-[:CITES_SOURCE]->(SourceArtifact)\n"
         "(KnowledgeReuseEvent)-[:REUSES]->(LysisAssay)\n"
         "(KnowledgeReuseEvent)-[:SOURCE_CASE]->(ClinicalCase)\n"
         "(KnowledgeReuseEvent)-[:TARGETS_PACKAGE]->(ScientificEvidencePackage)"),
        ("CI Domain",
         "(Organization)-[:DEVELOPS]->(DevelopmentProgram)\n"
         "(DevelopmentProgram)-[:TARGETS_PATHOGEN]->(Pathogen)\n"
         "(DevelopmentProgram)-[:ADDRESSES]->(ClinicalIndication)\n"
         "(DevelopmentProgram)-[:HAS_TRIAL]->(ClinicalTrial)\n"
         "(DevelopmentProgram)-[:COVERED_BY]->(PatentFamily)\n"
         "(Organization)-[:OWNS_PATENT]->(PatentFamily)\n"
         "(Organization)-[:SPONSORS]->(ClinicalTrial)\n"
         "(Organization)-[:OWNS_ASSET]->(ProductAsset)\n"
         "(IntelligenceEvent)-[:INVOLVES]->(Organization)\n"
         "(IntelligenceEvent)-[:AFFECTS]->(DevelopmentProgram)\n"
         "(IntelligenceEvent)-[:HAS_SOURCE]->(SourceArtifact)\n"
         "(SourceArtifact)-[:GENERATED_SIGNAL]->(IntelligenceSignal)\n"
         "(Review)-[:REVIEWS]->(IntelligenceSignal)\n"
         "(IntelligenceSignal)-[:PROMOTED_TO]->(IntelligenceEvent)"),
        ("Engineering Intelligence Domain",
         "(DevelopmentProgram)-[:USES_STRATEGY]->(EngineeringStrategy)\n"
         "(DevelopmentProgram)-[:USES_CONSTRUCT]->(EngineeredPhageConstruct)\n"
         "(EngineeredPhageConstruct)-[:IMPLEMENTS]->(EngineeringStrategy)\n"
         "(EngineeredPhageConstruct)-[:TARGETS]->(Pathogen)\n"
         "(EngineeredPhageConstruct)-[:DEVELOPED_BY]->(Organization)\n"
         "(EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(DevelopmentProgram)\n"
         "(EngineeredPhageConstruct)-[:HAS_MODIFICATION]->(EngineeringModification)\n"
         "(EngineeredPhageConstruct)-[:CARRIES_PAYLOAD]->(DeliveryPayload)\n"
         "(EngineeredPhageConstruct)-[:REPORTED_IN]->(SourceArtifact)\n"
         "(TechnicalClaim)-[:CLAIMS_ABOUT]->(EngineeredPhageConstruct)\n"
         "(TechnicalClaim)-[:SUPPORTED_BY]->(SourceArtifact)\n"
         "(TechnicalClaim)-[:EVALUATED_BY]->(TechnologyAssessment)\n"
         "(TechnicalResult)-[:RESULT_FOR]->(EngineeredPhageConstruct)\n"
         "(TechnicalResult)-[:SUPPORTED_OR_CHALLENGES]->(TechnicalClaim)\n"
         "(TechnicalResult)-[:REPORTED_IN]->(SourceArtifact)"),
        ("Decision & Learning Layer",
         "(IntelligenceProduct)-[:COVERS]->(Organization)\n"
         "(DecisionBrief)-[:ANSWERS]->(IntelligenceQuestion)\n"
         "(DecisionBrief)-[:USES_EVENT]->(IntelligenceEvent)\n"
         "(DecisionBrief)-[:CITES]->(SourceArtifact)\n"
         "(DecisionBrief)-[:INCLUDES_ASSESSMENT]->(CompetitorAssessment)\n"
         "(DecisionRecord)-[:BASED_ON]->(DecisionBrief)\n"
         "(DecisionRecord)-[:BASED_ON]->(IntelligenceProduct)\n"
         "(DecisionRecord)-[:AFFECTS_INTERNAL_PROGRAM]->(DevelopmentProgram)\n"
         "(IntelligenceUseEvent)-[:CONSUMES]->(IntelligenceProduct)\n"
         "(IntelligenceUseEvent)-[:TRIGGERS]->(DecisionRecord)\n"
         "(DecisionOption)-[:OPTION_FOR]->(DecisionBrief)\n"
         "(WatchlistItem)-[:WATCHES]->(Organization | DevelopmentProgram)"),
    ]:
        p(doc, title, bold=True)
        code(doc, txt)

    # ===== 三、快速开始 =====
    doc.add_page_break()
    h(doc, "三、快速开始", 1)

    h(doc, "3.1 环境要求", 2)
    tbl(doc, ["组件", "版本要求"], [
        ["Python", "3.11+"],
        ["Neo4j", "5.x（Community Edition）"],
        ["Redis", "7.x（可选，用于监控缓存）"],
        ["内存", "≥ 8GB"],
    ], widths=[4.0, 8.0])

    h(doc, "3.2 克隆与安装", 2)
    code(doc, "git clone https://github.com/lyx923/phage-workspace-mvp.git\ncd phage-workspace-mvp\npip install -r requirements.txt")

    h(doc, "3.3 启动 Neo4j 与 Redis", 2)
    code(doc,
        "docker run -d --name neo4j -p 7474:7474 -p 7687:7687 \\\n"
        "  -e NEO4J_AUTH=neo4j/your-password neo4j:5.26\n\n"
        "docker run -d --name redis -p 6379:6379 redis:7-alpine")

    h(doc, "3.4 配置 .env", 2)
    code(doc,
        "NEO4J_URI=bolt://localhost:7687\n"
        "NEO4J_USER=neo4j\n"
        "NEO4J_PASSWORD=your-password\n"
        "DS_API_KEY=sk-your-deepseek-api-key\n"
        "DS_MODEL=deepseek-chat\n"
        "DS_TEMPERATURE=0.3\n"
        "DS_MAX_TOKENS=4096")

    h(doc, "3.5 一键数据准备 + 验收", 2)
    code(doc, "python scripts/setup_all_stage2.py\npython tests/acceptance_stage2.py\n# 预期输出：汇总：53/53 通过，0 失败")

    h(doc, "3.6 启动前端", 2)
    code(doc, "streamlit run app.py\n# 或：jupyter notebook")

    doc.add_page_break()

    # ===== 四、核心设计原则 =====
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
    ], widths=[5.0, 10.0])

    # ===== 五、技术栈 =====
    h(doc, "五、技术栈", 1)
    tbl(doc, ["层", "技术"], [
        ["数据存储", "Neo4j 5.x + Redis 7.x"],
        ["LLM", "DeepSeek Chat（OpenAI 兼容 SDK）"],
        ["后端", "Python 3.11+"],
        ["前端（当前）", "Streamlit + Plotly + pandas"],
        ["前端（规划）", "Dash + dash-bootstrap-components + dash-ag-grid + dash-cytoscape"],
        ["数据处理", "pandas / numpy / scikit-learn"],
        ["Notebook", "Jupyter"],
    ], widths=[4.0, 11.0])

    # ===== 六、版本历史 =====
    h(doc, "六、版本历史", 1)
    tbl(doc, ["版本", "日期", "主要变更"], [
        ["v0.1", "—", "早期 MVP 初版"],
        ["v0.2", "—", "沙箱版 / CI 增补 PRD"],
        ["v0.4", "—", "Enterprise Ontology Foundation 设计"],
        ["v0.5", "2026-08-24", "CI Demo 修复；Learning Engine 闭环目标"],
        ["v0.6", "2026-08-31", "修复 v0.5 验收遗留问题；AuditEvent/OntologyModule 强制完成；消除归因链语义污染"],
    ], widths=[2.0, 3.0, 10.0])

    # ===== 尾注 =====
    p(doc, "")
    p(doc, "Phage Intelligence Workspace — 让上一个病例的经验，成为下一个病例的起点；让外部情报，成为内部决策的依据。",
      size=11, bold=True, align="center", color=BLUE)

    doc.save(out_path)
    print(f"✅ 已生成：{out_path}")


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(root, "")
    os.makedirs(out_dir, exist_ok=True)
    build(os.path.join(out_dir, "Phage_Intelligence_Workspace.docx"))