# src/foundation/schema.py
from config import get_driver
from neo4j import GraphDatabase
import hashlib
import json

def create_schema(driver):
    """创建所有约束和索引（幂等，支持重复执行）"""
    with driver.session() as session:
        
        # 1. Pathogen 唯一约束
        session.run("CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.taxonomy_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (p:Pathogen) ON (p.aliases);")
        # 2. ClinicalCase 唯一约束
        session.run("CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:ClinicalCase) REQUIRE c.case_id IS UNIQUE;")
        # 3. Phage 唯一约束
        session.run("CREATE CONSTRAINT phage_id_unique IF NOT EXISTS FOR (p:Phage) REQUIRE p.phage_id IS UNIQUE;")
        # 4. PhageHostInteraction 唯一约束
        session.run("CREATE CONSTRAINT interaction_id_unique IF NOT EXISTS FOR (i:PhageHostInteraction) REQUIRE i.interaction_id IS UNIQUE;")

        # -------- 第二阶段新增对象（科学子网） --------
        # HostStrain：以 host_strain_id 为主键，strain_label 加索引加速查询
        session.run("CREATE CONSTRAINT host_strain_id_unique IF NOT EXISTS FOR (h:HostStrain) REQUIRE h.host_strain_id IS UNIQUE;")
        session.run("CREATE INDEX host_strain_label_idx IF NOT EXISTS FOR (h:HostStrain) ON (h.strain_label);")

        # LysisAssay：assay_id 唯一
        session.run("CREATE CONSTRAINT assay_id_unique IF NOT EXISTS FOR (a:LysisAssay) REQUIRE a.assay_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.assay_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.qc_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.validation_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.evidence_level);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.source_domain);")

        # EvidenceSource：evidence_id 唯一（保留兼容，但不再使用）
        session.run("CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (e:EvidenceSource) REQUIRE e.evidence_id IS UNIQUE;")
        
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:SourceArtifact) REQUIRE s.source_id IS UNIQUE")
        session.run("CREATE INDEX IF NOT EXISTS FOR (s:SourceArtifact) ON (s.source_domain)")
        session.run("CREATE INDEX IF NOT EXISTS FOR (s:SourceArtifact) ON (s.source_type)")

        # -------- 第二阶段新增对象（市场情报子网） --------
        session.run("CREATE CONSTRAINT org_id_unique IF NOT EXISTS FOR (o:Organization) REQUIRE o.organization_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT program_id_unique IF NOT EXISTS FOR (d:DevelopmentProgram) REQUIRE d.program_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (e:IntelligenceEvent) REQUIRE e.event_id IS UNIQUE;")

        # （可选）为市场对象添加常用查询索引
        session.run("CREATE INDEX org_name_idx IF NOT EXISTS FOR (o:Organization) ON (o.canonical_name);")
        session.run("CREATE INDEX program_name_idx IF NOT EXISTS FOR (d:DevelopmentProgram) ON (d.canonical_name);")
        session.run("CREATE INDEX event_type_idx IF NOT EXISTS FOR (e:IntelligenceEvent) ON (e.event_type);")
        session.run("CREATE INDEX event_dedup_key_idx IF NOT EXISTS FOR (e:IntelligenceEvent) ON (e.deduplication_key);")

        # 证据升级提案
        session.run("CREATE CONSTRAINT proposal_id_unique IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) REQUIRE p.proposal_id IS UNIQUE;")
        session.run("CREATE INDEX proposal_status_idx IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) ON (p.status);")
        
        # -------- AuditEvent 约束与索引 --------
        session.run("CREATE CONSTRAINT audit_event_id_unique IF NOT EXISTS FOR (ae:AuditEvent) REQUIRE ae.audit_event_id IS UNIQUE;")
        session.run("CREATE INDEX audit_event_correlation_idx IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.correlation_id);")
        session.run("CREATE INDEX audit_event_domain_idx IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.domain);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.reason);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (ae:AuditEvent) ON (ae.actor_id);")
        
        # -------- Review 约束与索引 --------
        session.run("CREATE CONSTRAINT review_id_unique IF NOT EXISTS FOR (r:Review) REQUIRE r.review_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.review_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.target_object_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.target_object_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (r:Review) ON (r.decision);")

        # -------- 患者 --------
        session.run("CREATE CONSTRAINT patient_id_unique IF NOT EXISTS FOR (p:Patient) REQUIRE p.patient_id IS UNIQUE;")

        # -------- ScientificEvidencePackage 约束与索引 --------
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:ScientificEvidencePackage) REQUIRE p.package_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (p:ScientificEvidencePackage) ON (p.status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (p:ScientificEvidencePackage) ON (p.review_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (p:ScientificEvidencePackage) ON (p.package_type);")
        
        # -------- ControlledVocabulary 约束与索引 --------
        session.run("CREATE CONSTRAINT vocabulary_id_unique IF NOT EXISTS FOR (v:ControlledVocabulary) REQUIRE v.vocabulary_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT term_id_unique IF NOT EXISTS FOR (t:ControlledTerm) REQUIRE t.term_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (t:ControlledTerm) ON (t.code);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (t:ControlledTerm) ON (t.vocabulary_id);")

        # -------- 新增 CI 对象（工程情报、决策支持） --------
        session.run("CREATE CONSTRAINT indication_id_unique IF NOT EXISTS FOR (ci:ClinicalIndication) REQUIRE ci.indication_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT patent_family_id_unique IF NOT EXISTS FOR (pf:PatentFamily) REQUIRE pf.patent_family_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT comp_assessment_id_unique IF NOT EXISTS FOR (ca:CompetitorAssessment) REQUIRE ca.assessment_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT construct_id_unique IF NOT EXISTS FOR (ec:EngineeredPhageConstruct) REQUIRE ec.construct_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT strategy_id_unique IF NOT EXISTS FOR (es:EngineeringStrategy) REQUIRE es.strategy_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT modification_id_unique IF NOT EXISTS FOR (em:EngineeringModification) REQUIRE em.modification_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (tc:TechnicalClaim) REQUIRE tc.claim_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT result_id_unique IF NOT EXISTS FOR (tr:TechnicalResult) REQUIRE tr.result_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT tech_assessment_id_unique IF NOT EXISTS FOR (ta:TechnologyAssessment) REQUIRE ta.technology_assessment_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT question_id_unique IF NOT EXISTS FOR (iq:IntelligenceQuestion) REQUIRE iq.question_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT brief_id_unique IF NOT EXISTS FOR (db:DecisionBrief) REQUIRE db.brief_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT decision_record_id_unique IF NOT EXISTS FOR (dr:DecisionRecord) REQUIRE dr.decision_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT decision_option_id_unique IF NOT EXISTS FOR (do:DecisionOption) REQUIRE do.option_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT watchlist_item_id_unique IF NOT EXISTS FOR (wi:WatchlistItem) REQUIRE wi.watchlist_item_id IS UNIQUE;")

        # -------- 新增索引（提升查询性能） --------
        session.run("CREATE INDEX indication_name_idx IF NOT EXISTS FOR (ci:ClinicalIndication) ON (ci.name);")
        session.run("CREATE INDEX patent_family_title_idx IF NOT EXISTS FOR (pf:PatentFamily) ON (pf.title);")
        session.run("CREATE INDEX construct_name_idx IF NOT EXISTS FOR (ec:EngineeredPhageConstruct) ON (ec.public_name);")
        session.run("CREATE INDEX strategy_type_idx IF NOT EXISTS FOR (es:EngineeringStrategy) ON (es.strategy_type);")
        session.run("CREATE INDEX claim_type_idx IF NOT EXISTS FOR (tc:TechnicalClaim) ON (tc.claim_type);")
        session.run("CREATE INDEX result_type_idx IF NOT EXISTS FOR (tr:TechnicalResult) ON (tr.result_type);")
        session.run("CREATE INDEX brief_type_idx IF NOT EXISTS FOR (db:DecisionBrief) ON (db.brief_type);")
        session.run("CREATE INDEX decision_type_idx IF NOT EXISTS FOR (dr:DecisionRecord) ON (dr.decision_type);")
        session.run("CREATE INDEX comp_assessment_subject_idx IF NOT EXISTS FOR (ca:CompetitorAssessment) ON (ca.subject_type);")
        session.run("CREATE INDEX tech_assessment_subject_idx IF NOT EXISTS FOR (ta:TechnologyAssessment) ON (ta.subject_type);")

         # -------- 工程化噬菌体情报关系类型索引 --------
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:CLAIMS_ABOUT]-() ON (r.claim_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:RESULT_FOR]-() ON (r.result_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:REPORTED_IN]-() ON (r.source_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:IMPLEMENTS]-() ON (r.strategy_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:SUPPORTED_BY]-() ON (r.source_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:USES_CONSTRUCT]-() ON (r.program_id);")
        session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:ASSESSES]-() ON (r.subject_type);")

        print("✅ 所有数据库约束与索引创建完成（含科学子网 + 市场情报子网 + 工程情报 + 决策支持）")


