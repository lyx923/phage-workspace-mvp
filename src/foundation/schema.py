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
        
        print("✅ 所有数据库约束与索引创建完成（含科学子网 + 市场情报子网）")


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
    
    print("✅ ControlledVocabulary 受控词表已创建")