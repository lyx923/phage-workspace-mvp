# src/ci/competitor_assessment.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import log_action


def generate_assessment_id() -> str:
    """生成符合 PRD 8.3 的评估 ID"""
    return f"CI:ASSESS:{uuid.uuid4().hex[:8].upper()}"


def create_competitor_assessment(
    driver: Driver,
    assessment_type: str,  # threat / opportunity / capability / uncertainty
    subject_type: str,     # organization / program / event
    subject_id: str,
    impact_area: str,      # market / technology / clinical / IP / BD
    impact_level: str,     # high / medium / low
    assessment_summary: str,
    confidence: str = "medium",  # high / medium / low
    analyst_id: str = "unknown",
    time_horizon: Optional[str] = None,  # short / medium / long
    assumptions: Optional[List[str]] = None,
    unknowns: Optional[List[str]] = None,
    valid_until: Optional[str] = None,   # YYYY-MM-DD
    actor_id: str = "system"
) -> str:
    """
    PRD 8.3 / 12.6: 创建竞争影响评估

    记录内部分析人员对竞争对手、项目或事件的判断。
    所有输入必须基于已审核事实，外部展示时需标记 'Internal assessment'。
    """
    assessment_id = generate_assessment_id()
    assumptions = assumptions or []
    unknowns = unknowns or []

    # subject_type 到 Neo4j 标签和 ID 属性的映射
    subject_map = {
        "organization": ("Organization", "organization_id"),
        "program": ("DevelopmentProgram", "program_id"),
        "event": ("IntelligenceEvent", "event_id"),
    }

    if subject_type not in subject_map:
        raise ValueError(f"不支持的 subject_type: {subject_type}，可选: organization, program, event")

    label, id_prop = subject_map[subject_type]

    with driver.session() as session:
        # 1. 检查目标对象是否存在
        check_query = f"MATCH (n:{label} {{`{id_prop}`: $sid}}) RETURN n"
        target = session.run(check_query, sid=subject_id).single()
        if not target:
            raise ValueError(f"{subject_type} 对象 {subject_id} 不存在")

        # 2. 创建评估节点
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

        # 3. 建立评估与目标对象的关系
        session.run(
            f"""
            MATCH (ca:CompetitorAssessment {{assessment_id: $assessment_id}})
            MATCH (n:{label} {{`{id_prop}`: $subject_id}})
            CREATE (ca)-[:ASSESSES]->(n)
            """,
            assessment_id=assessment_id,
            subject_id=subject_id,
        )

        # 4. 审计日志
        log_action(
            driver,
            domain="ci",
            action_type="CREATE_COMPETITOR_ASSESSMENT",
            object_type="CompetitorAssessment",
            object_id=assessment_id,
            actor_id=actor_id,
            after_snapshot={
                "assessment_type": assessment_type,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "impact_level": impact_level,
            },
            reason=f"分析人员 {analyst_id} 创建了 {assessment_type} 评估",
        )

        return assessment_id


def get_assessment(driver: Driver, assessment_id: str) -> Optional[Dict]:
    """根据 ID 获取单个评估"""
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
    """获取某个主题的所有评估（按时间倒序）"""
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
    new_status: str,  # draft / reviewed / approved
    reviewer_id: str,
    comment: Optional[str] = None,
    actor_id: str = "system",
) -> bool:
    """更新评估的审核状态（通常由 shared.review 自动触发，也可手动调用）"""
    valid_statuses = ["draft", "reviewed", "approved"]
    if new_status not in valid_statuses:
        raise ValueError(f"状态必须是 {valid_statuses} 之一")

    with driver.session() as session:
        # 检查是否存在
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

        log_action(
            driver,
            domain="ci",
            action_type="UPDATE_ASSESSMENT_REVIEW",
            object_type="CompetitorAssessment",
            object_id=assessment_id,
            actor_id=actor_id,
            after_snapshot={"review_status": new_status, "reviewer_id": reviewer_id},
            reason=comment or f"审核状态更新为 {new_status}",
        )

        return True