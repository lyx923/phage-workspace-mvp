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
    actor_id: str = "system",
) -> str:
    """
    创建研发项目（PRD 12.1）。
    
    自动建立：
        - (Organization)-[:DEVELOPS]->(Program)
        - (Program)-[:TARGETS_PATHOGEN]->(Pathogen)  [按物种自动创建或复用 Pathogen 节点]
    
    Args:
        driver: Neo4j 数据库驱动
        organization_id: 所属组织 ID
        canonical_name: 项目规范名称
        program_type: 项目类型（therapeutic / diagnostic / platform / research）
        development_stage: 研发阶段（discovery / preclinical / phase_1 等）
        modality: 模态（natural_phage / engineered_phage / cocktail）
        target_pathogen_species: 靶向病原体物种列表（如 ["Klebsiella pneumoniae"]）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 创建的项目 ID（CI:PROG:XXXXXXXX）
    
    Raises:
        ValueError: 当组织不存在时抛出
    """
    target_pathogen_species = target_pathogen_species or []
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

        # 3. 关联病原体（使用 species 自动获取或创建 Pathogen 节点）
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
                CREATE (d)-[:TARGETS_PATHOGEN]->(p)
                """,
                prog_id=prog_id,
                pathogen_id=pathogen_id,
            )

        # 4. 审计日志
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
            },
            reason=f"创建研发项目: {canonical_name}",
        )

        return prog_id


def update_program_status(
    driver: Driver,
    program_id: str,
    new_status: str,
    source_event_id: str,
    actor_id: str,
):
    """
    更新研发项目状态（PRD 12.3）。
    
    当项目状态变化时，关联触发该变化的 IntelligenceEvent。
    
    Args:
        driver: Neo4j 数据库驱动
        program_id: 项目 ID
        new_status: 新状态
        source_event_id: 触发状态变化的情报事件 ID
        actor_id: 操作者标识
    
    Raises:
        ValueError: 当项目不存在时抛出
    """
    with driver.session() as session:
        # 1. 查询当前状态
        old = session.run(
            "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d.program_status AS status",
            pid=program_id,
        ).single()
        if not old:
            raise ValueError(f"项目 {program_id} 不存在")

        # 2. 更新状态
        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            SET d.program_status = $new_status, d.updated_at = datetime()
            """,
            pid=program_id,
            new_status=new_status,
        )

        # 3. 关联触发事件
        session.run(
            """
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (e:IntelligenceEvent {event_id: $source_event_id})
            CREATE (e)-[:AFFECTS]->(d)
            """,
            pid=program_id,
            source_event_id=source_event_id,
        )

        # 4. 审计日志
        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="DevelopmentProgram",
            object_id=program_id,
            actor_id=actor_id,
            delta={"status": {"before": old["status"], "after": new_status}},
            reason=f"项目状态从 {old['status']} 更新为 {new_status}",
        )