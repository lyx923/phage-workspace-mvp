# src/foundation/schema.py
"""
Neo4j 数据库 schema 定义（约束 + 索引 + 受控词表 + 本体模块 + CI 信号链路契约）

本模块职责：
    - 声明 CI 域的信号链路契约（CI_SIGNAL_CHAIN）
    - 创建全部唯一约束与索引（create_schema）
    - 声明本体模块版本（create_ontology_modules）
    - 创建受控词表（create_controlled_vocabularies）
    - 幂等初始化（initialize_neo4j_schema）

设计要点：
    - 所有约束 / 索引使用 IF NOT EXISTS，可重复执行
    - Neo4j 不支持对关系类型建唯一约束，只支持关系属性索引（4.3+）
    - 受控词表与 PRD 中 VOC-XXX 一一对应
"""
from config import get_driver
from neo4j import GraphDatabase, Driver
import hashlib
import json


# =====================================================
# CI 信号链路契约（声明式，供文档 / 测试 / 治理使用）
# 注意：Neo4j 不支持对关系类型建唯一约束，
#       只支持对关系属性建索引（Neo4j 4.3+）。
# =====================================================

CI_SIGNAL_CHAIN = [
    # 1. 来源 → 信号
    {
        "from": "SourceArtifact",
        "rel": "GENERATED_SIGNAL",
        "to": "IntelligenceSignal",
        "cardinality": "1..N",
        "props": ["source_id"],
        "desc": "来源生成信号（一篇文章可抽取多条信号）",
    },
    # 2. 审核 → 信号
    {
        "from": "Review",
        "rel": "REVIEWS",
        "to": "IntelligenceSignal",
        "cardinality": "1..N",
        "props": ["target_object_id"],
        "desc": "审核作用于信号；决策驱动信号状态",
    },
    # 3. 信号 → 事件
    {
        "from": "IntelligenceSignal",
        "rel": "PROMOTED_TO",
        "to": "IntelligenceEvent",
        "cardinality": "0..1",
        "props": ["event_id"],
        "desc": "审核通过后信号晋升为正式情报事件",
    },
    # 4. 事件 → 组织（v0.6：统一关系名 CONCERNS → INVOLVES）
    {
        "from": "IntelligenceEvent",
        "rel": "INVOLVES",
        "to": "Organization",
        "cardinality": "1..N",
        "props": ["organization_id"],
        "desc": "事件涉及的组织（v0.6 统一关系名，取代旧 CONCERNS）",
    },
    # 5. 事件 → 项目
    {
        "from": "IntelligenceEvent",
        "rel": "AFFECTS",
        "to": "DevelopmentProgram",
        "cardinality": "0..N",
        "props": ["target_type"],
        "desc": "事件影响到的研发项目",
    },
    # 6. 事件 → 来源（v0.6：SourceArtifact，支持多来源合并 MCI-12）
    {
        "from": "IntelligenceEvent",
        "rel": "HAS_SOURCE",
        "to": "SourceArtifact",
        "cardinality": "1..N",
        "props": ["source_id"],
        "desc": "事件引用的 SourceArtifact（多来源合并通过多次 HAS_SOURCE 表示）",
    },
    # 7. 简报 → 组织
    {
        "from": "IntelligenceProduct",
        "rel": "COVERS",
        "to": "Organization",
        "cardinality": "1..N",
        "props": ["organization_id"],
        "desc": "竞争简报覆盖的组织",
    },
    # 8. DecisionBrief → IntelligenceQuestion（PRD 10.2）
    {
        "from": "DecisionBrief",
        "rel": "ANSWERS",
        "to": "IntelligenceQuestion",
        "cardinality": "1..1",
        "props": [],
        "desc": "决策简报回答的情报问题",
    },
    # 9. DecisionRecord → DecisionBrief（PRD 11.3）
    {
        "from": "DecisionRecord",
        "rel": "BASED_ON",
        "to": ["DecisionBrief", "IntelligenceProduct"],
        "cardinality": "1..1",
        "props": [],
        "desc": "决策基于的简报（v0.6 支持 DecisionBrief 和 IntelligenceProduct 两种）",
    },
]


