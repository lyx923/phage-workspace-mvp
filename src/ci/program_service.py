# src/ci/program_service.py 实现研发项目的创建及与组织的关联
import uuid
from typing import Optional, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event
from src.shared.pathogen_service import get_or_create_pathogen


def generate_program_id() -> str:
    """
    生成研发项目 ID。

    Returns:
        str: 格式为 CI:PROG:XXXXXXXX 的项目唯一标识符
    """
    return f"CI:PROG:{uuid.uuid4().hex[:8].upper()}"


def create_development_program(
    driver: Driver,
    organization_id: str,
    canonical_name: str,
    program_type: str = "therapeutic",
    development_stage: str = "discovery",
    modality: Optional[str] = None,
    target_pathogen_species: Optional[List[str]] = None,
    strategy_ids: Optional[List[str]] = None,   # v0.6 P1-6：直接关联 USES_STRATEGY
    actor_id: str = "system",
) -> str:
    """
    创建研发项目（PRD 12.1）。

    自动建立：
        - (Organization)-[:DEVELOPS]->(Program)
        - (Program)-[:TARGETS_PATHOGEN]->(Pathogen)  [按物种自动创建或复用 Pathogen 节点]
        - (Program)-[:USES_STRATEGY]->(EngineeringStrategy)  [v0.6 新增，PRD 11.1]

    Args:
        driver: Neo4j 数据库驱动
        organization_id: 所属组织 ID
        canonical_name: 项目规范名称
        program_type: 项目类型
        development_stage: 研发阶段
        modality: 模态
        target_pathogen_species: 靶向病原体物种列表
        strategy_ids: 关联的 EngineeringStrategy.strategy_id 列表（可选）
        actor_id: 操作者标识

    Returns:
        str: 创建的项目 ID（CI:PROG:XXXXXXXX）
    """
    target_pathogen_species = target_pathogen_species or []
    strategy_ids = strategy_ids or []
    prog_id = generate_program_id()

    with driver.session() as session:
        # 1. 检查组织是否存在
        org_check = session.run(
            "MATCH (o:Organization {organization_id: $oid}) RETURN o",
            oid=organization_id,
        ).single()
        if not org_check:
            raise ValueError(f"组织 {organization_id} 不存在")

        # 2. 创建 Program 节点
        session.run(
            """
            CREATE (d:DevelopmentProgram {
                program_id: $prog_id,
                canonical_name: $name,
                program_type: $p_type,
                development_stage: $stage,
                modality: $modality,
                program_status: 'active',
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
            WITH d
            MATCH (o:Organization {organization_id: $oid})
            CREATE (o)-[:DEVELOPS]->(d)
            """,
            prog_id=prog_id,
            name=canonical_name,
            p_type=program_type,
            stage=development_stage,
            modality=modality,
            oid=organization_id,
        )

        # 3. 关联病原体
        for species in target_pathogen_species:
            pathogen_id = get_or_create_pathogen(
                driver,
                species=species,
                actor_id=actor_id,
            )
            session.run(
                """
                MATCH (d:DevelopmentProgram {program_id: $prog_id})
                MATCH (p:Pathogen {pathogen_id: $pathogen_id})
                MERGE (d)-[:TARGETS_PATHOGEN]->(p)
                """,
                prog_id=prog_id,
                pathogen_id=pathogen_id,
            )

        # 4. 关联工程策略（v0.6 P1-6：直接建立 USES_STRATEGY）
        for sid in strategy_ids:
            es_chk = session.run(
                "MATCH (es:EngineeringStrategy {strategy_id: $sid}) RETURN es LIMIT 1",
                sid=sid,
            ).single()
            if not es_chk:
                print(f"⚠️ EngineeringStrategy {sid} 不存在，跳过 USES_STRATEGY")
                continue
            session.run(
                """
                MATCH (d:DevelopmentProgram {program_id: $prog_id})
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                MERGE (d)-[:USES_STRATEGY]->(es)
                """,
                prog_id=prog_id,
                sid=sid,
            )

        # 5. 审计日志
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="DevelopmentProgram",
            object_id=prog_id,
            actor_id=actor_id,
            delta={
                "canonical_name": canonical_name,
                "organization_id": organization_id,
                "target_pathogen_species": target_pathogen_species,
                "strategy_ids": strategy_ids,
            },
            reason=f"创建研发项目: {canonical_name}",
        )

        return prog_id


