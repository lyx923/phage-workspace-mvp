# src/decision_support/intelligence_question.py
"""IntelligenceQuestion 服务 —— 符合 PRD 10.1"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from neo4j import Driver

from src.shared.audit_service import write_audit_event


QUESTION_TYPES = {"market", "technology", "ip", "clinical", "bd"}
QUESTION_STATUSES = {"open", "answered", "archived"}


def generate_question_id() -> str:
    return f"CI:IQ:{uuid.uuid4().hex[:8].upper()}"


def create_intelligence_question(
    driver: Driver,
    question_text: str,
    question_type: str = "market",
    requester_id: str = "analyst",
    priority: str = "medium",
    target_object_type: Optional[str] = None,
    target_object_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """创建情报问题。"""
    if question_type not in QUESTION_TYPES:
        raise ValueError(f"question_type 必须是 {QUESTION_TYPES} 之一")

    question_id = generate_question_id()

    with driver.session() as session:
        session.run(
            """
            CREATE (iq:IntelligenceQuestion {
                question_id: $qid,
                question_text: $text,
                question_type: $qtype,
                requester_id: $requester,
                priority: $priority,
                status: 'open',
                target_object_type: $ttype,
                target_object_id: $tid,
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            qid=question_id,
            text=question_text,
            qtype=question_type,
            requester=requester_id,
            priority=priority,
            ttype=target_object_type,
            tid=target_object_id,
        )

        if target_object_type and target_object_id:
            label_map = {
                "organization": ("Organization", "organization_id"),
                "development_program": ("DevelopmentProgram", "program_id"),
                "engineering_strategy": ("EngineeringStrategy", "strategy_id"),
                "pathogen": ("Pathogen", "pathogen_id"),
                "patent_family": ("PatentFamily", "patent_family_id"),
                "clinical_trial": ("ClinicalTrial", "trial_id"),
            }
            if target_object_type in label_map:
                label, id_prop = label_map[target_object_type]
                session.run(
                    f"""
                    MATCH (iq:IntelligenceQuestion {{question_id: $qid}})
                    MATCH (t:{label} {{`{id_prop}`: $tid}})
                    MERGE (iq)-[:ABOUT]->(t)
                    """,
                    qid=question_id,
                    tid=target_object_id,
                )

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="IntelligenceQuestion",
            object_id=question_id,
            actor_id=actor_id,
            delta={
                "question_type": question_type,
                "priority": priority,
                "requester_id": requester_id,
            },
            reason=f"创建情报问题: {question_text[:60]}",
        )

    return question_id


def get_intelligence_question(driver: Driver, question_id: str) -> Optional[Dict]:
    with driver.session() as session:
        r = session.run(
            """
            MATCH (iq:IntelligenceQuestion {question_id: $qid})
            OPTIONAL MATCH (iq)-[:ABOUT]->(t)
            OPTIONAL MATCH (b)-[:ANSWERS]->(iq)
            WHERE b:DecisionBrief OR b:IntelligenceProduct
            RETURN iq,
                   labels(t)[0] AS about_label,
                   t AS about_node,
                   collect(DISTINCT b.brief_id) AS answered_by
            """,
            qid=question_id,
        ).single()
        if not r:
            return None
        data = dict(r["iq"])
        data["about_label"] = r["about_label"]
        data["about_node"] = dict(r["about_node"]) if r["about_node"] else None
        data["answered_by"] = r["answered_by"]
        return data


def list_intelligence_questions(
    driver: Driver,
    status: Optional[str] = None,
    question_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    """
    v0.6 修复：brief_count 同时计入 DecisionBrief 和 IntelligenceProduct。
    """
    filters = []
    params: Dict = {"limit": limit}
    if status:
        filters.append("iq.status = $status")
        params["status"] = status
    if question_type:
        filters.append("iq.question_type = $qtype")
        params["qtype"] = question_type
    where = " AND ".join(filters) if filters else "true"

    with driver.session() as session:
        r = session.run(
            f"""
            MATCH (iq:IntelligenceQuestion)
            WHERE {where}
            OPTIONAL MATCH (b)-[:ANSWERS]->(iq)
            WHERE b:DecisionBrief OR b:IntelligenceProduct
            RETURN iq.question_id AS question_id,
                   iq.question_text AS question_text,
                   iq.question_type AS question_type,
                   iq.requester_id AS requester_id,
                   iq.priority AS priority,
                   iq.status AS status,
                   iq.created_at AS created_at,
                   count(DISTINCT b) AS brief_count
            ORDER BY iq.created_at DESC
            LIMIT $limit
            """,
            **params,
        )
        return [dict(rec) for rec in r]


def mark_question_answered(
    driver: Driver,
    question_id: str,
    actor_id: str = "system",
) -> bool:
    with driver.session() as session:
        check = session.run(
            "MATCH (iq:IntelligenceQuestion {question_id: $qid}) RETURN iq",
            qid=question_id,
        ).single()
        if not check:
            raise ValueError(f"问题 {question_id} 不存在")

        session.run(
            """
            MATCH (iq:IntelligenceQuestion {question_id: $qid})
            SET iq.status = 'answered', iq.updated_at = datetime()
            """,
            qid=question_id,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="IntelligenceQuestion",
            object_id=question_id,
            actor_id=actor_id,
            delta={"status": {"before": "open", "after": "answered"}},
            reason=f"情报问题已被回答: {question_id}",
        )
        return True


def link_brief_to_question(
    driver: Driver,
    brief_id: str,
    question_id: str,
    actor_id: str = "system",
) -> bool:
    """建立 (DecisionBrief|IntelligenceProduct)-[:ANSWERS]->(IntelligenceQuestion)。"""
    with driver.session() as session:
        check_q = session.run(
            "MATCH (iq:IntelligenceQuestion {question_id: $qid}) RETURN iq",
            qid=question_id,
        ).single()
        if not check_q:
            raise ValueError(f"问题 {question_id} 不存在")

        check_b = session.run(
            """
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN b, labels(b) AS labels
            LIMIT 1
            """,
            bid=brief_id,
        ).single()
        if not check_b:
            raise ValueError(
                f"简报 {brief_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct）"
            )
        _brief_label = check_b["labels"][0]

        session.run(
            f"""
            MATCH (b:{_brief_label} {{brief_id: $bid}})
            MATCH (iq:IntelligenceQuestion {{question_id: $qid}})
            MERGE (b)-[:ANSWERS]->(iq)
            SET iq.updated_at = datetime()
            """,
            bid=brief_id,
            qid=question_id,
        )

    write_audit_event(
        driver,
        action_type="LINK_CREATE",
        object_type="IntelligenceQuestion",
        object_id=question_id,
        actor_id=actor_id,
        delta={"brief_id": brief_id, "brief_label": _brief_label},
        reason=f"简报 {brief_id} 回答情报问题 {question_id}",
    )
    return True