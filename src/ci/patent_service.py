# src/ci/patent_service.py
"""
专利族（PatentFamily）服务
符合 PRD 7.3

边界原则：
- 只记录公开权利要求、公开法律状态、公开申请人信息、内部审核后的摘要
- 不能把「专利申请」直接解释为「技术已实现或验证」
"""
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.shared.audit_service import write_audit_event


LEGAL_STATUSES = {"pending", "granted", "expired", "abandoned", "unknown"}


def generate_patent_family_id() -> str:
    return f"CI:PATENT:{uuid.uuid4().hex[:8].upper()}"


def create_patent_family(
    driver: Driver,
    title: str,
    priority_date: Optional[str] = None,
    application_numbers: Optional[List[str]] = None,
    publication_numbers: Optional[List[str]] = None,
    jurisdictions: Optional[List[str]] = None,
    applicants: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
    legal_status: str = "unknown",
    claim_scope_summary: Optional[str] = None,
    source_url: Optional[str] = None,
    organization_id: Optional[str] = None,
    program_ids: Optional[List[str]] = None,
    actor_id: str = "system",
) -> str:
    """
    创建专利族节点。

    关系：
        (Organization)-[:OWNS_PATENT]->(PatentFamily)
        (DevelopmentProgram)-[:COVERED_BY]->(PatentFamily)
    """
    if legal_status not in LEGAL_STATUSES:
        raise ValueError(f"legal_status 必须是 {LEGAL_STATUSES} 之一")

    application_numbers = application_numbers or []
    publication_numbers = publication_numbers or []
    jurisdictions = jurisdictions or []
    applicants = applicants or []
    assignees = assignees or []
    program_ids = program_ids or []

    patent_family_id = generate_patent_family_id()

    with driver.session() as session:
        # 去重：同一优先权号或公开号不重复建
        if priority_date and publication_numbers:
            existing = session.run("""
                MATCH (pf:PatentFamily)
                WHERE pf.priority_date = $pd
                  AND ANY(pub IN $pubs WHERE pub IN pf.publication_numbers)
                RETURN pf.patent_family_id AS id LIMIT 1
            """, pd=priority_date, pubs=publication_numbers).single()
            if existing:
                print(f"ℹ️ 疑似重复专利族，已存在: {existing['id']}")
                return existing["id"]

        session.run("""
            CREATE (pf:PatentFamily {
                patent_family_id: $pfid,
                title: $title,
                priority_date: $priority_date,
                application_numbers: $application_numbers,
                publication_numbers: $publication_numbers,
                jurisdictions: $jurisdictions,
                applicants: $applicants,
                assignees: $assignees,
                legal_status: $legal_status,
                claim_scope_summary: $claim_scope_summary,
                source_url: $source_url,
                review_status: 'pending',
                last_verified_at: datetime(),
                created_at: datetime(),
                updated_at: datetime()
            })
        """,
        pfid=patent_family_id,
        title=title,
        priority_date=priority_date,
        application_numbers=application_numbers,
        publication_numbers=publication_numbers,
        jurisdictions=jurisdictions,
        applicants=applicants,
        assignees=assignees,
        legal_status=legal_status,
        claim_scope_summary=claim_scope_summary,
        source_url=source_url,
        )

        # 关联组织
        if organization_id:
            session.run("""
                MATCH (o:Organization {organization_id: $oid})
                MATCH (pf:PatentFamily {patent_family_id: $pfid})
                MERGE (o)-[:OWNS_PATENT]->(pf)
            """, oid=organization_id, pfid=patent_family_id)

        # 关联研发项目
        for pid in program_ids:
            session.run("""
                MATCH (d:DevelopmentProgram {program_id: $pid})
                MATCH (pf:PatentFamily {patent_family_id: $pfid})
                MERGE (d)-[:COVERED_BY]->(pf)
            """, pid=pid, pfid=patent_family_id)

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="PatentFamily",
            object_id=patent_family_id,
            actor_id=actor_id,
            delta={
                "title": title,
                "legal_status": legal_status,
                "publication_numbers": publication_numbers,
                "organization_id": organization_id,
            },
            reason=f"创建专利族: {title[:60]}",
        )

    return patent_family_id


def get_patent_family(driver: Driver, patent_family_id: str) -> Optional[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (pf:PatentFamily {patent_family_id: $pfid})
            OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
            OPTIONAL MATCH (d:DevelopmentProgram)-[:COVERED_BY]->(pf)
            RETURN pf,
                   collect(DISTINCT o.canonical_name) AS owners,
                   collect(DISTINCT d.canonical_name) AS programs
        """, pfid=patent_family_id).single()
        if not r:
            return None
        data = dict(r["pf"])
        data["owners"] = r["owners"]
        data["programs"] = r["programs"]
        return data


def list_patent_families_for_program(driver: Driver, program_id: str) -> List[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (d:DevelopmentProgram {program_id: $pid})-[:COVERED_BY]->(pf:PatentFamily)
            OPTIONAL MATCH (o:Organization)-[:OWNS_PATENT]->(pf)
            RETURN pf.patent_family_id AS id,
                   pf.title AS title,
                   pf.legal_status AS legal_status,
                   pf.priority_date AS priority_date,
                   pf.jurisdictions AS jurisdictions,
                   collect(DISTINCT o.canonical_name) AS owners
            ORDER BY pf.priority_date DESC
        """, pid=program_id)
        return [dict(rec) for rec in r]


def list_patent_families_for_organization(driver: Driver, organization_id: str) -> List[Dict]:
    with driver.session() as session:
        r = session.run("""
            MATCH (o:Organization {organization_id: $oid})-[:OWNS_PATENT]->(pf:PatentFamily)
            RETURN pf.patent_family_id AS id,
                   pf.title AS title,
                   pf.legal_status AS legal_status,
                   pf.priority_date AS priority_date,
                   pf.publication_numbers AS publication_numbers
            ORDER BY pf.priority_date DESC
        """, oid=organization_id)
        return [dict(rec) for rec in r]