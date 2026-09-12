# src/engineering_intelligence/construct_service.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event
from src.shared.pathogen_service import get_or_create_pathogen  # 新增导入


def generate_construct_id() -> str:
    return f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"


def create_engineered_construct(
    driver: Driver,
    public_name: Optional[str] = None,
    construct_code: Optional[str] = None,
    parent_phage_name: Optional[str] = None,
    intended_effects: Optional[List[str]] = None,
    target_pathogen_ids: Optional[List[str]] = None,       # 保留兼容，推荐使用 target_pathogen_species
    target_pathogen_species: Optional[List[str]] = None,   # 新增：物种名称列表
    strategy_ids: Optional[List[str]] = None,
    construct_status: str = "proposed",
    first_public_date: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    """
    创建工程化噬菌体构建体（PRD 9.1）
    关联到亲本噬菌体（如果存在）、策略和靶向病原体

    参数：
        target_pathogen_ids: 已废弃，建议使用 target_pathogen_species
        target_pathogen_species: 靶向病原体物种名称列表（如 ["Klebsiella pneumoniae"]）
    """
    construct_id = generate_construct_id()
    intended_effects = intended_effects or []
    target_pathogen_ids = target_pathogen_ids or []
    target_pathogen_species = target_pathogen_species or []
    strategy_ids = strategy_ids or []

    # 如果提供了 species，将其转换为 pathogen_id 并合并到 target_pathogen_ids
    for species in target_pathogen_species:
        pathogen_id = get_or_create_pathogen(
            driver,
            species=species,
            pathogen_type="bacteria",
            actor_id=actor_id,
        )
        if pathogen_id not in target_pathogen_ids:
            target_pathogen_ids.append(pathogen_id)

    with driver.session() as session:
        # 创建构建体节点
        session.run("""
            CREATE (ec:EngineeredPhageConstruct {
                construct_id: $construct_id,
                public_name: $public_name,
                construct_code: $construct_code,
                construct_status: $construct_status,
                intended_effects: $intended_effects,
                first_public_date: $first_public_date,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, construct_id=construct_id, public_name=public_name,
           construct_code=construct_code, construct_status=construct_status,
           intended_effects=intended_effects, first_public_date=first_public_date)

        # 关联亲本噬菌体
        if parent_phage_name:
            result = session.run("""
                MATCH (ph:Phage)
                WHERE ph.name = $parent_name OR ph.phage_id = $parent_name
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                CREATE (ec)-[:DERIVED_FROM]->(ph)
                RETURN ph.name AS name
            """, parent_name=parent_phage_name, construct_id=construct_id)
            if not result.single():
                print(f"⚠️ 亲本噬菌体 '{parent_phage_name}' 未找到，跳过关联")

        # 关联策略
        for strategy_id in strategy_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                CREATE (ec)-[:IMPLEMENTS]->(es)
            """, construct_id=construct_id, strategy_id=strategy_id)

        # 关联靶向病原体
        for pathogen_id in target_pathogen_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                CREATE (ec)-[:TARGETS]->(p)
            """, construct_id=construct_id, pathogen_id=pathogen_id)

        # 审计日志（新版）
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="EngineeredPhageConstruct",
            object_id=construct_id,
            actor_id=actor_id,
            delta={
                "public_name": public_name,
                "construct_status": construct_status,
                "strategy_ids": strategy_ids,
                "target_pathogen_ids": target_pathogen_ids,
                "target_pathogen_species": target_pathogen_species,
            },
            reason=f"创建工程化构建体: {public_name or construct_code or construct_id}"
        )

        return construct_id


def get_constructs_by_strategy(driver: Driver, strategy_id: str) -> List[Dict]:
    """获取使用某个策略的所有构建体"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $strategy_id})
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            WITH ec, ph, COLLECT(DISTINCT p.species) AS target_species
            RETURN ec.construct_id AS id,
                   ec.public_name AS name,
                   ec.construct_status AS status,
                   ph.name AS parent_phage,
                   target_species AS target_pathogens
            ORDER BY ec.created_at DESC
        """, strategy_id=strategy_id)
        return [dict(record) for record in result]


def link_program_to_construct(
    driver: Driver,
    program_id: str,
    construct_id: str,
    relationship_type: str = "ASSOCIATED_WITH",  # 按 PRD 9.1 / 11.2 定义
    actor_id: str = "system"
) -> bool:
    """
    将研发项目（DevelopmentProgram）与工程化构建体（EngineeredPhageConstruct）关联

    按 PRD 定义，关系方向为：
        (EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(DevelopmentProgram)

    relationship_type 参数保留为可配置项，便于未来切换，但默认使用 PRD 标准。
    """
    # 只接受白名单内的关系类型，避免拼写错误悄悄写入
    allowed_types = {"ASSOCIATED_WITH", "USES_CONSTRUCT"}
    if relationship_type not in allowed_types:
        raise ValueError(
            f"不支持的关系类型: {relationship_type}，仅允许 {sorted(allowed_types)}"
        )

    with driver.session() as session:
        # 检查项目是否存在
        prog_check = session.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d",
            pid=program_id
        ).single()
        if not prog_check:
            raise ValueError(f"项目 {program_id} 不存在")

        # 检查构建体是否存在
        const_check = session.run(
            "MATCH (ec:EngineeredPhageConstruct {construct_id: $cid}) RETURN ec",
            cid=construct_id
        ).single()
        if not const_check:
            raise ValueError(f"构建体 {construct_id} 不存在")

        # 检查关系是否已存在（按方向 + 类型）
        existing = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            OPTIONAL MATCH (ec)-[r:ASSOCIATED_WITH]->(d)
            RETURN r IS NOT NULL AS exists
        """, pid=program_id, cid=construct_id).single()

        if existing and existing['exists']:
            print(f"ℹ️ 关联已存在: {construct_id} → {program_id} (ASSOCIATED_WITH)")
            return True

        # 创建关联（方向：construct → program）
        session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MERGE (ec)-[:ASSOCIATED_WITH]->(d)
            SET ec.updated_at = datetime()
        """, pid=program_id, cid=construct_id)

        # 审计日志
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="EngineeredPhageConstruct",
            object_id=construct_id,
            actor_id=actor_id,
            delta={
                "relation": "ASSOCIATED_WITH",
                "program_id": program_id
            },
            reason=f"构建体 {construct_id} 关联项目 {program_id} (ASSOCIATED_WITH)"
        )

        print(f"✅ 关联创建成功: {construct_id} → {program_id} (ASSOCIATED_WITH)")
        return True


def get_constructs_by_program(driver: Driver, program_id: str) -> List[Dict]:
    """
    获取某个研发项目关联的所有工程化构建体

    兼容两种情况：
      - 新数据: (ec)-[:ASSOCIATED_WITH]->(d)   [PRD 标准]
      - 旧数据: (d)-[:USES_CONSTRUCT]->(ec)    [历史遗留]
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            OPTIONAL MATCH (ec1:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
            OPTIONAL MATCH (d)-[:USES_CONSTRUCT]->(ec2:EngineeredPhageConstruct)
            WITH d,
                 COLLECT(DISTINCT ec1) + COLLECT(DISTINCT ec2) AS constructs
            UNWIND constructs AS ec
            WITH DISTINCT ec
            WHERE ec IS NOT NULL
            OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            WITH ec,
                 es.strategy_type AS strategy_type,
                 ph.name AS parent_phage,
                 COLLECT(DISTINCT p.species) AS target_pathogens,
                 COLLECT(DISTINCT tc.claim_type) AS claim_types,
                 COLLECT(DISTINCT tr.result_type) AS result_types
            RETURN ec.construct_id AS id,
                   ec.public_name AS name,
                   ec.construct_status AS status,
                   strategy_type,
                   parent_phage,
                   target_pathogens,
                   claim_types,
                   result_types
            ORDER BY ec.created_at DESC
        """, pid=program_id)
        return [dict(record) for record in result]


def get_programs_by_strategy(driver: Driver, strategy_id: str) -> List[Dict]:
    """
    获取使用某个工程策略的所有项目

    兼容新旧两种关系方向：
      - 新: (ec)-[:ASSOCIATED_WITH]->(d)
      - 旧: (d)-[:USES_CONSTRUCT]->(ec)
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $sid})
            OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(d1:DevelopmentProgram)
            OPTIONAL MATCH (d2:DevelopmentProgram)-[:USES_CONSTRUCT]->(ec)
            WITH ec, COLLECT(DISTINCT d1) + COLLECT(DISTINCT d2) AS progs
            UNWIND progs AS d
            WITH DISTINCT ec, d
            WHERE d IS NOT NULL
            OPTIONAL MATCH (d)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            WITH d, ec, ph, COLLECT(DISTINCT p.species) AS target_pathogens
            RETURN d.program_id AS program_id,
                   d.canonical_name AS program_name,
                   d.development_stage AS stage,
                   d.program_status AS status,
                   ec.public_name AS construct_name,
                   ec.construct_status AS construct_status,
                   ph.name AS parent_phage,
                   target_pathogens
            ORDER BY d.created_at DESC
        """, sid=strategy_id)
        return [dict(record) for record in result]