def link_program_to_strategy(
    driver: Driver,
    program_id: str,
    strategy_id: str,
    actor_id: str = "system",
) -> bool:
    """
    v0.6 P1-6：建立 (DevelopmentProgram)-[:USES_STRATEGY]->(EngineeringStrategy) 关系。
    幂等。
    """
    with driver.session() as s:
        d = s.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d LIMIT 1",
            pid=program_id,
        ).single()
        if not d:
            raise ValueError(f"DevelopmentProgram {program_id} 不存在")
        es = s.run(
            "MATCH (es:EngineeringStrategy {strategy_id: $sid}) RETURN es LIMIT 1",
            sid=strategy_id,
        ).single()
        if not es:
            raise ValueError(f"EngineeringStrategy {strategy_id} 不存在")

        existing = s.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:USES_STRATEGY]->(es:EngineeringStrategy {strategy_id: $sid})
            RETURN 1 AS x LIMIT 1
            """,
            pid=program_id,
            sid=strategy_id,
        ).single()
        if existing:
            return True

        s.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (es:EngineeringStrategy {strategy_id: $sid})
            MERGE (d)-[:USES_STRATEGY]->(es)
            """,
            pid=program_id,
            sid=strategy_id,
        )

    write_audit_event(
        driver,
        action_type="LINK_CREATE",
        object_type="DevelopmentProgram",
        object_id=program_id,
        actor_id=actor_id,
        delta={
            "relation": "USES_STRATEGY",
            "strategy_id": strategy_id,
        },
        reason=f"项目 {program_id} 关联策略 {strategy_id}",
    )
    return True


def backfill_program_uses_strategy(
    driver: Driver,
    actor_id: str = "backfill",
) -> dict:
    """
    v0.6 P1-6 backfill：
    从已有的 (ec:EngineeredPhageConstruct)-[:ASSOCIATED_WITH]->(d:DevelopmentProgram)
    和 (ec)-[:IMPLEMENTS]->(es:EngineeringStrategy)
    推导 (d)-[:USES_STRATEGY]->(es)，幂等。

    返回：{"created": N, "details": [...]}
    """
    created = 0
    details = []

    with driver.session() as s:
        # 找出所有应该有但还没有 USES_STRATEGY 的 (d, es) 组合
        rows = list(s.run("""
            MATCH (d:DevelopmentProgram)<-[:ASSOCIATED_WITH]-(ec:EngineeredPhageConstruct)
                  -[:IMPLEMENTS]->(es:EngineeringStrategy)
            WHERE NOT (d)-[:USES_STRATEGY]->(es)
            RETURN DISTINCT d.program_id AS pid, es.strategy_id AS sid
        """))

        for r in rows:
            pid = r["pid"]
            sid = r["sid"]
            s.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (es:EngineeringStrategy {strategy_id: $sid})
                MERGE (d)-[:USES_STRATEGY]->(es)
            """, pid=pid, sid=sid)
            created += 1
            details.append({"program_id": pid, "strategy_id": sid})

    if created > 0:
        write_audit_event(
            driver,
            action_type="LINK_CREATE",
            object_type="DevelopmentProgram",
            object_id="bulk_backfill",
            actor_id=actor_id,
            delta={"created_usES_STRATEGY": created, "details": details},
            reason=f"回填 USES_STRATEGY 关系：{created} 条",
        )

    return {"created": created, "details": details}


def update_program_status(
    driver: Driver,
    program_id: str,
    new_status: str,
    source_event_id: str,
    actor_id: str,
):
    """
    更新研发项目状态（PRD 12.3）。
    """
    with driver.session() as session:
        old = session.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d.program_status AS status",
            pid=program_id,
        ).single()
        if not old:
            raise ValueError(f"项目 {program_id} 不存在")

        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            SET d.program_status = $new_status, d.updated_at = datetime()
            """,
            pid=program_id,
            new_status=new_status,
        )

        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (e:IntelligenceEvent {event_id: $source_event_id})
            MERGE (e)-[:AFFECTS]->(d)
            """,
            pid=program_id,
            source_event_id=source_event_id,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="DevelopmentProgram",
            object_id=program_id,
            actor_id=actor_id,
            delta={"status": {"before": old["status"], "after": new_status}},
            reason=f"项目状态从 {old['status']} 更新为 {new_status}",
        )