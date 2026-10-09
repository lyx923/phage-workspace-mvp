# src/engineering_intelligence/modification_service.py
"""
EngineeringModification 服务（PRD 9.3）

关系：
    (EngineeredPhageConstruct)-[:HAS_MODIFICATION]->(EngineeringModification)

边界：
- 只用于情报建模和公开证据比较，不用于生成可执行的基因工程操作步骤。
- modification_summary 必须是经过审核的、非操作性的描述。
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


MODIFICATION_TYPES = {"insertion", "deletion", "replacement", "editing", "display", "other"}


def generate_modification_id() -> str:
    return f"ENG:MOD:{uuid.uuid4().hex[:8].upper()}"


def create_engineering_modification(
    driver: Driver,
    modification_type: str,
    modification_summary: str,
    construct_id: Optional[str] = None,
    target_component: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    if modification_type not in MODIFICATION_TYPES:
        raise ValueError(f"modification_type 必须是 {sorted(MODIFICATION_TYPES)} 之一")

    modification_id = generate_modification_id()

    with driver.session() as s:
        s.run("""
            CREATE (em:EngineeringModification {
                modification_id: $mid,
                modification_type: $mtype,
                modification_summary: $summary,
                target_component: $comp,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
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
        driver,
        action_type="CREATE",
        object_type="EngineeringModification",
        object_id=modification_id,
        actor_id=actor_id,
        delta={"modification_type": modification_type, "construct_id": construct_id},
        reason=f"创建工程改造: {modification_type}",
    )
    return modification_id


def list_modifications(
    driver: Driver,
    construct_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
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