def declare_ci_signal_chain(driver):
    """
    把 CI 链路契约写成一个 OntologyModule 节点，
    便于审计 / 前端读取 / 版本对比。
    """
    payload = json.dumps(CI_SIGNAL_CHAIN, ensure_ascii=False, sort_keys=True)
    schema_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    with driver.session() as session:
        session.run(
            """
            MERGE (m:OntologyModule {module_id: 'CI-SIGNAL-CHAIN'})
            SET m.module_name = 'ci-signal-chain',
                m.domain      = 'ci',
                m.version     = '0.6.0',
                m.status      = 'active',
                m.owner       = 'platform_team',
                m.schema_hash = $hash,
                m.contract    = $payload,
                m.created_at  = COALESCE(m.created_at, datetime()),
                m.activated_at = datetime()
            """,
            hash=schema_hash,
            payload=payload,
        )
    print(f"✅ CI-SIGNAL-CHAIN 契约已声明 (hash={schema_hash})")


def create_schema(driver):
    """
    创建所有约束和索引（幂等，支持重复执行）。

    分区：
        1. 科学子网：Pathogen / ClinicalCase / Phage / HostStrain / LysisAssay / SourceArtifact
        2. 市场情报子网：Organization / DevelopmentProgram / IntelligenceEvent
        3. 审计与审核：AuditEvent / Review
        4. 证据包与词表：ScientificEvidencePackage / ControlledVocabulary / ControlledTerm
        5. CI 域对象：ClinicalIndication / PatentFamily / CompetitorAssessment / 构建体 / 评估 / 决策
        6. P1 质量能力：Organization.legal_name / website_domain / credibility_score 等
        7. PRD 14.3 时间语义：valid_from / valid_to 索引
    """
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
        session.run("CREATE CONSTRAINT host_strain_id_unique IF NOT EXISTS FOR (h:HostStrain) REQUIRE h.host_strain_id IS UNIQUE;")
        session.run("CREATE INDEX host_strain_label_idx IF NOT EXISTS FOR (h:HostStrain) ON (h.strain_label);")

        session.run("CREATE CONSTRAINT assay_id_unique IF NOT EXISTS FOR (a:LysisAssay) REQUIRE a.assay_id IS UNIQUE;")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.assay_type);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.qc_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.validation_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.evidence_level);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (a:LysisAssay) ON (a.source_domain);")

        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:SourceArtifact) REQUIRE s.source_id IS UNIQUE")
        session.run("CREATE INDEX IF NOT EXISTS FOR (s:SourceArtifact) ON (s.source_domain)")
        session.run("CREATE INDEX IF NOT EXISTS FOR (s:SourceArtifact) ON (s.source_type)")

        # -------- 第二阶段新增对象（市场情报子网） --------
        session.run("CREATE CONSTRAINT org_id_unique IF NOT EXISTS FOR (o:Organization) REQUIRE o.organization_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT program_id_unique IF NOT EXISTS FOR (d:DevelopmentProgram) REQUIRE d.program_id IS UNIQUE;")
        session.run("CREATE CONSTRAINT event_id_unique IF NOT EXISTS FOR (e:IntelligenceEvent) REQUIRE e.event_id IS UNIQUE;")

        session.run("CREATE INDEX org_name_idx IF NOT EXISTS FOR (o:Organization) ON (o.canonical_name);")
        session.run("CREATE INDEX program_name_idx IF NOT EXISTS FOR (d:DevelopmentProgram) ON (d.canonical_name);")
        session.run("CREATE INDEX event_type_idx IF NOT EXISTS FOR (e:IntelligenceEvent) ON (e.event_type);")
        session.run("CREATE INDEX event_dedup_key_idx IF NOT EXISTS FOR (e:IntelligenceEvent) ON (e.deduplication_key);")

        session.run("CREATE CONSTRAINT proposal_id_unique IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) REQUIRE p.proposal_id IS UNIQUE;")
        session.run("CREATE INDEX proposal_status_idx IF NOT EXISTS FOR (p:EvidenceUpgradeProposal) ON (p.status);")

        # -------- AuditEvent 约束与索引 --------
        session.run("CREATE CONSTRAINT audit_id_unique IF NOT EXISTS FOR (ae:AuditEvent) REQUIRE ae.audit_id IS UNIQUE;")
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
        session.run("CREATE CONSTRAINT patent_family_id_unique IF NOT EXISTS FOR (pf:PatentFamily) REQUIRE pf.patent_family_id IS UNIQUE;")
        session.run("CREATE INDEX patent_family_title_idx IF NOT EXISTS FOR (pf:PatentFamily) ON (pf.title);")
        session.run("CREATE INDEX patent_family_legal_idx IF NOT EXISTS FOR (pf:PatentFamily) ON (pf.legal_status);")
        session.run("CREATE CONSTRAINT clinical_trial_id_unique IF NOT EXISTS FOR (ct:ClinicalTrial) REQUIRE ct.trial_id IS UNIQUE;")
        session.run("CREATE INDEX clinical_trial_nct_idx IF NOT EXISTS FOR (ct:ClinicalTrial) ON (ct.nct_id);")
        session.run("CREATE INDEX clinical_trial_phase_idx IF NOT EXISTS FOR (ct:ClinicalTrial) ON (ct.phase);")
        session.run("CREATE INDEX clinical_trial_status_idx IF NOT EXISTS FOR (ct:ClinicalTrial) ON (ct.status);")
        session.run("CREATE CONSTRAINT question_id_unique IF NOT EXISTS FOR (iq:IntelligenceQuestion) REQUIRE iq.question_id IS UNIQUE;")
        session.run("CREATE INDEX question_type_idx IF NOT EXISTS FOR (iq:IntelligenceQuestion) ON (iq.question_type);")
        session.run("CREATE INDEX question_status_idx IF NOT EXISTS FOR (iq:IntelligenceQuestion) ON (iq.status);")
        session.run("CREATE CONSTRAINT watchlist_item_id_unique IF NOT EXISTS FOR (wi:WatchlistItem) REQUIRE wi.watchlist_item_id IS UNIQUE;")
        session.run("CREATE INDEX watchlist_target_idx IF NOT EXISTS FOR (wi:WatchlistItem) ON (wi.target_type);")
        session.run("CREATE INDEX watchlist_status_idx IF NOT EXISTS FOR (wi:WatchlistItem) ON (wi.status);")
        session.run("CREATE INDEX watchlist_priority_idx IF NOT EXISTS FOR (wi:WatchlistItem) ON (wi.priority);")

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

        # -------- IntelligenceSignal 节点索引 --------
        session.run("CREATE CONSTRAINT intelligence_signal_id_unique IF NOT EXISTS FOR (s:IntelligenceSignal) REQUIRE s.signal_id IS UNIQUE;")
        session.run("CREATE INDEX intelligence_signal_type_idx IF NOT EXISTS FOR (s:IntelligenceSignal) ON (s.signal_type);")
        session.run("CREATE INDEX signal_review_status_idx IF NOT EXISTS FOR (s:IntelligenceSignal) ON (s.review_status);")
        session.run("CREATE INDEX signal_source_idx IF NOT EXISTS FOR (s:IntelligenceSignal) ON (s.source_artifact_id);")

        # -------- CI 链路关系属性索引（Neo4j 4.3+） --------
        try:
            session.run("CREATE INDEX rel_generated_signal_src_idx IF NOT EXISTS FOR ()-[r:GENERATED_SIGNAL]-() ON (r.source_id);")
            session.run("CREATE INDEX rel_reviews_target_idx IF NOT EXISTS FOR ()-[r:REVIEWS]-() ON (r.target_object_id);")
            session.run("CREATE INDEX rel_promoted_to_event_idx IF NOT EXISTS FOR ()-[r:PROMOTED_TO]-() ON (r.event_id);")
            session.run("CREATE INDEX rel_affects_target_idx IF NOT EXISTS FOR ()-[r:AFFECTS]-() ON (r.target_type);")
            session.run("CREATE INDEX rel_covers_org_idx IF NOT EXISTS FOR ()-[r:COVERS]-() ON (r.organization_id);")
        except Exception as _e:
            print(f"⚠️ CI 关系索引创建跳过（Neo4j 版本可能不支持）: {_e}")

        # ========================================================
        # ★ P1 质量能力：新增索引
        # ========================================================
        session.run("CREATE INDEX IF NOT EXISTS FOR (o:Organization) ON (o.legal_name);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (o:Organization) ON (o.website_domain);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (s:SourceArtifact) ON (s.credibility_score);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (pf:PatentFamily) ON (pf.claim_scope_summary);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (tc:TechnicalClaim) ON (tc.claim_text);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (tc:TechnicalClaim) ON (tc.claim_status);")
        session.run("CREATE INDEX IF NOT EXISTS FOR (tr:TechnicalResult) ON (tr.outcome_direction);")

        # -------- v0.7 新增约束 --------
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:EnzymeGene) REQUIRE e.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (b:ExperimentBatch) REQUIRE b.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (b:BiofilmAssay) REQUIRE b.id IS UNIQUE")
        session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:SchemaVersion) REQUIRE s.version IS UNIQUE")

        # P1 关系属性索引（Neo4j 4.3+）
        try:
            session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:OWNS_OR_CONTROLS]-() ON (r.relation_type);")
            session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:MAPS_TO]-() ON (r.similarity);")
            session.run("CREATE INDEX IF NOT EXISTS FOR ()-[r:CONTRADICTS]-() ON (r.conflict_type);")
        except Exception as _e:
            print(f"⚠️ P1 关系索引创建跳过（Neo4j 版本可能不支持）: {_e}")

        # ========================================================
        # ★ PRD 14.3 时间语义：valid_from / valid_to 索引
        # ========================================================
        for label in [
            "Organization", "DevelopmentProgram", "IntelligenceEvent",
            "EngineeringStrategy", "EngineeredPhageConstruct",
            "TechnicalClaim", "TechnicalResult", "PatentFamily",
            "ClinicalTrial", "IntelligenceProduct", "DecisionRecord",
            "TechnologyAssessment", "CompetitorAssessment",
        ]:
            session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.valid_from);")
            session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.valid_to);")

        print("✅ 所有数据库约束与索引创建完成（含科学子网 + 市场情报子网 + 工程情报 + 决策支持 + CI 信号链路 + P1 质量能力 + 时间语义）")

    # -------- 声明 CI 链路契约（独立 session） --------
    try:
        declare_ci_signal_chain(driver)
    except Exception as _e:
        print(f"⚠️ CI 链路契约声明失败: {_e}")


