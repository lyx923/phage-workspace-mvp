# src/ci/indication_service.py
"""
ClinicalIndication 服务（PRD 7.2 / 5.2）

关系：
    (DevelopmentProgram)-[:ADDRESSES]->(ClinicalIndication)
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


def generate_indication_id() -> str:
    return f"CI:IND:{uuid.uuid4().hex[:8].upper()}"


def create_indication(
    driver: Driver,
    name: str,
    infection_site: Optional[str] = None,
    pathogen_scope: Optional[str] = None,
    disease_stage: Optional[str] = None,
    standard_term: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """创建或复用 ClinicalIndication（幂等：按 name 查重）"""
    if not name or not name.strip():
        raise ValueError("name 不能为空")
    name = name.strip()

    with driver.session() as s:
        existing = s.run("""
            MATCH (ci:ClinicalIndication)
            WHERE toLower(ci.name) = toLower($name)
            RETURN ci.indication_id AS iid LIMIT 1
        """, name=name).single()
        if existing:
            return existing["iid"]

        indication_id = generate_indication_id()
        s.run("""
            CREATE (ci:ClinicalIndication {
                indication_id: $iid,
                name: $name,
                infection_site: $site,
                pathogen_scope: $scope,
                disease_stage: $stage,
                standard_term: $term,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            })
        """, iid=indication_id, name=name,
             site=infection_site, scope=pathogen_scope,
             stage=disease_stage, term=standard_term)

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="ClinicalIndication",
        object_id=indication_id,
        actor_id=actor_id,
        delta={"name": name},
        reason=f"创建适应症: {name}",
    )
    return indication_id


def link_program_to_indication(
    driver: Driver,
    program_id: str,
    indication_id: str,
    actor_id: str = "system",
) -> bool:
    """建立 (DevelopmentProgram)-[:ADDRESSES]->(ClinicalIndication)"""
    with driver.session() as s:
        ok = s.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})
            MATCH (ci:ClinicalIndication {indication_id: $iid})
            MERGE (d)-[:ADDRESSES]->(ci)
            RETURN d.canonical_name AS pname, ci.name AS iname
        """, pid=program_id, iid=indication_id).single()
        if not ok:
            raise ValueError("program 或 indication 不存在")

    write_audit_event(
        driver,
        action_type="LINK_CREATE",
        object_type="ClinicalIndication",
        object_id=indication_id,
        actor_id=actor_id,
        delta={"program_id": program_id},
        reason=f"项目 {ok['pname']} 关联适应症 {ok['iname']}",
    )
    return True


def list_indications(
    driver: Driver,
    limit: int = 100,
) -> List[Dict]:
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (ci:ClinicalIndication)
            OPTIONAL MATCH (d:DevelopmentProgram)-[:ADDRESSES]->(ci)
            RETURN ci.indication_id AS indication_id,
                   ci.name AS name,
                   ci.infection_site AS infection_site,
                   ci.pathogen_scope AS pathogen_scope,
                   ci.disease_stage AS disease_stage,
                   ci.standard_term AS standard_term,
                   ci.review_status AS review_status,
                   count(DISTINCT d) AS program_count
            ORDER BY ci.name
            LIMIT $limit
        """, limit=limit))
    return [dict(r) for r in rows]