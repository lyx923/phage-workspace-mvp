# src/engineering_intelligence/construct_service.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event
from src.shared.pathogen_service import get_or_create_pathogen


def generate_construct_id() -> str:
    return f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"


def _resolve_developer_org_id(
    session,
    program_id: Optional[str],
    organization_id: Optional[str],
) -> Optional[str]:
    """
    v0.6 P1-7：确定 construct 的开发者组织。

    优先级：
      1. 显式传入的 organization_id
      2. 从 program_id 推导：MATCH (o:Organization)-[:DEVELOPS]->(d:DevelopmentProgram {program_id})
    """
    if organization_id:
        chk = session.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
            oid=organization_id,
        ).single()
        if chk:
            return organization_id
        # 传入的 organization_id 不存在，继续尝试从 program 推导

    if program_id:
        r = session.run("""
            MATCH (o:Organization)-[:DEVELOPS]->(d:DevelopmentProgram {program_id: $pid})
            RETURN o.organization_id AS oid LIMIT 1
        """, pid=program_id).single()
        if r:
            return r["oid"]

    return None


def create_engineered_construct(
    driver: Driver,
    public_name: Optional[str] = None,
    construct_code: Optional[str] = None,
    parent_phage_name: Optional[str] = None,
    intended_effects: Optional[List[str]] = None,
    target_pathogen_ids: Optional[List[str]] = None,       # 保留兼容
    target_pathogen_species: Optional[List[str]] = None,   # 推荐
    strategy_ids: Optional[List[str]] = None,
    construct_status: str = "proposed",
    first_public_date: Optional[str] = None,
    target_pathogen_text: Optional[str] = None,
    organization_id: Optional[str] = None,                 # v0.6 P1-7：显式开发者组织
    program_id: Optional[str] = None,                      # v0.6 P1-7：用于自动推导 organization
    actor_id: str = "system",
) -> str:
    """
    创建工程化噬菌体构建体（PRD 9.1）。

    v0.6 P1-7 新增：
      - organization_id / program_id 参数
      - 自动建立 (ec)-[:DEVELOPED_BY]->(o:Organization)
      - 若未传 organization_id，但传了 program_id，会从 program 推导出组织
      - 若两者都传了，会同时建立 ASSOCIATED_WITH（如果还没建）
    """
    construct_id = generate_construct_id()
    intended_effects = intended_effects or []
    target_pathogen_ids = target_pathogen_ids or []
    target_pathogen_species = target_pathogen_species or []
    strategy_ids = strategy_ids or []

    # species → pathogen_id
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
        # 1. 创建构建体节点
        session.run("""
            CREATE (ec:EngineeredPhageConstruct {
                construct_id: $construct_id,
                public_name: $public_name,
                construct_code: $construct_code,
                construct_status: $construct_status,
                intended_effects: $intended_effects,
                target_pathogen_text: $target_pathogen_text,
                first_public_date: $first_public_date,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, construct_id=construct_id, public_name=public_name,
           construct_code=construct_code, construct_status=construct_status,
           intended_effects=intended_effects,
           target_pathogen_text=target_pathogen_text or "",
           first_public_date=first_public_date)

        # 2. 关联亲本噬菌体
        if parent_phage_name:
            result = session.run("""
                MATCH (ph:Phage)
                WHERE ph.name = $parent_name OR ph.phage_id = $parent_name
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (ec)-[:DERIVED_FROM]->(ph)
                RETURN ph.name AS name
                LIMIT 1
            """, parent_name=parent_phage_name, construct_id=construct_id)
            if not result.single():
                print(f"⚠️ 亲本噬菌体 '{parent_phage_name}' 未找到，跳过关联")

        # 3. 关联策略
        for strategy_id in strategy_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                MERGE (ec)-[:IMPLEMENTS]->(es)
            """, construct_id=construct_id, strategy_id=strategy_id)

        # 4. 关联靶向病原体
        for pathogen_id in target_pathogen_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                MERGE (ec)-[:TARGETS]->(p)
            """, construct_id=construct_id, pathogen_id=pathogen_id)

        # 5. v0.6 P1-7：关联开发者组织（DEVELOPED_BY）
        resolved_org_id = _resolve_developer_org_id(session, program_id, organization_id)
        linked_org = False
        if resolved_org_id:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (o:Organization {organization_id: $oid})
                MERGE (ec)-[:DEVELOPED_BY]->(o)
            """, construct_id=construct_id, oid=resolved_org_id)
            linked_org = True

        # 6. v0.6 P1-7：如果传了 program_id 且关系还没建，顺带建立 ASSOCIATED_WITH
        linked_program = False
        if program_id:
            chk = session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                      -[:ASSOCIATED_WITH]->(d:DevelopmentProgram {program_id: $pid})
                RETURN 1 AS x LIMIT 1
            """, cid=construct_id, pid=program_id).single()
            if not chk:
                chk2 = session.run(
                    "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d LIMIT 1",
                    pid=program_id,
                ).single()
                if chk2:
                    session.run("""
                        MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                        MATCH (d:DevelopmentProgram {program_id: $pid})
                        MERGE (ec)-[:ASSOCIATED_WITH]->(d)
                    """, cid=construct_id, pid=program_id)
                    linked_program = True

        # 7. 审计
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
                "organization_id": resolved_org_id,
                "program_id": program_id,
                "linked_org": linked_org,
                "linked_program": linked_program,
            },
            reason=f"创建工程化构建体: {public_name or construct_code or construct_id}"
        )

        return construct_id


# ============================================================
# v0.6 P1-7：独立挂载与回填
# ============================================================

def link_construct_to_organization(
    driver: Driver,
    construct_id: str,
    organization_id: str,
    actor_id: str = "system",
) -> bool:
    """
    v0.6 P1-7：建立 (EngineeredPhageConstruct)-[:DEVELOPED_BY]->(Organization)。
    幂等。
    """
    with driver.session() as s:
        ec = s.run(
            "MATCH (ec:EngineeredPhageConstruct {construct_id: $cid}) RETURN ec LIMIT 1",
            cid=construct_id,
        ).single()
        if not ec:
            raise ValueError(f"EngineeredPhageConstruct {construct_id} 不存在")
        org = s.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
            oid=organization_id,
        ).single()
        if not org:
            raise ValueError(f"Organization {organization_id} 不存在")

        existing = s.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                  -[:DEVELOPED_BY]->(o:Organization {organization_id: $oid})
            RETURN 1 AS x LIMIT 1
        """, cid=construct_id, oid=organization_id).single()
        if existing:
            return True

        s.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (o:Organization {organization_id: $oid})
            MERGE (ec)-[:DEVELOPED_BY]->(o)
        """, cid=construct_id, oid=organization_id)

    write_audit_event(
        driver,
        action_type="LINK_CREATE",
        object_type="EngineeredPhageConstruct",
        object_id=construct_id,
        actor_id=actor_id,
        delta={
            "relation": "DEVELOPED_BY",
            "organization_id": organization_id,
        },
        reason=f"构建体 {construct_id} 关联开发者 {organization_id}",
    )
    return True


def backfill_construct_developed_by(
    driver: Driver,
    actor_id: str = "backfill",
) -> dict:
    """
    v0.6 P1-7 backfill：
    从已有的 (ec)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)<-[:DEVELOPS]-(o:Organization)
    推导 (ec)-[:DEVELOPED_BY]->(o)，幂等。

    返回：{"created": N, "details": [...]}
    """
    created = 0
    details = []

    with driver.session() as s:
        rows = list(s.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
                  <-[:DEVELOPS]-(o:Organization)
            WHERE NOT (ec)-[:DEVELOPED_BY]->(o)
            RETURN DISTINCT ec.construct_id AS cid, o.organization_id AS oid
        """))

        for r in rows:
            cid = r["cid"]
            oid = r["oid"]
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (o:Organization {organization_id: $oid})
                MERGE (ec)-[:DEVELOPED_BY]->(o)
            """, cid=cid, oid=oid)
            created += 1
            details.append({"construct_id": cid, "organization_id": oid})

    if created > 0:
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="EngineeredPhageConstruct",
            object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_developed_by": created, "details": details},
            reason=f"回填 DEVELOPED_BY 关系：{created} 条",
        )

    return {"created": created, "details": details}


# ============================================================
# 查询
# ============================================================

def get_constructs_by_strategy(driver: Driver, strategy_id: str) -> List[Dict]:
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $strategy_id})
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DEVELOPED_BY]->(o:Organization)
            WITH ec, ph, o, COLLECT(DISTINCT p.species) AS target_species
            RETURN ec.construct_id AS id,
                   ec.public_name AS name,
                   ec.construct_status AS status,
                   ph.name AS parent_phage,
                   o.canonical_name AS developer,
                   target_species AS target_pathogens
            ORDER BY ec.created_at DESC
        """, strategy_id=strategy_id)
        return [dict(record) for record in result]


