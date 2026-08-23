# src/ci/program_service.py 实现研发项目的创建及与组织的关联
import uuid
from neo4j import Driver
from src.foundation.audit_service import log_action
from typing import Optional, List

def generate_program_id() -> str:
    return f"CI:PROG:{uuid.uuid4().hex[:8].upper()}"

def create_development_program(
    driver: Driver,
    organization_id: str,
    canonical_name: str,
    program_type: str = "therapeutic",
    development_stage: str = "discovery",
    modality: Optional[str] = None,
    target_pathogen_ids: Optional[List[str]] = None,
    actor_id: str = "system"
) -> str:
    """
    创建研发项目并建立 (Organization)-[:DEVELOPS]->(Program) 关系
    """
    prog_id = generate_program_id()
    target_pathogen_ids = target_pathogen_ids or []
    
    with driver.session() as session:
        # 检查组织是否存在
        org_check = session.run("MATCH (o:Organization {organization_id: $oid}) RETURN o", oid=organization_id).single()
        if not org_check:
            raise ValueError(f"组织 {organization_id} 不存在")
        
        # 创建 Program
        session.run("""
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
        """, prog_id=prog_id, name=canonical_name, p_type=program_type,
           stage=development_stage, modality=modality, oid=organization_id)
        
        # 关联病原菌（如果有）
        if target_pathogen_ids:
            for pid in target_pathogen_ids:
                session.run("""
                    MATCH (d:DevelopmentProgram {program_id: $prog_id})
                    MATCH (p:Pathogen {pathogen_id: $pid})
                    CREATE (d)-[:TARGETS]->(p)
                """, prog_id=prog_id, pid=pid)
        
        log_action(driver, domain="ci", action_type="CREATE_PROGRAM",
                   object_type="DevelopmentProgram", object_id=prog_id, actor_id=actor_id)
        
        return prog_id

def update_program_status(driver: Driver, program_id: str, new_status: str, source_event_id: str, actor_id: str):
    """PRD 12.3 Action: Update Program Status"""
    with driver.session() as session:
        # 获取旧状态用于审计
        old = session.run("MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d.program_status AS status", pid=program_id).single()
        if not old:
            raise ValueError(f"项目 {program_id} 不存在")
        
        session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            SET d.program_status = $new_status, d.updated_at = datetime()
        """, pid=program_id, new_status=new_status)
        
        # 关联事件
        session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (e:IntelligenceEvent {event_id: $source_event_id})
            CREATE (e)-[:AFFECTS]->(d)
        """, pid=program_id, source_event_id=source_event_id)
        
        log_action(driver, domain="ci", action_type="UPDATE_PROGRAM_STATUS",
                   object_type="DevelopmentProgram", object_id=program_id, actor_id=actor_id,
                   before_snapshot={"status": old['status']}, after_snapshot={"status": new_status})