# src/shared/init_schema.py
from neo4j import Driver


def initialize_neo4j_schema(driver: Driver) -> None:
    """
    幂等地创建 Neo4j 数据库约束和索引。
    可多次调用，不会重复创建已存在的约束和索引。
    须在每个 Notebook 的 Cell 1 中调用一次。
    """
    # 节点唯一性约束（按 Label + 属性）
    CONSTRAINTS = [
        # Foundation 层
        ("SourceArtifact", "source_id"),
        ("SourceArtifact", "url"),
        ("Pathogen", "pathogen_id"),
        ("Organization", "organization_id"),
        ("Review", "review_id"),
        ("AuditEvent", "audit_event_id"),   # 注意：PRD 中为 audit_id，但实际节点属性是 audit_event_id
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

    # 查询性能索引
    INDEXES = [
        ("AuditEvent", "object_id"),
        ("AuditEvent", "actor_id"),
        ("AuditEvent", "occurred_at"),      # 原 timestamp，实际属性是 occurred_at
        ("IntelligenceEvent", "event_type"),
        ("IntelligenceEvent", "event_date"),
        ("Pathogen", "species"),
        ("Organization", "canonical_name"),
        ("Review", "target_object_type"),
        ("Review", "target_object_id"),
    ]

    with driver.session() as session:
        # 创建约束
        for label, prop in CONSTRAINTS:
            session.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )

        # 创建索引
        for label, prop in INDEXES:
            session.run(
                f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"
            )

    print(f"✅ Neo4j Schema 初始化完成（{len(CONSTRAINTS)} 条约束, {len(INDEXES)} 个索引, 幂等）")