def link_program_to_construct(
    driver: Driver,
    program_id: str,
    construct_id: str,
    relationship_type: str = "ASSOCIATED_WITH",
    actor_id: str = "system"
) -> bool:
    """
    将研发项目与工程化构建体关联，方向：(ec)-[:ASSOCIATED_WITH]->(d)。
    """
    allowed_types = {"ASSOCIATED_WITH", "USES_CONSTRUCT"}
    if relationship_type not in allowed_types:
        raise ValueError(
            f"不支持的关系类型: {relationship_type}，仅允许 {sorted(allowed_types)}"
        )

    with driver.session() as session:
        prog_check = session.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d",
            pid=program_id
        ).single()
        if not prog_check:
            raise ValueError(f"项目 {program_id} 不存在")

        const_check = session.run(
            "MATCH (ec:EngineeredPhageConstruct {construct_id: $cid}) RETURN ec",
            cid=construct_id
        ).single()
        if not const_check:
            raise ValueError(f"构建体 {construct_id} 不存在")

        existing = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            OPTIONAL MATCH (ec)-[r:ASSOCIATED_WITH]->(d)
            RETURN r IS NOT NULL AS exists
        """, pid=program_id, cid=construct_id).single()

        if existing and existing['exists']:
            return True

        session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MERGE (ec)-[:ASSOCIATED_WITH]->(d)
            SET ec.updated_at = datetime()
        """, pid=program_id, cid=construct_id)

        # v0.6 P1-7：顺带补 DEVELOPED_BY（如果还没建）
        org_row = session.run("""
            MATCH (o:Organization)-[:DEVELOPS]->(d:DevelopmentProgram {program_id: $pid})
            RETURN o.organization_id AS oid LIMIT 1
        """, pid=program_id).single()
        if org_row:
            oid = org_row["oid"]
            already = session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                      -[:DEVELOPED_BY]->(o:Organization {organization_id: $oid})
                RETURN 1 AS x LIMIT 1
            """, cid=construct_id, oid=oid).single()
            if not already:
                session.run("""
                    MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                    MATCH (o:Organization {organization_id: $oid})
                    MERGE (ec)-[:DEVELOPED_BY]->(o)
                """, cid=construct_id, oid=oid)

        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="EngineeredPhageConstruct",
            object_id=construct_id,
            actor_id=actor_id,
            delta={
                "relation": "ASSOCIATED_WITH",
                "program_id": program_id,
            },
            reason=f"构建体 {construct_id} 关联项目 {program_id}"
        )

        return True


def get_constructs_by_program(driver: Driver, program_id: str) -> List[Dict]:
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
            OPTIONAL MATCH (ec)-[:DEVELOPED_BY]->(o:Organization)
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            WITH ec,
                 es.strategy_type AS strategy_type,
                 ph.name AS parent_phage,
                 o.canonical_name AS developer,
                 COLLECT(DISTINCT p.species) AS target_pathogens,
                 COLLECT(DISTINCT tc.claim_type) AS claim_types,
                 COLLECT(DISTINCT tr.result_type) AS result_types
            RETURN ec.construct_id AS id,
                   ec.public_name AS name,
                   ec.construct_status AS status,
                   strategy_type,
                   parent_phage,
                   developer,
                   target_pathogens,
                   claim_types,
                   result_types
            ORDER BY ec.created_at DESC
        """, pid=program_id)
        return [dict(record) for record in result]


def get_programs_by_strategy(driver: Driver, strategy_id: str) -> List[Dict]:
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