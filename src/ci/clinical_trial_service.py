# src/ci/clinical_trial_service.py
"""
临床试验（ClinicalTrial）服务
符合 PRD 5.2

边界原则：
- 只记录公开试验登记信息
- 试验状态以登记平台为准，不自动推断成败
"""
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


TRIAL_PHASES = {
    "preclinical", "phase_1", "phase_1_2", "phase_2",
    "phase_2b", "phase_3", "phase_4", "unknown",
}

TRIAL_STATUSES = {
    "not_yet_recruiting", "recruiting", "active",
    "completed", "terminated", "suspended", "withdrawn", "unknown",
}


def generate_trial_id() -> str:
    return f"CI:TRIAL:{uuid.uuid4().hex[:8].upper()}"


def create_clinical_trial(
    driver: Driver,
    title: str,
    nct_id: Optional[str] = None,
    phase: str = "unknown",
    status: str = "unknown",
    indication: Optional[str] = None,
    sponsor: Optional[str] = None,
    organization_id: Optional[str] = None,
    program_id: Optional[str] = None,
    start_date: Optional[str] = None,
    completion_date: Optional[str] = None,
    enrollment: Optional[int] = None,
    primary_endpoint: Optional[str] = None,
    source_url: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建临床试验节点。

    关系：
        (DevelopmentProgram)-[:HAS_TRIAL]->(ClinicalTrial)
        (Organization)-[:SPONSORS]->(ClinicalTrial)
    """
    if phase not in TRIAL_PHASES:
        raise ValueError(f"phase 必须是 {TRIAL_PHASES} 之一")
    if status not in TRIAL_STATUSES:
        raise ValueError(f"status 必须是 {TRIAL_STATUSES} 之一")

    trial_id = generate_trial_id()

    with driver.session() as session:
        # 去重：按 NCT 号
        if nct_id:
            existing = session.run("""
                MATCH (ct:ClinicalTrial {nct_id: $nct})
                RETURN ct.trial_id AS id LIMIT 1
            """, nct=nct_id).single()
            if existing:
                print(f"ℹ️ 临床试验 {nct_id} 已存在: {existing['id']}")
                return existing["id"]

        session.run("""
            CREATE (ct:ClinicalTrial {
                trial_id: $tid,
                nct_id: $nct_id,
                title: $title,
                phase: $phase,
                status: $status,
                indication: $indication,
                sponsor: $sponsor,
                start_date: $start_date,
                completion_date: $completion_date,
                enrollment: $enrollment,
                primary_endpoint: $primary_endpoint,
                source_url: $source_url,
                review_status: 'pending',
                last_verified_at: datetime(),
                created_at: datetime(),
                updated_at: datetime()
            })
        """,
        tid=trial_id,
        nct_id=nct_id,
        title=title,
        phase=phase,
        status=status,
        indication=indication,
        sponsor=sponsor,
        start_date=start_date,
        completion_date=completion_date,
        enrollment=enrollment,
        primary_endpoint=primary_endpoint,
        source_url=source_url,
        )

        if program_id:
            session.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (ct:ClinicalTrial {trial_id: $tid})
                MERGE (d)-[:HAS_TRIAL]->(ct)
            """, pid=program_id, tid=trial_id)

        if organization_id:
            session.run("""
                MATCH (o:Organization {organization_id: $oid})
                MATCH (ct:ClinicalTrial {trial_id: $tid})
                MERGE (o)-[:SPONSORS]->(ct)
            """, oid=organization_id, tid=trial_id)

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="ClinicalTrial",
            object_id=trial_id,
            actor_id=actor_id,
            delta={
                "nct_id": nct_id,
                "phase": phase,
                "status": status,
                "sponsor": sponsor,
            },
            reason=f"创建临床试验: {title[:60]}",
        )

    return trial_id


def get_clinical_trial(driver: Driver, trial_id: str) -> Optional[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (ct:ClinicalTrial {trial_id: $tid})
            OPTIONAL MATCH (d:DevelopmentProgram)-[:HAS_TRIAL]->(ct)
            OPTIONAL MATCH (o:Organization)-[:SPONSORS]->(ct)
            RETURN ct,
                   collect(DISTINCT d.canonical_name) AS programs,
                   collect(DISTINCT o.canonical_name) AS sponsors
        """, tid=trial_id).single()
        if not r:
            return None
        data = dict(r["ct"])
        data["programs"] = r["programs"]
        data["sponsors"] = r["sponsors"]
        return data


def list_trials_for_program(driver: Driver, program_id: str) -> List[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:HAS_TRIAL]->(ct:ClinicalTrial)
            OPTIONAL MATCH (o:Organization)-[:SPONSORS]->(ct)
            RETURN ct.trial_id AS id,
                   ct.nct_id AS nct_id,
                   ct.title AS title,
                   ct.phase AS phase,
                   ct.status AS status,
                   ct.start_date AS start_date,
                   collect(DISTINCT o.canonical_name) AS sponsors
            ORDER BY ct.start_date DESC
        """, pid=program_id)
        return [dict(rec) for rec in r]


def list_trials_for_organization(driver: Driver, organization_id: str) -> List[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:SPONSORS]->(ct:ClinicalTrial)
            RETURN ct.trial_id AS id,
                   ct.nct_id AS nct_id,
                   ct.title AS title,
                   ct.phase AS phase,
                   ct.status AS status
            ORDER BY ct.start_date DESC
        """, oid=organization_id)
        return [dict(rec) for rec in r]