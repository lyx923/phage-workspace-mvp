# src/engineering_intelligence/construct_service.py
"""
EngineeredPhageConstruct / EngineeringModification / DeliveryPayload
合并服务（PRD 9.1 / 9.3）

包含三个部分：
    Part 1: EngineeredPhageConstruct —— 工程化噬菌体构建体
    Part 2: EngineeringModification  —— 工程改造
    Part 3: DeliveryPayload          —— 递送载荷
"""

# ==================================================================
# Part 1: EngineeredPhageConstruct (原 construct_service.py)
# ==================================================================
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event
from src.shared.evidence_source import get_or_create_pathogen


def generate_construct_id() -> str:
    """生成构建体 ID（格式：ENG:CONST:XXXXXXXX）。"""
    return f"ENG:CONST:{uuid.uuid4().hex[:8].upper()}"


def _resolve_developer_org_id(session, program_id, organization_id):
    """
    内部函数：解析开发者组织 ID。
    优先使用显式传入的 organization_id，其次从 program_id 反查。
    """
    if organization_id:
        chk = session.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
            oid=organization_id,
        ).single()
        if chk:
            return organization_id

    if program_id:
        r = session.run("""
            MATCH (o:Organization)-[:DEVELOPS]->(d:DevelopmentProgram {program_id: $pid})
            RETURN o.organization_id AS oid LIMIT 1
        """, pid=program_id).single()
        if r:
            return r["oid"]
    return None


def create_engineered_construct(
    driver: Driver, public_name=None, construct_code=None,
    parent_phage_name=None, intended_effects=None,
    target_pathogen_ids=None, target_pathogen_species=None,
    strategy_ids=None, construct_status="proposed",
    first_public_date=None, target_pathogen_text=None,
    organization_id=None, program_id=None, actor_id="system",
) -> str:
    """
    创建工程化噬菌体构建体。

    自动完成：
        - 创建节点
        - 可选：DERIVED_FROM 亲本噬菌体
        - IMPLEMENTS 工程策略
        - TARGETS 目标病原（支持 ID 或物种名）
        - DEVELOPED_BY 开发者组织（从 program_id 反查）
        - ASSOCIATED_WITH 关联研发项目

    Returns:
        str: construct_id
    """
    construct_id = generate_construct_id()
    intended_effects = intended_effects or []
    target_pathogen_ids = target_pathogen_ids or []
    target_pathogen_species = target_pathogen_species or []
    strategy_ids = strategy_ids or []

    # 把物种名转换为 pathogen_id
    for species in target_pathogen_species:
        pathogen_id = get_or_create_pathogen(
            driver, species=species, pathogen_type="bacteria", actor_id=actor_id,
        )
        if pathogen_id not in target_pathogen_ids:
            target_pathogen_ids.append(pathogen_id)

    with driver.session() as session:
        # 创建构建体节点
        session.run("""
            CREATE (ec:EngineeredPhageConstruct {
                construct_id: $construct_id, public_name: $public_name,
                construct_code: $construct_code, construct_status: $construct_status,
                intended_effects: $intended_effects,
                target_pathogen_text: $target_pathogen_text,
                first_public_date: $first_public_date,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, construct_id=construct_id, public_name=public_name,
             construct_code=construct_code, construct_status=construct_status,
             intended_effects=intended_effects,
             target_pathogen_text=target_pathogen_text or "",
             first_public_date=first_public_date)

        # 可选：DERIVED_FROM 亲本噬菌体
        if parent_phage_name:
            result = session.run("""
                MATCH (ph:Phage)
                WHERE ph.name = $parent_name OR ph.phage_id = $parent_name
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MERGE (ec)-[:DERIVED_FROM]->(ph)
                RETURN ph.name AS name LIMIT 1
            """, parent_name=parent_phage_name, construct_id=construct_id)
            if not result.single():
                print(f"⚠️ 亲本噬菌体 '{parent_phage_name}' 未找到，跳过关联")

        # IMPLEMENTS 工程策略
        for strategy_id in strategy_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (es:EngineeringStrategy {strategy_id: $strategy_id})
                MERGE (ec)-[:IMPLEMENTS]->(es)
            """, construct_id=construct_id, strategy_id=strategy_id)

        # TARGETS 目标病原
        for pathogen_id in target_pathogen_ids:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                MERGE (ec)-[:TARGETS]->(p)
            """, construct_id=construct_id, pathogen_id=pathogen_id)

        # DEVELOPED_BY 开发者组织
        resolved_org_id = _resolve_developer_org_id(session, program_id, organization_id)
        linked_org = False
        if resolved_org_id:
            session.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $construct_id})
                MATCH (o:Organization {organization_id: $oid})
                MERGE (ec)-[:DEVELOPED_BY]->(o)
            """, construct_id=construct_id, oid=resolved_org_id)
            linked_org = True

        # ASSOCIATED_WITH 研发项目
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

        write_audit_event(
            driver, action_type="CREATE",
            object_type="EngineeredPhageConstruct", object_id=construct_id,
            actor_id=actor_id,
            delta={"public_name": public_name, "construct_status": construct_status,
                   "strategy_ids": strategy_ids,
                   "target_pathogen_ids": target_pathogen_ids,
                   "target_pathogen_species": target_pathogen_species,
                   "organization_id": resolved_org_id, "program_id": program_id,
                   "linked_org": linked_org, "linked_program": linked_program},
            reason=f"创建工程化构建体: {public_name or construct_code or construct_id}",
        )
        return construct_id


