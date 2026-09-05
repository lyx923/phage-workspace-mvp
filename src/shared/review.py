# src/shared/review.py
import uuid
from typing import Optional, List, Dict
from neo4j import Driver
from src.foundation.audit_service import write_audit_event

REVIEW_DECISIONS = ["approved", "rejected", "needs_revision", "confirmed", "unverified"]

TARGET_ID_MAP = {
    "Organization": "organization_id",
    "DevelopmentProgram": "program_id",
    "IntelligenceEvent": "event_id",
    "EngineeredPhageConstruct": "construct_id",
    "EngineeringStrategy": "strategy_id",
    "TechnicalClaim": "claim_id",
    "TechnicalResult": "result_id",
    "CompetitorAssessment": "assessment_id",
    "TechnologyAssessment": "technology_assessment_id",
    "DecisionRecord": "decision_id",
    "DecisionBrief": "brief_id",
    "IntelligenceProduct": "brief_id",
    "ScientificEvidencePackage": "package_id",
    "LysisAssay": "assay_id",
    "ClinicalCase": "case_id",
    "KnowledgeReuseEvent": "reuse_event_id",
    "EvidenceUpgradeProposal": "proposal_id",
    "Review": "review_id",
}


def generate_review_id() -> str:
    return f"REV-{uuid.uuid4().hex[:8].upper()}"


def create_review(
    driver: Driver,
    review_type: str,
    target_object_type: str,
    target_object_id: str,
    reviewer_id: str,
    decision: str,
    comment: Optional[str] = None,
    actor_id: str = "system",
    update_target_status: bool = True,
) -> str:
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision 必须是 {REVIEW_DECISIONS} 之一")

    id_prop = TARGET_ID_MAP.get(target_object_type)
    if not id_prop:
        id_prop = f"{target_object_type.lower()}_id"

    review_id = generate_review_id()

    with driver.session() as session:
        check_query = (
            f"MATCH (n:{target_object_type} {{`{id_prop}`: $oid}}) RETURN n"
        )
        target = session.run(check_query, oid=target_object_id).single()
        if not target:
            raise ValueError(
                f"目标对象 {target_object_type} (ID: {target_object_id}) 不存在"
            )

        session.run(
            f"""
            MATCH (n:{target_object_type} {{`{id_prop}`: $oid}})
            CREATE (r:Review {{
                review_id: $review_id,
                review_type: $review_type,
                target_object_type: $target_object_type,
                target_object_id: $target_object_id,
                reviewer_id: $reviewer_id,
                decision: $decision,
                comment: $comment,
                reviewed_at: datetime(),
                created_at: datetime()
            }})
            CREATE (r)-[:REVIEWS]->(n)
            """,
            oid=target_object_id,
            review_id=review_id,
            review_type=review_type,
            target_object_type=target_object_type,
            target_object_id=target_object_id,
            reviewer_id=reviewer_id,
            decision=decision,
            comment=comment,
        )

        if update_target_status:
            try:
                has_status = session.run(
                    f"MATCH (n:{target_object_type} {{`{id_prop}`: $oid}}) "
                    "RETURN properties(n) AS props",
                    oid=target_object_id,
                ).single()
                if has_status and "review_status" in has_status["props"]:
                    session.run(
                        f"""
                        MATCH (n:{target_object_type} {{`{id_prop}`: $oid}})
                        SET n.review_status = $decision,
                            n.updated_at = datetime()
                        """,
                        oid=target_object_id,
                        decision=decision,
                    )
            except Exception as e:
                print(f"⚠️ 更新目标对象 review_status 失败: {e}")

        # 审核分为 approve 和 reject
        action_type = "REVIEW_APPROVE" if decision == "approved" else "REVIEW_REJECT"
        write_audit_event(
            driver,
            action_type=action_type,
            object_type="Review",
            object_id=review_id,
            actor_id=actor_id,
            delta={
                "review_type": review_type,
                "target_object_type": target_object_type,
                "target_object_id": target_object_id,
                "decision": decision,
                "reviewer_id": reviewer_id,
            },
            reason=comment or f"审核创建，决策: {decision}",
        )

        return review_id


def get_reviews_for_object(
    driver: Driver,
    target_object_type: str,
    target_object_id: str,
    limit: int = 50,
) -> List[Dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (r:Review {target_object_type: $ttype, target_object_id: $tid})
            RETURN r
            ORDER BY r.reviewed_at DESC
            LIMIT $limit
            """,
            ttype=target_object_type,
            tid=target_object_id,
            limit=limit,
        )
        return [dict(record["r"]) for record in result]


def get_latest_review(
    driver: Driver,
    target_object_type: str,
    target_object_id: str,
) -> Optional[Dict]:
    reviews = get_reviews_for_object(
        driver, target_object_type, target_object_id, limit=1
    )
    return reviews[0] if reviews else None


def update_review_decision(
    driver: Driver,
    review_id: str,
    new_decision: str,
    actor_id: str = "system",
    comment: Optional[str] = None,
) -> bool:
    if new_decision not in REVIEW_DECISIONS:
        raise ValueError(f"decision 必须是 {REVIEW_DECISIONS} 之一")

    with driver.session() as session:
        old = session.run(
            "MATCH (r:Review {review_id: $rid}) RETURN r.decision AS dec",
            rid=review_id,
        ).single()
        if not old:
            raise ValueError(f"审核 {review_id} 不存在")

        session.run(
            """
            MATCH (r:Review {review_id: $rid})
            SET r.decision = $new_dec,
                r.comment = COALESCE($comment, r.comment),
                r.updated_at = datetime()
            """,
            rid=review_id,
            new_dec=new_decision,
            comment=comment,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="Review",
            object_id=review_id,
            actor_id=actor_id,
            delta={"decision": {"before": old["dec"], "after": new_decision}},
            reason=comment or f"审核决策从 {old['dec']} 更新为 {new_decision}",
        )

        return True


def get_review_by_id(driver: Driver, review_id: str) -> Optional[Dict]:
    with driver.session() as session:
        result = session.run(
            "MATCH (r:Review {review_id: $rid}) RETURN r", rid=review_id
        ).single()
        return dict(result["r"]) if result else None