# src/decision_support/decision_record.py
import uuid
from typing import Optional, Dict, List
from neo4j import Driver
from src.foundation.audit_service import write_audit_event


def generate_decision_id() -> str:
    """
    生成决策记录 ID。
    
    Returns:
        str: 格式为 CI:DEC:XXXXXXXX 的决策唯一标识符
    """
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
    """
    记录内部决策（PRD 10.3）。
    
    将情报评估与组织行动连接起来，支持决策追溯。
    
    Args:
        driver: Neo4j 数据库驱动
        brief_id: 关联的情报简报 ID（必填）
        decision_type: 决策类型（monitor / evaluate / partner / deprioritize / IP_review 等）
        decision_summary: 决策摘要
        rationale: 决策理由
        decision_owner: 决策负责人
        review_date: 建议复核日期（YYYY-MM-DD，可选）
        affected_program_id: 受影响的内部项目 ID（可选）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 创建的决策 ID（CI:DEC:XXXXXXXX）
    
    Raises:
        ValueError: 当简报不存在时抛出
    """
    decision_id = generate_decision_id()

    with driver.session() as session:
        # 1. 检查简报是否存在
        brief_check = session.run(
            """
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            RETURN b
            """,
            bid=brief_id,
        ).single()
        if not brief_check:
            raise ValueError(f"简报 {brief_id} 不存在，无法创建决策记录。")

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

        # 3. 建立 BASED_ON 关系（指向简报）
        session.run(
            """
            MATCH (dr:DecisionRecord {decision_id: $did})
            MATCH (b:IntelligenceProduct {brief_id: $bid})
            CREATE (dr)-[:BASED_ON]->(b)
            """,
            did=decision_id,
            bid=brief_id,
        )

        # 4. 如果提供了受影响的内部项目，建立关系
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

        # 5. 审计日志
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
    """
    更新决策的执行结果（用于决策追踪）。
    
    Args:
        driver: Neo4j 数据库驱动
        decision_id: 决策 ID
        outcome_status: 结果状态（pending / successful / unsuccessful / mixed）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        bool: 更新成功返回 True
    
    Raises:
        ValueError: 当状态不合法或决策不存在时抛出
    """
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
    """
    根据 ID 获取决策记录（含关联的简报和项目信息）。
    
    Args:
        driver: Neo4j 数据库驱动
        decision_id: 决策 ID
    
    Returns:
        Optional[Dict]: 决策数据字典，若不存在则返回 None
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord {decision_id: $did})
            OPTIONAL MATCH (dr)-[:BASED_ON]->(b:IntelligenceProduct)
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
    获取基于某个简报的所有决策。
    
    Args:
        driver: Neo4j 数据库驱动
        brief_id: 简报 ID
    
    Returns:
        List[Dict]: 决策列表，按决策时间倒序排列
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (dr:DecisionRecord)-[:BASED_ON]->(b:IntelligenceProduct {brief_id: $bid})
            RETURN dr
            ORDER BY dr.decided_at DESC
            """,
            bid=brief_id,
        )
        return [dict(record["dr"]) for record in result]