def link_construct_to_organization(driver, construct_id, organization_id, actor_id="system"):
    """建立 (构建体)-[:DEVELOPED_BY]->(组织) 关系（幂等）。"""
    with driver.session() as s:
        ec = s.run("MATCH (ec:EngineeredPhageConstruct {construct_id: $cid}) RETURN ec LIMIT 1",
                   cid=construct_id).single()
        if not ec:
            raise ValueError(f"EngineeredPhageConstruct {construct_id} 不存在")
        org = s.run("MATCH (o:Organization {organization_id: $oid}) RETURN o LIMIT 1",
                    oid=organization_id).single()
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
        driver, action_type="LINK_CREATE",
        object_type="EngineeredPhageConstruct", object_id=construct_id,
        actor_id=actor_id,
        delta={"relation": "DEVELOPED_BY", "organization_id": organization_id},
        reason=f"构建体 {construct_id} 关联开发者 {organization_id}",
    )
    return True


def backfill_construct_developed_by(driver, actor_id="backfill"):
    """
    回填 DEVELOPED_BY 关系：
    从 (构建体)-ASSOCIATED_WITH->(项目)<-DEVELOPS-(组织) 推导。
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
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (o:Organization {organization_id: $oid})
                MERGE (ec)-[:DEVELOPED_BY]->(o)
            """, cid=r["cid"], oid=r["oid"])
            created += 1
            details.append({"construct_id": r["cid"], "organization_id": r["oid"]})

    if created > 0:
        write_audit_event(
            driver, action_type="LINK_CREATE",
            object_type="EngineeredPhageConstruct", object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_developed_by": created, "details": details},
            reason=f"回填 DEVELOPED_BY 关系：{created} 条",
        )
    return {"created": created, "details": details}


def get_constructs_by_strategy(driver, strategy_id):
    """查询实现某策略的所有构建体，附带亲本噬菌体 / 开发者 / 目标病原。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $strategy_id})
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DEVELOPED_BY]->(o:Organization)
            WITH ec, ph, o, COLLECT(DISTINCT p.species) AS target_species
            RETURN ec.construct_id AS id, ec.public_name AS name,
                   ec.construct_status AS status, ph.name AS parent_phage,
                   o.canonical_name AS developer,
                   target_species AS target_pathogens
            ORDER BY ec.created_at DESC
        """, strategy_id=strategy_id)
        return [dict(record) for record in result]