def create_ontology_modules(driver):
    """创建 OntologyModule 节点，记录模块版本（含 schema_hash）"""
    modules = [
        {"id": "FOUNDATION-CORE", "name": "foundation-core", "domain": "foundation", "version": "1.0.0"},
        {"id": "FOUNDATION-PROVENANCE", "name": "foundation-provenance", "domain": "foundation", "version": "1.0.0"},
        {"id": "FOUNDATION-GOVERNANCE", "name": "foundation-governance", "domain": "foundation", "version": "1.0.0"},
        {"id": "SCIENTIFIC-CORE", "name": "scientific-core", "domain": "scientific", "version": "1.0.0"},
        {"id": "SCIENTIFIC-EVIDENCE", "name": "scientific-evidence", "domain": "scientific", "version": "1.0.0"},
        {"id": "CI-PLACEHOLDER", "name": "ci-placeholder", "domain": "ci", "version": "0.1.0", "status": "draft"},
        {"id": "CONSUMER-CONTRACT", "name": "consumer-contract", "domain": "foundation", "version": "1.0.0"},
    ]
    
    # 为每个模块计算 schema_hash（基于模块 ID + 版本）
    with driver.session() as session:
        for mod in modules:
            # 计算简单的 schema_hash
            schema_content = f"{mod['id']}:{mod['version']}:{mod['domain']}"
            schema_hash = hashlib.sha256(schema_content.encode()).hexdigest()[:16]
            
            session.run("""
                MERGE (m:OntologyModule {module_id: $id})
                SET m.module_name = $name,
                    m.domain = $domain,
                    m.version = $version,
                    m.status = COALESCE($status, 'active'),
                    m.owner = 'platform_team',
                    m.schema_hash = $schema_hash,
                    m.activated_at = datetime(),
                    m.created_at = datetime()
            """, id=mod["id"], name=mod["name"], domain=mod["domain"],
                version=mod["version"], status=mod.get("status", "active"),
                schema_hash=schema_hash)
    print("✅ OntologyModule 版本记录已创建")