def create_ontology_modules(driver):
    """创建 OntologyModule 节点，记录模块版本（含 schema_hash）。"""
    modules = [
        {"id": "FOUNDATION-CORE", "name": "foundation-core", "domain": "foundation", "version": "1.0.0"},
        {"id": "FOUNDATION-PROVENANCE", "name": "foundation-provenance", "domain": "foundation", "version": "1.0.0"},
        {"id": "FOUNDATION-GOVERNANCE", "name": "foundation-governance", "domain": "foundation", "version": "1.0.0"},
        {"id": "SCIENTIFIC-CORE", "name": "scientific-core", "domain": "scientific", "version": "1.0.0"},
        {"id": "SCIENTIFIC-EVIDENCE", "name": "scientific-evidence", "domain": "scientific", "version": "1.0.0"},
        {"id": "CI-PLACEHOLDER", "name": "ci-placeholder", "domain": "ci", "version": "0.1.0", "status": "draft"},
        {"id": "CONSUMER-CONTRACT", "name": "consumer-contract", "domain": "foundation", "version": "1.0.0"},
    ]

    with driver.session() as session:
        for mod in modules:
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
    """
    创建受控词表（ControlledVocabulary + ControlledTerm）。

    词表清单（与 PRD VOC-XXX 一致）：
        VOC-REVIEW-DECISION / VOC-REVIEW-TYPE / VOC-ASSAY-QC / VOC-PACKAGE-STATUS
        VOC-KNOWLEDGE-REUSE / VOC-SOURCE-TYPE / VOC-SOURCE-ACCESS
        VOC-ENGINEERING-STRATEGY / VOC-EVENT-TYPE / VOC-PROGRAM-STAGE
        VOC-PROGRAM-TYPE / VOC-MODALITY / VOC-ORGANIZATION-TYPE
        VOC-CLAIM-TYPE / VOC-RESULT-TYPE / VOC-ASSESSMENT-TYPE
        VOC-PATENT-LEGAL-STATUS / VOC-TRIAL-PHASE / VOC-TRIAL-STATUS
        VOC-IQ-TYPE / VOC-WATCH-TARGET
        ★ P1 质量能力：VOC-ORG-RELATION / VOC-CONFLICT-TYPE / VOC-CREDIBILITY-TIER
        ★ PRD 14.3：VOC-TIME-SEMANTICS
    """
    vocabularies = [
        # ------- 基础审核词表 -------
        {
            "id": "VOC-REVIEW-DECISION", "name": "review_decision", "domain": "foundation", "version": "1.0.0",
            "terms": [
                {"code": "approved", "display": "已批准", "description": "审核通过"},
                {"code": "rejected", "display": "已拒绝", "description": "审核拒绝"},
                {"code": "needs_revision", "display": "需修改", "description": "需补充数据后重新审核"},
                {"code": "confirmed", "display": "已确认", "description": "知识复用确认"},
                {"code": "unverified", "display": "未验证", "description": "待审核或未通过验证"}
            ]
        },
        {
            "id": "VOC-REVIEW-TYPE", "name": "review_type", "domain": "foundation", "version": "1.0.0",
            "terms": [
                {"code": "assay_qc", "display": "实验QC审核", "description": "LysisAssay 质量审核"},
                {"code": "evidence_upgrade", "display": "证据升级审核", "description": "证据等级升级提案审核"},
                {"code": "scientific_package_review", "display": "证据包审核", "description": "ScientificEvidencePackage 审核"},
                {"code": "knowledge_reuse_review", "display": "知识复用审核", "description": "KnowledgeReuseEvent 审核"},
                {"code": "ci_fact_review", "display": "情报事实审核", "description": "CI 事实审核"},
                {"code": "technical_intelligence_review", "display": "技术情报审核", "description": "技术情报审核"},
                {"code": "intelligence_product_review", "display": "情报产品审核", "description": "情报产品审核"}
            ]
        },
        {
            "id": "VOC-ASSAY-QC", "name": "assay_qc_status", "domain": "scientific", "version": "1.0.0",
            "terms": [
                {"code": "pending", "display": "待审核", "description": "QC 待审核，不得自动升级"},
                {"code": "passed", "display": "已通过", "description": "QC 已通过，可参与升级"},
                {"code": "failed", "display": "未通过", "description": "QC 未通过，不可升级"}
            ]
        },
        {
            "id": "VOC-PACKAGE-STATUS", "name": "scientific_package_status", "domain": "scientific", "version": "1.0.0",
            "terms": [
                {"code": "draft", "display": "草稿", "description": "初始生成状态"},
                {"code": "pending_review", "display": "待审核", "description": "已提交审核"},
                {"code": "approved", "display": "已批准", "description": "审核通过"},
                {"code": "rejected", "display": "已拒绝", "description": "审核拒绝"},
                {"code": "superseded", "display": "已替代", "description": "被新版本替代"}
            ]
        },
        {
            "id": "VOC-KNOWLEDGE-REUSE", "name": "knowledge_reuse_status", "domain": "scientific", "version": "1.0.0",
            "terms": [
                {"code": "detected", "display": "已检测", "description": "系统自动检测到复用"},
                {"code": "pending_review", "display": "待审核", "description": "等待人工确认"},
                {"code": "confirmed", "display": "已确认", "description": "人工确认复用有效"},
                {"code": "rejected", "display": "已拒绝", "description": "人工拒绝复用"}
            ]
        },
        {
            "id": "VOC-SOURCE-TYPE", "name": "source_type", "domain": "foundation", "version": "1.0.0",
            "terms": [
                {"code": "literature", "display": "文献", "description": "PubMed/期刊文献"},
                {"code": "clinical_case", "display": "临床病例", "description": "临床病例报告"},
                {"code": "lysis_assay_file", "display": "裂解谱数据文件", "description": "体外裂解谱数据"},
                {"code": "clinical_trial", "display": "临床试验", "description": "临床试验数据"},
                {"code": "internal_experiment", "display": "内部实验", "description": "内部实验室数据"}
            ]
        },
        {
            "id": "VOC-SOURCE-ACCESS", "name": "source_access_level", "domain": "foundation", "version": "1.0.0",
            "terms": [
                {"code": "public", "display": "公开", "description": "可对外公开"},
                {"code": "internal", "display": "内部", "description": "仅内部使用"},
                {"code": "restricted", "display": "受限", "description": "需特殊授权"}
            ]
        },
        # ------- CI 域词表 -------
        {
            "id": "VOC-ENGINEERING-STRATEGY", "name": "engineering_strategy", "domain": "ci", "version": "1.0.0",
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
            "id": "VOC-EVENT-TYPE", "name": "intelligence_event_type", "domain": "ci", "version": "1.0.0",
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
            "id": "VOC-PROGRAM-STAGE", "name": "development_stage", "domain": "ci", "version": "1.0.0",
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
            "id": "VOC-PROGRAM-TYPE", "name": "program_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "therapeutic", "display": "治疗性", "description": "治疗产品"},
                {"code": "diagnostic", "display": "诊断性", "description": "诊断产品"},
                {"code": "platform", "display": "平台技术", "description": "技术平台"},
                {"code": "research", "display": "研究工具", "description": "研究用试剂或工具"}
            ]
        },
        {
            "id": "VOC-MODALITY", "name": "modality", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "natural_phage", "display": "天然噬菌体", "description": "天然分离噬菌体"},
                {"code": "engineered_phage", "display": "工程化噬菌体", "description": "经改造的噬菌体"},
                {"code": "cocktail", "display": "鸡尾酒", "description": "噬菌体混合物"}
            ]
        },
        {
            "id": "VOC-ORGANIZATION-TYPE", "name": "organization_type", "domain": "ci", "version": "1.0.0",
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
            "id": "VOC-CLAIM-TYPE", "name": "technical_claim_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "efficacy", "display": "有效性", "description": "治疗效果主张"},
                {"code": "host_range", "display": "宿主范围", "description": "宿主范围扩展主张"},
                {"code": "safety", "display": "安全性", "description": "安全性主张"},
                {"code": "manufacturability", "display": "可制造性", "description": "生产可行性主张"},
                {"code": "mechanism", "display": "作用机制", "description": "机制相关主张"}
            ]
        },
        {
            "id": "VOC-RESULT-TYPE", "name": "technical_result_type", "domain": "ci", "version": "1.0.0",
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
            "id": "VOC-ASSESSMENT-TYPE", "name": "competitor_assessment_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "threat", "display": "威胁", "description": "竞争威胁评估"},
                {"code": "opportunity", "display": "机会", "description": "市场机会评估"},
                {"code": "capability", "display": "能力", "description": "竞争对手能力评估"},
                {"code": "uncertainty", "display": "不确定性", "description": "不确定性评估"}
            ]
        },
        {
            "id": "VOC-PATENT-LEGAL-STATUS", "name": "patent_legal_status", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "pending",   "display": "审查中",   "description": "申请已提交，尚未授权"},
                {"code": "granted",   "display": "已授权",   "description": "已获授权"},
                {"code": "expired",   "display": "已过期",   "description": "专利已过期"},
                {"code": "abandoned", "display": "已放弃",   "description": "申请人主动放弃"},
                {"code": "unknown",   "display": "未知",     "description": "法律状态不明"}
            ]
        },
        {
            "id": "VOC-TRIAL-PHASE", "name": "clinical_trial_phase", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "preclinical", "display": "临床前",  "description": "尚未进入临床"},
                {"code": "phase_1",     "display": "I期",     "description": "安全性/剂量探索"},
                {"code": "phase_1_2",   "display": "I/II期",  "description": "I/II 期联合"},
                {"code": "phase_2",     "display": "II期",    "description": "有效性探索"},
                {"code": "phase_2b",    "display": "IIb期",   "description": "剂量确认"},
                {"code": "phase_3",     "display": "III期",   "description": "确证性试验"},
                {"code": "phase_4",     "display": "IV期",    "description": "上市后研究"},
                {"code": "unknown",     "display": "未知",    "description": "阶段不明"}
            ]
        },
        {
            "id": "VOC-TRIAL-STATUS", "name": "clinical_trial_status", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "not_yet_recruiting", "display": "尚未招募", "description": "已登记未启动"},
                {"code": "recruiting",         "display": "招募中",   "description": "正在入组"},
                {"code": "active",             "display": "进行中",   "description": "已入组，试验进行中"},
                {"code": "completed",          "display": "已完成",   "description": "试验已完成"},
                {"code": "terminated",         "display": "已终止",   "description": "提前终止"},
                {"code": "suspended",          "display": "已暂停",   "description": "暂时暂停"},
                {"code": "withdrawn",          "display": "已撤回",   "description": "启动前撤回"},
                {"code": "unknown",            "display": "未知",     "description": "状态不明"}
            ]
        },
        {
            "id": "VOC-IQ-TYPE", "name": "intelligence_question_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "market",     "display": "市场",     "description": "竞争格局/份额类问题"},
                {"code": "technology", "display": "技术",     "description": "技术路线/成熟度类问题"},
                {"code": "ip",         "display": "IP",       "description": "专利/FTO 类问题"},
                {"code": "clinical",   "display": "临床",     "description": "适应症/试验类问题"},
                {"code": "bd",         "display": "BD",       "description": "合作/引进/并购类问题"}
            ]
        },
        {
            "id": "VOC-WATCH-TARGET", "name": "watchlist_target_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "organization",        "display": "组织",     "description": "竞争对手组织"},
                {"code": "development_program", "display": "研发项目", "description": "某竞争对手的管线"},
                {"code": "engineering_strategy","display": "工程策略", "description": "某类技术路线"},
                {"code": "pathogen",            "display": "病原菌",   "description": "某类目标病原"},
                {"code": "patent_family",       "display": "专利族",   "description": "某族专利"},
                {"code": "clinical_trial",      "display": "临床试验", "description": "某项临床试验"}
            ]
        },
        # ========================================================
        # ★ P1 质量能力：新增词表
        # ========================================================
        {
            "id": "VOC-ORG-RELATION", "name": "organization_relation_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "parent_of",      "display": "母公司",   "description": "A 是 B 的母公司"},
                {"code": "subsidiary_of",  "display": "子公司",   "description": "A 是 B 的子公司"},
                {"code": "brand_of",       "display": "品牌归属", "description": "A 是 B 的品牌"},
                {"code": "renamed_to",     "display": "更名",     "description": "A 更名为 B"},
                {"code": "acquired",       "display": "收购",     "description": "A 收购了 B"},
            ],
        },
        {
            "id": "VOC-CONFLICT-TYPE", "name": "conflict_type", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "claim_status_conflict",   "display": "主张状态冲突", "description": "同一 construct 下同类 claim 一个 supported 一个 contradicted"},
                {"code": "result_direction_conflict","display": "结果方向冲突", "description": "同一 construct 下同类 result 方向相反"},
                {"code": "cross_construct_conflict","display": "跨构建体冲突", "description": "同一 strategy 下不同 construct 的结果方向相反"},
            ],
        },
        {
            "id": "VOC-CREDIBILITY-TIER", "name": "credibility_tier", "domain": "ci", "version": "1.0.0",
            "terms": [
                {"code": "primary",    "display": "一手来源", "description": "监管公告 / 官方披露 / 同行评议论文"},
                {"code": "secondary",  "display": "二手来源", "description": "新闻稿 / 会议摘要 / 专利文本"},
                {"code": "tertiary",   "display": "三手来源", "description": "媒体报道 / 二手转述"},
                {"code": "unknown",    "display": "未知",     "description": "来源不明"},
            ],
        },
        # ========================================================
        # ★ PRD 14.3 时间语义
        # ========================================================
        {
            "id": "VOC-TIME-SEMANTICS", "name": "time_semantics", "domain": "foundation", "version": "1.0.0",
            "terms": [
                {"code": "valid_from",   "display": "生效时间", "description": "对象开始有效的时间"},
                {"code": "valid_to",     "display": "失效时间", "description": "对象失效时间，null 表示当前仍有效"},
                {"code": "as_of_date",   "display": "截止日期", "description": "查询某时刻有效对象的参照时间"},
            ],
        },
    ]

    with driver.session() as session:
        for vocab in vocabularies:
            # 创建词表节点
            session.run("""
                MERGE (v:ControlledVocabulary {vocabulary_id: $id})
                SET v.vocabulary_name = $name,
                    v.domain = $domain,
                    v.version = $version,
                    v.status = 'active',
                    v.owner = 'platform_team',
                    v.created_at = datetime()
            """, id=vocab["id"], name=vocab["name"], domain=vocab["domain"], version=vocab["version"])

            # 创建术语节点并关联
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

    print("✅ ControlledVocabulary 受控词表已创建（含 CI 词表 + P1 质量能力词表 + 时间语义词表）")