def link_program_to_construct(driver, program_id, construct_id,
                              relationship_type="ASSOCIATED_WITH", actor_id="system"):
    """
    建立 (项目)-[:ASSOCIATED_WITH/USES_CONSTRUCT]->(构建体) 关系。

    同时自动补 DEVELOPED_BY 关系。
    """
    allowed_types = {"ASSOCIATED_WITH", "USES_CONSTRUCT"}
    if relationship_type not in allowed_types:
        raise ValueError(f"不支持的关系类型: {relationship_type}，仅允许 {sorted(allowed_types)}")

    with driver.session() as session:
        # 校验两端存在
        prog_check = session.run("MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d",
                                 pid=program_id).single()
        if not prog_check:
            raise ValueError(f"项目 {program_id} 不存在")
        const_check = session.run("MATCH (ec:EngineeredPhageConstruct {construct_id: $cid}) RETURN ec",
                                  cid=construct_id).single()
        if not const_check:
            raise ValueError(f"构建体 {construct_id} 不存在")

        # 幂等
        existing = session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            OPTIONAL MATCH (ec)-[r:ASSOCIATED_WITH]->(d)
            RETURN r IS NOT NULL AS exists
        """, pid=program_id, cid=construct_id).single()
        if existing and existing['exists']:
            return True

        # 建立关系（当前实现固定用 ASSOCIATED_WITH）
        session.run("""
            MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MERGE (ec)-[:ASSOCIATED_WITH]->(d)
            SET ec.updated_at = datetime()
        """, pid=program_id, cid=construct_id)

        # 自动补 DEVELOPED_BY
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
            driver, action_type="LINK_CREATE",
            object_type="EngineeredPhageConstruct", object_id=construct_id,
            actor_id=actor_id,
            delta={"relation": "ASSOCIATED_WITH", "program_id": program_id},
            reason=f"构建体 {construct_id} 关联项目 {program_id}",
        )
        return True


def get_constructs_by_program(driver, program_id):
    """
    查询某项目的所有构建体（同时走 ASSOCIATED_WITH 和 USES_CONSTRUCT 两条路径）。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            OPTIONAL MATCH (ec1:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d)
            OPTIONAL MATCH (d)-[:USES_CONSTRUCT]->(ec2:EngineeredPhageConstruct)
            WITH d, COLLECT(DISTINCT ec1) + COLLECT(DISTINCT ec2) AS constructs
            UNWIND constructs AS ec
            WITH DISTINCT ec WHERE ec IS NOT NULL
            OPTIONAL MATCH (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            OPTIONAL MATCH (ec)-[:TARGETS]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DEVELOPED_BY]->(o:Organization)
            OPTIONAL MATCH (tc:TechnicalClaim)-[:CLAIMS_ABOUT]->(ec)
            OPTIONAL MATCH (tr:TechnicalResult)-[:RESULT_FOR]->(ec)
            WITH ec, es.strategy_type AS strategy_type, ph.name AS parent_phage,
                 o.canonical_name AS developer,
                 COLLECT(DISTINCT p.species) AS target_pathogens,
                 COLLECT(DISTINCT tc.claim_type) AS claim_types,
                 COLLECT(DISTINCT tr.result_type) AS result_types
            RETURN ec.construct_id AS id, ec.public_name AS name,
                   ec.construct_status AS status, strategy_type, parent_phage,
                   developer, target_pathogens, claim_types, result_types
            ORDER BY ec.created_at DESC
        """, pid=program_id)
        return [dict(record) for record in result]


def get_programs_by_strategy(driver, strategy_id):
    """
    查询实现某策略的所有项目（同时走 ASSOCIATED_WITH 和 USES_CONSTRUCT 两条路径）。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (ec:EngineeredPhageConstruct)-[:IMPLEMENTS]->(es:EngineeringStrategy {strategy_id: $sid})
            OPTIONAL MATCH (ec)-[:ASSOCIATED_WITH]->(d1:DevelopmentProgram)
            OPTIONAL MATCH (d2:DevelopmentProgram)-[:USES_CONSTRUCT]->(ec)
            WITH ec, COLLECT(DISTINCT d1) + COLLECT(DISTINCT d2) AS progs
            UNWIND progs AS d
            WITH DISTINCT ec, d WHERE d IS NOT NULL
            OPTIONAL MATCH (d)-[:TARGETS_PATHOGEN]->(p:Pathogen)
            OPTIONAL MATCH (ec)-[:DERIVED_FROM]->(ph:Phage)
            WITH d, ec, ph, COLLECT(DISTINCT p.species) AS target_pathogens
            RETURN d.program_id AS program_id, d.canonical_name AS program_name,
                   d.development_stage AS stage, d.program_status AS status,
                   ec.public_name AS construct_name,
                   ec.construct_status AS construct_status,
                   ph.name AS parent_phage, target_pathogens
            ORDER BY d.created_at DESC
        """, sid=strategy_id)
        return [dict(record) for record in result]


# ==================================================================
# Part 2: EngineeringModification (原 modification_service.py)
# ==================================================================

# 受控词表：改造类型
MODIFICATION_TYPES = {"insertion", "deletion", "replacement", "editing", "display", "other"}


def generate_modification_id() -> str:
    """生成工程改造 ID（格式：ENG:MOD:XXXXXXXX）。"""
    return f"ENG:MOD:{uuid.uuid4().hex[:8].upper()}"


def create_engineering_modification(driver, modification_type, modification_summary,
                                    construct_id=None, target_component=None,
                                    actor_id="system"):
    """
    创建工程改造（EngineeringModification）。

    可选：建立 (构建体)-[:HAS_MODIFICATION]->(改造) 关系。
    """
    if modification_type not in MODIFICATION_TYPES:
        raise ValueError(f"modification_type 必须是 {sorted(MODIFICATION_TYPES)} 之一")
    modification_id = generate_modification_id()
    with driver.session() as s:
        s.run("""
            CREATE (em:EngineeringModification {
                modification_id: $mid, modification_type: $mtype,
                modification_summary: $summary, target_component: $comp,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, mid=modification_id, mtype=modification_type,
             summary=modification_summary, comp=target_component)
        if construct_id:
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (em:EngineeringModification {modification_id: $mid})
                MERGE (ec)-[:HAS_MODIFICATION]->(em)
            """, cid=construct_id, mid=modification_id)

    write_audit_event(
        driver, action_type="CREATE",
        object_type="EngineeringModification", object_id=modification_id,
        actor_id=actor_id,
        delta={"modification_type": modification_type, "construct_id": construct_id},
        reason=f"创建工程改造: {modification_type}",
    )
    return modification_id


def list_modifications(driver, construct_id=None, limit=100):
    """列出工程改造（可按构建体过滤）。"""
    with driver.session() as s:
        if construct_id:
            rows = list(s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                      -[:HAS_MODIFICATION]->(em:EngineeringModification)
                RETURN em.modification_id AS modification_id,
                       em.modification_type AS modification_type,
                       em.modification_summary AS modification_summary,
                       em.target_component AS target_component
                LIMIT $limit
            """, cid=construct_id, limit=limit))
        else:
            rows = list(s.run("""
                MATCH (em:EngineeringModification)
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:HAS_MODIFICATION]->(em)
                RETURN em.modification_id AS modification_id,
                       em.modification_type AS modification_type,
                       em.modification_summary AS modification_summary,
                       collect(DISTINCT ec.public_name) AS constructs
                LIMIT $limit
            """, limit=limit))
    return [dict(r) for r in rows]


