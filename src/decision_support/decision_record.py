# src/decision_support/decision_record.py
import uuid
from typing import Optional, Dict, List
from neo4j import Driver
from src.foundation.audit_service import log_action


def generate_decision_id() -> str:
    """生成符合 PRD 10.3 的决策 ID"""
    return f"CI:DEC:{uuid.uuid4().hex[:8].upper()}"


def create_decision_record(
    driver: Driver,
    decision_type: str,  # monitor / evaluate / partner / deprioritize / IP_review / etc.
    decision_summary: str,
    rationale: str,
    decision_owner: str,
    brief_id: Optional[str] = None,  # 关联的 DecisionBrief ID（可选）
    review_date: Optional[str] = None,  # YYYY-MM-DD，建议复核日期
    affected_program_id: Optional[str] = None,  # 受影响的内部项目 ID
    actor_id: str = "system",
) -> str:
    """
    PRD 10.3: 记录内部决策

    将情报（评估/简报）与组织行动连接起来。
    这是 Palantir-style Ontology 区别于普通情报数据库的关键。
    """
    decision_id = generate_decision_id()

    with driver.session() as session:
        # 1. 创建决策节点
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

        # 2. 如果提供了 brief_id，建立 BASED_ON 关系
        if brief_id:
            session.run(
                """
                MATCH (dr:DecisionRecord {decision_id: $did})
                MATCH (db:DecisionBrief {brief_id: $bid})
                CREATE (dr)-[:BASED_ON]->(db)
                """,
                did=decision_id,
                bid=brief_id,
            )

        # 3. 如果提供了受影响的内部项目，建立 AFFECTS_INTERNAL_PROGRAM 关系
        if affected_program_id:
            session.run(
                """
                MATCH (dr:DecisionRecord {decision_id: $did})
                MATCH (d:DevelopmentProgram {program_id: $pid})
                CREATE (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d)
                """,
                did=decision_id,
                pid=affected_program_id,
            )

        # 4. 审计日志
        log_action(
            driver,
            domain="ci",
            action_type="CREATE_DECISION_RECORD",
            object_type="DecisionRecord",
            object_id=decision_id,
            actor_id=actor_id,
            after_snapshot={
                "decision_type": decision_type,
                "decision_owner": decision_owner,
                "brief_id": brief_id,
            },
            reason=rationale,
        )

        return decision_id


def update_decision_outcome(
    driver: Driver,
    decision_id: str,
    outcome_status: str,  # pending / successful / unsuccessful / mixed
    actor_id: str = "system",
) -> bool:
    """更新决策的后续结果（用于决策追踪）"""
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

        log_action(
            driver,
            domain="ci",
            action_type="UPDATE_DECISION_OUTCOME",
            object_type="DecisionRecord",
            object_id=decision_id,
            actor_id=actor_id,
            after_snapshot={"outcome_status": outcome_status},
        )

        return True


def get_decision_record(driver: Driver, decision_id: str) -> Optional[Dict]:
    """根据 ID 获取决策记录（含关联的简报 ID）"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord {decision_id: $did})
            OPTIONAL MATCH (dr)-[:BASED_ON]->(db:DecisionBrief)
            OPTIONAL MATCH (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d:DevelopmentProgram)
            RETURN dr,
                   db.brief_id AS brief_id,
                   db.title AS brief_title,
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
    """获取基于某个简报的所有决策"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord)-[:BASED_ON]->(db:DecisionBrief {brief_id: $bid})
            RETURN dr
            ORDER BY dr.decided_at DESC
            """,
            bid=brief_id,
        )
        return [dict(record["dr"]) for record in result]