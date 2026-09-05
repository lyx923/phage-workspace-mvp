# src/ci/competitor_assessment.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import write_audit_event


def generate_assessment_id() -> str:
    """生成符合 PRD 8.3 的评估 ID"""
    return f"CI:ASSESS:{uuid.uuid4().hex[:8].upper()}"


def create_competitor_assessment(
    driver: Driver,
    assessment_type: str,
    subject_type: str,
    subject_id: str,
    impact_area: str,
    impact_level: str,
    assessment_summary: str,
    confidence: str = "medium",
    analyst_id: str = "unknown",
    time_horizon: Optional[str] = None,
    assumptions: Optional[List[str]] = None,
    unknowns: Optional[List[str]] = None,
    valid_until: Optional[str] = None,
    actor_id: str = "system"
) -> str:
    assessment_id = generate_assessment_id()
    assumptions = assumptions or []
    unknowns = unknowns or []

    subject_map = {
        "organization": ("Organization", "organization_id"),
        "program": ("DevelopmentProgram", "program_id"),
        "event": ("IntelligenceEvent", "event_id"),
    }

    if subject_type not in subject_map:
        raise ValueError(f"不支持的 subject_type: {subject_type}，可选: organization, program, event")

    label, id_prop = subject_map[subject_type]

    with driver.session() as session:
        check_query = f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n"
        target = session.run(check_query, sid=subject_id).single()
        if not target:
            raise ValueError(f"{subject_type} 对象 {subject_id} 不存在")

        session.run(
            f"""
            CREATE (ca:CompetitorAssessment {{
                assessment_id: $assessment_id,
                assessment_type: $assessment_type,
                subject_type: $subject_type,
                subject_id: $subject_id,
                impact_area: $impact_area,
                impact_level: $impact_level,
                time_horizon: $time_horizon,
                assessment_summary: $summary,
                assumptions: $assumptions,
                unknowns: $unknowns,
                confidence: $confidence,
                analyst_id: $analyst_id,
                valid_until: $valid_until,
                review_status: 'draft',
                assessed_at: datetime(),
                created_at: datetime(),
                updated_at: datetime()
            }})
            """,
            assessment_id=assessment_id,
            assessment_type=assessment_type,
            subject_type=subject_type,
            subject_id=subject_id,
            impact_area=impact_area,
            impact_level=impact_level,
            time_horizon=time_horizon,
            summary=assessment_summary,
            assumptions=assumptions,
            unknowns=unknowns,
            confidence=confidence,
            analyst_id=analyst_id,
            valid_until=valid_until,
        )

        session.run(
            f"""
            MATCH (ca:CompetitorAssessment {{assessment_id: $assessment_id}})
            MATCH (n:{label} {{`{id_prop}`: $subject_id}})
            CREATE (ca)-[:ASSESSES]->(n)
            """,
            assessment_id=assessment_id,
            subject_id=subject_id,
        )

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="CompetitorAssessment",
            object_id=assessment_id,
            actor_id=actor_id,
            delta={
                "assessment_type": assessment_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "impact_level": impact_level,
            },
            reason=f"分析人员 {analyst_id} 创建了 {assessment_type} 评估",
        )

        return assessment_id


def get_assessment(driver: Driver, assessment_id: str) -> Optional[Dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (ca:CompetitorAssessment {assessment_id: $aid})
            RETURN ca
            """,
            aid=assessment_id,
        ).single()
        return dict(result["ca"]) if result else None


def get_assessments_for_subject(
    driver: Driver,
    subject_type: str,
    subject_id: str,
    limit: int = 50,
) -> List[Dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (ca:CompetitorAssessment {subject_type: $stype, subject_id: $sid})
            RETURN ca
            ORDER BY ca.assessed_at DESC
            LIMIT $limit
            """,
            stype=subject_type,
            sid=subject_id,
            limit=limit,
        )
        return [dict(record["ca"]) for record in result]


def update_assessment_review_status(
    driver: Driver,
    assessment_id: str,
    new_status: str,
    reviewer_id: str,
    comment: Optional[str] = None,
    actor_id: str = "system",
) -> bool:
    valid_statuses = ["draft", "reviewed", "approved"]
    if new_status not in valid_statuses:
        raise ValueError(f"状态必须是 {valid_statuses} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (ca:CompetitorAssessment {assessment_id: $aid}) RETURN ca",
            aid=assessment_id,
        ).single()
        if not check:
            raise ValueError(f"评估 {assessment_id} 不存在")

        session.run(
            """
            MATCH (ca:CompetitorAssessment {assessment_id: $aid})
            SET ca.review_status = $status,
                ca.reviewed_by = $reviewer,
                ca.review_comment = $comment,
                ca.reviewed_at = datetime(),
                ca.updated_at = datetime()
            """,
            aid=assessment_id,
            status=new_status,
            reviewer=reviewer_id,
            comment=comment,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="CompetitorAssessment",
            object_id=assessment_id,
            actor_id=actor_id,
            delta={"review_status": new_status, "reviewer_id": reviewer_id},
            reason=comment or f"审核状态更新为 {new_status}",
        )

        return True