# ==================================================================
# Part 3: DeliveryPayload (原 payload_service.py)
# ==================================================================

# 受控词表：载荷类型
PAYLOAD_TYPES = {
    "crispr_cas", "anti_crispr", "toxin_antitoxin", "biofilm_enzyme",
    "immune_modulator", "antibiotic", "gene_editor", "other",
}


def generate_payload_id() -> str:
    """生成递送载荷 ID（格式：ENG:PAYLOAD:XXXXXXXX）。"""
    return f"ENG:PAYLOAD:{uuid.uuid4().hex[:8].upper()}"


def create_delivery_payload(driver, payload_type, payload_description,
                            construct_id=None, target_pathogen_id=None,
                            actor_id="system"):
    """
    创建递送载荷（DeliveryPayload）。

    可选：
        - (构建体)-[:CARRIES_PAYLOAD]->(载荷)
        - (载荷)-[:TARGETS]->(病原)
    """
    if payload_type not in PAYLOAD_TYPES:
        raise ValueError(f"payload_type 必须是 {sorted(PAYLOAD_TYPES)} 之一")
    payload_id = generate_payload_id()
    with driver.session() as s:
        s.run("""
            CREATE (pl:DeliveryPayload {
                payload_id: $pid, payload_type: $ptype,
                payload_description: $desc,
                review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            })
        """, pid=payload_id, ptype=payload_type, desc=payload_description)

        # 关联构建体
        if construct_id:
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (pl:DeliveryPayload {payload_id: $pid})
                MERGE (ec)-[:CARRIES_PAYLOAD]->(pl)
            """, cid=construct_id, pid=payload_id)
        # 关联目标病原
        if target_pathogen_id:
            s.run("""
                MATCH (pl:DeliveryPayload {payload_id: $pid})
                MATCH (p:Pathogen {pathogen_id: $pathid})
                MERGE (pl)-[:TARGETS]->(p)
            """, pid=payload_id, pathid=target_pathogen_id)

    write_audit_event(
        driver, action_type="CREATE",
        object_type="DeliveryPayload", object_id=payload_id,
        actor_id=actor_id,
        delta={"payload_type": payload_type, "construct_id": construct_id},
        reason=f"创建递送载荷: {payload_type}",
    )
    return payload_id


def list_payloads(driver, construct_id=None, limit=100):
    """列出递送载荷（可按构建体过滤）。"""
    with driver.session() as s:
        if construct_id:
            rows = list(s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                      -[:CARRIES_PAYLOAD]->(pl:DeliveryPayload)
                OPTIONAL MATCH (pl)-[:TARGETS]->(p:Pathogen)
                RETURN pl.payload_id AS payload_id,
                       pl.payload_type AS payload_type,
                       pl.payload_description AS payload_description,
                       collect(DISTINCT p.species) AS targets
                LIMIT $limit
            """, cid=construct_id, limit=limit))
        else:
            rows = list(s.run("""
                MATCH (pl:DeliveryPayload)
                OPTIONAL MATCH (ec:EngineeredPhageConstruct)-[:CARRIES_PAYLOAD]->(pl)
                RETURN pl.payload_id AS payload_id,
                       pl.payload_type AS payload_type,
                       pl.payload_description AS payload_description,
                       collect(DISTINCT ec.public_name) AS constructs
                LIMIT $limit
            """, limit=limit))
    return [dict(r) for r in rows]