def create_controlled_vocabularies(driver):
    """创建受控词表（ControlledVocabulary + ControlledTerm）"""
    vocabularies = [
        {
            "id": "VOC-REVIEW-DECISION",
            "name": "review_decision",
            "domain": "foundation",
            "version": "1.0.0",
            "terms": [
                {"code": "approved", "display": "已批准", "description": "审核通过"},
                {"code": "rejected", "display": "已拒绝", "description": "审核拒绝"},
                {"code": "needs_revision", "display": "需修改", "description": "需补充数据后重新审核"},
                {"code": "confirmed", "display": "已确认", "description": "知识复用确认"},
                {"code": "unverified", "display": "未验证", "description": "待审核或未通过验证"}
            ]
        },
        {
            "id": "VOC-REVIEW-TYPE",
            "name": "review_type",
            "domain": "foundation",
            "version": "1.0.0",
            "terms": [
                {"code": "assay_qc", "display": "实验QC审核", "description": "LysisAssay 质量审核"},
                {"code": "evidence_upgrade", "display": "证据升级审核", "description": "证据等级升级提案审核"},
                {"code": "scientific_package_review", "display": "证据包审核", "description": "ScientificEvidencePackage 审核"},
                {"code": "knowledge_reuse_review", "display": "知识复用审核", "description": "KnowledgeReuseEvent 审核"},
                {"code": "ci_fact_review", "display": "情报事实审核", "description": "CI 事实审核（预留）"},
                {"code": "technical_intelligence_review", "display": "技术情报审核", "description": "技术情报审核（预留）"},
                {"code": "intelligence_product_review", "display": "情报产品审核", "description": "情报产品审核（预留）"}
            ]
        },
        {
            "id": "VOC-ASSAY-QC",
            "name": "assay_qc_status",
            "domain": "scientific",
            "version": "1.0.0",
            "terms": [
                {"code": "pending", "display": "待审核", "description": "QC 待审核，不得自动升级"},
                {"code": "passed", "display": "已通过", "description": "QC 已通过，可参与升级"},
                {"code": "failed", "display": "未通过", "description": "QC 未通过，不可升级"}
            ]
        },
        {
            "id": "VOC-PACKAGE-STATUS",
            "name": "scientific_package_status",
            "domain": "scientific",
            "version": "1.0.0",
            "terms": [
                {"code": "draft", "display": "草稿", "description": "初始生成状态"},
                {"code": "pending_review", "display": "待审核", "description": "已提交审核"},
                {"code": "approved", "display": "已批准", "description": "审核通过"},
                {"code": "rejected", "display": "已拒绝", "description": "审核拒绝"},
                {"code": "superseded", "display": "已替代", "description": "被新版本替代"}
            ]
        },
        {
            "id": "VOC-KNOWLEDGE-REUSE",
            "name": "knowledge_reuse_status",
            "domain": "scientific",
            "version": "1.0.0",
            "terms": [
                {"code": "detected", "display": "已检测", "description": "系统自动检测到复用"},
                {"code": "pending_review", "display": "待审核", "description": "等待人工确认"},
                {"code": "confirmed", "display": "已确认", "description": "人工确认复用有效"},
                {"code": "rejected", "display": "已拒绝", "description": "人工拒绝复用"}
            ]
        },
        {
            "id": "VOC-SOURCE-TYPE",
            "name": "source_type",
            "domain": "foundation",
            "version": "1.0.0",
            "terms": [
                {"code": "literature", "display": "文献", "description": "PubMed/期刊文献"},
                {"code": "clinical_case", "display": "临床病例", "description": "临床病例报告"},
                {"code": "lysis_assay_file", "display": "裂解谱数据文件", "description": "体外裂解谱数据"},
                {"code": "clinical_trial", "display": "临床试验", "description": "临床试验数据"},
                {"code": "internal_experiment", "display": "内部实验", "description": "内部实验室数据"}
            ]
        },
        {
            "id": "VOC-SOURCE-ACCESS",
            "name": "source_access_level",
            "domain": "foundation",
            "version": "1.0.0",
            "terms": [
                {"code": "public", "display": "公开", "description": "可对外公开"},
                {"code": "internal", "display": "内部", "description": "仅内部使用"},
                {"code": "restricted", "display": "受限", "description": "需特殊授权"}
            ]
        },
        # -------- 新增 CI 受控词表 --------
        {
            "id": "VOC-ENGINEERING-STRATEGY",
            "name": "engineering_strategy",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "host_range_expansion", "display": "宿主范围扩展", "description": "扩展宿主范围"},
                {"code": "tail_fiber_engineering", "display": "尾纤维工程", "description": "改造尾纤维或受体结合蛋白"},
                {"code": "receptor_binding_engineering", "display": "受体结合工程", "description": "改变受体结合特异性"},
                {"code": "lysis_enhancement", "display": "裂解能力增强", "description": "增强裂解活性或裂解模块优化"},
                {"code": "lysogeny_removal", "display": "溶原性去除", "description": "移除溶原性基因"},
                {"code": "biofilm_disruption", "display": "生物膜破坏", "description": "生物膜相关工程"},
                {"code": "payload_delivery", "display": "递送载荷", "description": "递送抗耐药或抗毒力载荷"},
                {"code": "anti_resistance_payload", "display": "抗耐药载荷", "description": "递送抗耐药基因的载荷"},
                {"code": "anti_virulence_payload", "display": "抗毒力载荷", "description": "递送抗毒力基因的载荷"},
                {"code": "immune_modulation", "display": "免疫调节", "description": "调节宿主免疫应答"},
                {"code": "phage_display", "display": "噬菌体展示", "description": "展示外源蛋白"},
                {"code": "genome_minimization", "display": "基因组精简", "description": "去除冗余基因"},
                {"code": "manufacturability_optimization", "display": "可制造性优化", "description": "提高生产稳定性"},
                {"code": "stability_optimization", "display": "稳定性优化", "description": "提高噬菌体稳定性"},
                {"code": "delivery_optimization", "display": "递送优化", "description": "优化递送方式"},
                {"code": "other", "display": "其他", "description": "未分类策略"}
            ]
        },
        {
            "id": "VOC-EVENT-TYPE",
            "name": "intelligence_event_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "pipeline_update", "display": "管线更新", "description": "研发管线状态变更"},
                {"code": "clinical_trial_update", "display": "临床试验更新", "description": "临床试验进展或结果"},
                {"code": "regulatory_update", "display": "监管事件", "description": "监管审批、法规变化"},
                {"code": "publication", "display": "论文发表", "description": "学术论文或会议发布"},
                {"code": "patent_event", "display": "专利事件", "description": "专利申请、授权或争议"},
                {"code": "partnership", "display": "合作事件", "description": "合作、许可或联盟"},
                {"code": "funding", "display": "融资事件", "description": "融资、投资或补贴"},
                {"code": "acquisition", "display": "并购事件", "description": "收购、合并或剥离"},
                {"code": "leadership_change", "display": "领导层变动", "description": "高管任命或离职"},
                {"code": "manufacturing_update", "display": "制造更新", "description": "生产或供应链变化"},
                {"code": "commercial_launch", "display": "商业上市", "description": "产品上市或商业化"},
                {"code": "program_discontinuation", "display": "项目终止", "description": "研发项目终止或暂停"}
            ]
        },
        {
            "id": "VOC-PROGRAM-STAGE",
            "name": "development_stage",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "discovery", "display": "发现阶段", "description": "早期研究"},
                {"code": "preclinical", "display": "临床前", "description": "临床前研究"},
                {"code": "phase_1", "display": "I期临床", "description": "I期临床试验"},
                {"code": "phase_2", "display": "II期临床", "description": "II期临床试验"},
                {"code": "phase_3", "display": "III期临床", "description": "III期临床试验"},
                {"code": "phase_4", "display": "IV期临床", "description": "上市后研究"},
                {"code": "approved", "display": "已批准", "description": "已获监管批准"},
                {"code": "discontinued", "display": "已终止", "description": "项目已终止"}
            ]
        },
        {
            "id": "VOC-PROGRAM-TYPE",
            "name": "program_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "therapeutic", "display": "治疗性", "description": "治疗产品"},
                {"code": "diagnostic", "display": "诊断性", "description": "诊断产品"},
                {"code": "platform", "display": "平台技术", "description": "技术平台"},
                {"code": "research", "display": "研究工具", "description": "研究用试剂或工具"}
            ]
        },
        {
            "id": "VOC-MODALITY",
            "name": "modality",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "natural_phage", "display": "天然噬菌体", "description": "天然分离噬菌体"},
                {"code": "engineered_phage", "display": "工程化噬菌体", "description": "经改造的噬菌体"},
                {"code": "cocktail", "display": "鸡尾酒", "description": "噬菌体混合物"}
            ]
        },
        {
            "id": "VOC-ORGANIZATION-TYPE",
            "name": "organization_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "biotech", "display": "生物技术公司", "description": "专注生物技术"},
                {"code": "pharma", "display": "制药公司", "description": "大型制药企业"},
                {"code": "academic", "display": "学术机构", "description": "大学或研究所"},
                {"code": "regulator", "display": "监管机构", "description": "政府监管机构"},
                {"code": "hospital", "display": "医院", "description": "医疗机构"},
                {"code": "investor", "display": "投资机构", "description": "风险投资或基金"},
                {"code": "partner", "display": "合作伙伴", "description": "合作方（通用）"}
            ]
        },
        {
            "id": "VOC-CLAIM-TYPE",
            "name": "technical_claim_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "efficacy", "display": "有效性", "description": "治疗效果主张"},
                {"code": "host_range", "display": "宿主范围", "description": "宿主范围扩展主张"},
                {"code": "safety", "display": "安全性", "description": "安全性主张"},
                {"code": "manufacturability", "display": "可制造性", "description": "生产可行性主张"},
                {"code": "mechanism", "display": "作用机制", "description": "机制相关主张"}
            ]
        },
        {
            "id": "VOC-RESULT-TYPE",
            "name": "technical_result_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "host_range", "display": "宿主范围", "description": "宿主范围实验结果"},
                {"code": "lysis", "display": "裂解活性", "description": "裂解实验结果"},
                {"code": "biofilm", "display": "生物膜", "description": "生物膜抑制或清除结果"},
                {"code": "safety", "display": "安全性", "description": "安全性评估结果"},
                {"code": "in_vivo", "display": "体内实验", "description": "动物模型或人体结果"},
                {"code": "computational", "display": "计算预测", "description": "计算机模拟或预测结果"}
            ]
        },
        {
            "id": "VOC-ASSESSMENT-TYPE",
            "name": "competitor_assessment_type",
            "domain": "ci",
            "version": "1.0.0",
            "terms": [
                {"code": "threat", "display": "威胁", "description": "竞争威胁评估"},
                {"code": "opportunity", "display": "机会", "description": "市场机会评估"},
                {"code": "capability", "display": "能力", "description": "竞争对手能力评估"},
                {"code": "uncertainty", "display": "不确定性", "description": "不确定性评估"}
            ]
        }
    ]
    
    with driver.session() as session:
        for vocab in vocabularies:
            # 创建或更新 ControlledVocabulary
            session.run("""
                MERGE (v:ControlledVocabulary {vocabulary_id: $id})
                SET v.vocabulary_name = $name,
                    v.domain = $domain,
                    v.version = $version,
                    v.status = 'active',
                    v.owner = 'platform_team',
                    v.created_at = datetime()
            """, id=vocab["id"], name=vocab["name"], domain=vocab["domain"], version=vocab["version"])
            
            # 创建 ControlledTerm 节点并建立 BELONGS_TO 关系
            for term in vocab["terms"]:
                term_id = f"TERM-{term['code'].upper()[:8]}"
                session.run("""
                    MATCH (v:ControlledVocabulary {vocabulary_id: $vocab_id})
                    MERGE (t:ControlledTerm {term_id: $term_id})
                    SET t.code = $code,
                        t.display_name = $display,
                        t.description = $description,
                        t.status = 'active',
                        t.created_at = datetime()
                    MERGE (t)-[:BELONGS_TO]->(v)
                """, vocab_id=vocab["id"], term_id=term_id, code=term["code"],
                    display=term["display"], description=term["description"])
    
    print("✅ ControlledVocabulary 受控词表已创建（含 CI 词表）")