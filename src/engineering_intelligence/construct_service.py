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
    relationship_type: str = "USES_CONSTRUCT",
    actor_id: str = "system"
) -> bool:
    """
    将研发项目（DevelopmentProgram）与工程化构建体（EngineeredPhageConstruct）关联
    从而打通市场情报与工程情报
    """
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

        # 检查关系是否已存在
        existing = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            OPTIONAL MATCH (d)-[r:USES_CONSTRUCT]->(ec)
            RETURN r IS NOT NULL AS exists
        """, pid=program_id, cid=construct_id).single()

        if existing and existing['exists']:
            print(f"ℹ️ 关联已存在: {program_id} → {construct_id}")
            return True

        # 创建关联
        session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            CREATE (d)-[:USES_CONSTRUCT]->(ec)
        """, pid=program_id, cid=construct_id)

        # 审计日志（新版）
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="DevelopmentProgram",
            object_id=program_id,
            actor_id=actor_id,
            delta={
                "relation": "USES_CONSTRUCT",
                "construct_id": construct_id
            },
            reason=f"项目 {program_id} 关联构建体 {construct_id}"
        )

        print(f"✅ 关联创建成功: {program_id} → {construct_id}")
        return True


def get_constructs_by_program(driver: Driver, program_id: str) -> List[Dict]:
    """获取某个研发项目使用的所有工程化构建体"""
    with driver.session() as session:
        result = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:USES_CONSTRUCT]->(ec:EngineeredPhageConstruct)
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
    """获取使用某个工程策略的所有项目"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $sid})
            MATCH (d:DevelopmentProgram)-[:USES_CONSTRUCT]->(ec)
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