# ========================================================
# ★ 从 src/shared/init_schema.py 合并而来
# ========================================================

def initialize_neo4j_schema(driver: Driver) -> None:
    """
    幂等地创建 Neo4j 数据库约束和索引。
    可多次调用，不会重复创建已存在的约束和索引。
    须在每个 Notebook 的 Cell 1 中调用一次。
    """
    CONSTRAINTS = [
        # Foundation 层
        ("SourceArtifact", "source_id"),
        ("SourceArtifact", "url"),
        ("Pathogen", "pathogen_id"),
        ("Organization", "organization_id"),
        ("Review", "review_id"),
        ("AuditEvent", "audit_id"),
        ("OntologyModule", "module_id"),
        # CI Domain 层
        ("DevelopmentProgram", "program_id"),
        ("IntelligenceEvent", "event_id"),
        ("EngineeringStrategy", "strategy_id"),
        ("EngineeredPhageConstruct", "construct_id"),
        ("TechnicalClaim", "claim_id"),
        ("TechnicalResult", "result_id"),
        ("TechnologyAssessment", "technology_assessment_id"),
        ("CompetitorAssessment", "assessment_id"),
        ("IntelligenceProduct", "brief_id"),
        ("DecisionRecord", "decision_id"),
        ("IntelligenceUseEvent", "use_event_id"),
    ]

    INDEXES = [
        ("AuditEvent", "object_id"),
        ("AuditEvent", "actor_id"),
        ("AuditEvent", "timestamp"),
        ("IntelligenceEvent", "event_type"),
        ("IntelligenceEvent", "event_date"),
        ("Pathogen", "species"),
        ("Organization", "canonical_name"),
        ("Review", "target_object_type"),
        ("Review", "target_object_id"),
    ]

    with driver.session() as session:
        for label, prop in CONSTRAINTS:
            session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
        for label, prop in INDEXES:
            session.run(
                f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            )

    print(f"✅ Neo4j Schema 初始化完成（{len(CONSTRAINTS)} 条约束, {len(INDEXES)} 个索引, 幂等）")