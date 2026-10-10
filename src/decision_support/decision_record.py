# src/decision_support/decision_record.py
import uuid
from typing import Optional, Dict, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_decision_id() -> str:
    """生成决策记录 ID（格式：CI:DEC:XXXXXXXX）"""
    return f"CI:DEC:{uuid.uuid4().hex[:8].upper()}"


def create_decision_record(
    driver: Driver,
    brief_id: str,
    decision_type: str,
    decision_summary: str,
    rationale: str,
    decision_owner: str,
    review_date: Optional[str] = None,
    affected_program_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """记录内部决策（PRD 10.3）。支持 DecisionBrief 和 IntelligenceProduct 两种简报。"""
    decision_id = generate_decision_id()

    with driver.session() as session:
        # 1. 检查简报是否存在（双标签）
        brief_check = session.run(
            """
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN b, labels(b) AS labels
            LIMIT 1
            """,
            bid=brief_id,
        ).single()
        if not brief_check:
            raise ValueError(
                f"简报 {brief_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct）"
            )
        _brief_label = brief_check["labels"][0]

        # 2. 创建决策节点
        session.run(
            """
            CREATE (dr:DecisionRecord {
                decision_id: $decision_id,
                decision_type: $decision_type,
                decision_summary: $summary,
                rationale: $rationale,
                decision_owner: $owner,
                review_date: $review_date,
                outcome_status: 'pending',
                decided_at: datetime(),
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            decision_id=decision_id,
            decision_type=decision_type,
            summary=decision_summary,
            rationale=rationale,
            owner=decision_owner,
            review_date=review_date,
        )

        # 3. BASED_ON 关系
        session.run(
            f"""
            MATCH (dr:DecisionRecord {{decision_id: $did}})
            MATCH (b:{_brief_label} {{brief_id: $bid}})
            CREATE (dr)-[:BASED_ON]->(b)
            """,
            did=decision_id,
            bid=brief_id,
        )

        # 4. AFFECTS_INTERNAL_PROGRAM
        if affected_program_id:
            prog_check = session.run(
                "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d",
                pid=affected_program_id,
            ).single()
            if prog_check:
                session.run(
                    """
                    MATCH (dr:DecisionRecord {decision_id: $did})
                    MATCH (d:DevelopmentProgram {program_id: $pid})
                    CREATE (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d)
                    """,
                    did=decision_id,
                    pid=affected_program_id,
                )

        # 5. 审计
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="DecisionRecord",
            object_id=decision_id,
            actor_id=actor_id,
            delta={
                "decision_type": decision_type,
                "decision_owner": decision_owner,
                "brief_id": brief_id,
                "brief_label": _brief_label,
            },
            reason=rationale,
        )

        return decision_id


def update_decision_outcome(
    driver: Driver,
    decision_id: str,
    outcome_status: str,
    actor_id: str = "system",
) -> bool:
    """更新决策的执行结果。"""
    valid_outcomes = ["pending", "successful", "unsuccessful", "mixed"]
    if outcome_status not in valid_outcomes:
        raise ValueError(f"结果状态必须是 {valid_outcomes} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (dr:DecisionRecord {decision_id: $did}) RETURN dr",
            did=decision_id,
        ).single()
        if not check:
            raise ValueError(f"决策 {decision_id} 不存在")

        session.run(
            """
            MATCH (dr:DecisionRecord {decision_id: $did})
            SET dr.outcome_status = $status,
                dr.updated_at = datetime()
            """,
            did=decision_id,
            status=outcome_status,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="DecisionRecord",
            object_id=decision_id,
            actor_id=actor_id,
            delta={"outcome_status": outcome_status},
            reason=f"决策结果更新为 {outcome_status}",
        )
        return True


def get_decision_record(driver: Driver, decision_id: str) -> Optional[Dict]:
    """按 ID 获取决策记录。"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord {decision_id: $did})
            OPTIONAL MATCH (dr)-[:BASED_ON]->(b)
            WHERE b:DecisionBrief OR b:IntelligenceProduct
            OPTIONAL MATCH (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d:DevelopmentProgram)
            RETURN dr,
                   b.brief_id AS brief_id,
                   b.title AS brief_title,
                   d.program_id AS affected_program_id,
                   d.canonical_name AS affected_program_name
            """,
            did=decision_id,
        ).single()
        if not result:
            return None
        data = dict(result["dr"])
        data["brief_id"] = result.get("brief_id")
        data["brief_title"] = result.get("brief_title")
        data["affected_program_id"] = result.get("affected_program_id")
        data["affected_program_name"] = result.get("affected_program_name")
        return data


def get_decisions_by_brief(driver: Driver, brief_id: str) -> List[Dict]:
    """
    v0.6 修复：获取基于某个简报的所有决策。
    支持 DecisionBrief 和 IntelligenceProduct 双标签。
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord)-[:BASED_ON]->(b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN dr
            ORDER BY dr.decided_at DESC
            """,
            bid=brief_id,
        )
        return [dict(record["dr"]) for record in result]