# src/engineering_intelligence/payload_service.py
"""
DeliveryPayload 服务（PRD 5.3 / 9.3）

关系：
    (EngineeredPhageConstruct)-[:CARRIES_PAYLOAD]->(DeliveryPayload)
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


PAYLOAD_TYPES = {
    "crispr_cas", "anti_crispr", "toxin_antitoxin", "biofilm_enzyme",
    "immune_modulator", "antibiotic", "gene_editor", "other",
}


def generate_payload_id() -> str:
    return f"ENG:PAYLOAD:{uuid.uuid4().hex[:8].upper()}"


def create_delivery_payload(
    driver: Driver,
    payload_type: str,
    payload_description: str,
    construct_id: Optional[str] = None,
    target_pathogen_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    if payload_type not in PAYLOAD_TYPES:
        raise ValueError(f"payload_type 必须是 {sorted(PAYLOAD_TYPES)} 之一")

    payload_id = generate_payload_id()

    with driver.session() as s:
        s.run("""
            CREATE (pl:DeliveryPayload {
                payload_id: $pid,
                payload_type: $ptype,
                payload_description: $desc,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, pid=payload_id, ptype=payload_type, desc=payload_description)

        if construct_id:
            s.run("""
                MATCH (ec:EngineeredPhageConstruct {construct_id: $cid})
                MATCH (pl:DeliveryPayload {payload_id: $pid})
                MERGE (ec)-[:CARRIES_PAYLOAD]->(pl)
            """, cid=construct_id, pid=payload_id)

        if target_pathogen_id:
            s.run("""
                MATCH (pl:DeliveryPayload {payload_id: $pid})
                MATCH (p:Pathogen {pathogen_id: $pathid})
                MERGE (pl)-[:TARGETS]->(p)
            """, pid=payload_id, pathid=target_pathogen_id)

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="DeliveryPayload",
        object_id=payload_id,
        actor_id=actor_id,
        delta={"payload_type": payload_type, "construct_id": construct_id},
        reason=f"创建递送载荷: {payload_type}",
    )
    return payload_id


def list_payloads(
    driver: Driver,
    construct_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
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