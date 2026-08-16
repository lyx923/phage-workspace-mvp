# src/foundation/schema.py
from config import get_driver
from neo4j import GraphDatabase

def create_schema(driver):
    """创建所有约束和索引（幂等，支持重复执行）"""
    with driver.session() as session:
        
        # 1. Pathogen 唯一约束
        session.run("CREATE CONSTRAINT pathogen_id_unique IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.pathogen_id IS UNIQUE;")
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

        # EvidenceSource：evidence_id 唯一（后续使用）
        session.run("CREATE CONSTRAINT evidence_id_unique IF NOT EXISTS FOR (e:EvidenceSource) REQUIRE e.evidence_id IS UNIQUE;")

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

        print("✅ 所有数据库约束与索引创建完成（含科学子网 + 市场情报子网）")

if __name__ == "__main__":
    with get_driver() as driver:
        create_schema(driver)