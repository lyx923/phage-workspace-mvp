# src/ci/use_event_service.py
import uuid
from typing import Optional
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_use_event_id() -> str:
    """生成情报使用事件 ID（格式：CI:USE:XXXXXXXX）"""
    return f"CI:USE:{uuid.uuid4().hex[:8].upper()}"


def record_intelligence_use(
    driver: Driver,
    product_id: str,
    consumer_type: str,
    consumer_id: str,
    use_purpose: str,
    context_note: Optional[str] = None,
    referenced_decision_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    记录情报产品的消费事件（PRD 16.2）。

    v0.6 修复：product_id 支持 DecisionBrief 和 IntelligenceProduct 双标签。

    Args:
        product_id: 情报产品 ID（IntelligenceProduct.brief_id 或 DecisionBrief.brief_id）
        consumer_type: IPD / RD / BD / Clinical / Strategy / IP / Management
        consumer_id: 消费方标识（团队名称）
        use_purpose: roadmap_planning / go_no_go_decision 等
        context_note: 上下文说明
        referenced_decision_id: 触发的决策 ID
        actor_id: 操作者
    """
    use_event_id = generate_use_event_id()

    with driver.session() as session:
        # 1. 检查产品是否存在（双标签）
        product = session.run(
            """
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $pid)
               OR (b:IntelligenceProduct AND b.brief_id = $pid)
            RETURN b
            LIMIT 1
            """,
            pid=product_id,
        ).single()
        if not product:
            raise ValueError(
                f"情报产品 {product_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct），"
                f"无法记录使用事件。"
            )

        # 2. 创建使用事件节点
        session.run(
            """
            CREATE (u:IntelligenceUseEvent {
                use_event_id: $use_event_id,
                product_id: $product_id,
                consumer_type: $consumer_type,
                consumer_id: $consumer_id,
                use_purpose: $use_purpose,
                context_note: $context_note,
                actor_id: $actor_id,
                used_at: datetime()
            })
            """,
            use_event_id=use_event_id,
            product_id=product_id,
            consumer_type=consumer_type,
            consumer_id=consumer_id,
            use_purpose=use_purpose,
            context_note=context_note,
            actor_id=actor_id,
        )

        # 3. 建立 CONSUMES 关系（双标签）
        session.run(
            """
            MATCH (u:IntelligenceUseEvent {use_event_id: $uid})
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $pid)
               OR (b:IntelligenceProduct AND b.brief_id = $pid)
            CREATE (u)-[:CONSUMES]->(b)
            """,
            uid=use_event_id,
            pid=product_id,
        )

        # 4. 如果提供了决策 ID，建立 TRIGGERS 关系
        if referenced_decision_id:
            decision = session.run(
                "MATCH (d:DecisionRecord {decision_id: $did}) RETURN d",
                did=referenced_decision_id,
            ).single()
            if decision:
                session.run(
                    """
                    MATCH (u:IntelligenceUseEvent {use_event_id: $uid})
                    MATCH (d:DecisionRecord {decision_id: $did})
                    CREATE (u)-[:TRIGGERS]->(d)
                    """,
                    uid=use_event_id,
                    did=referenced_decision_id,
                )

        # 5. 审计日志
        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="IntelligenceUseEvent",
            object_id=use_event_id,
            actor_id=actor_id,
            delta={
                "product_id": product_id,
                "consumer_type": consumer_type,
                "consumer_id": consumer_id,
                "use_purpose": use_purpose,
            },
            reason=f"{consumer_type} 团队消费情报产品 {product_id}",
        )

        return use_event_id