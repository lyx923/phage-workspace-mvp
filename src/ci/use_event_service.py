# src/ci/use_event_service.py
import uuid
from typing import Optional
from neo4j import Driver
from src.foundation.audit_service import log_action


def generate_use_event_id() -> str:
    return f"CI:USE:{uuid.uuid4().hex[:8].upper()}"


def record_intelligence_use(
    driver: Driver,
    product_id: str,
    consumer_type: str,   # "IPD", "RD", "BD", "Clinical", "Strategy", "IP", "Management"
    consumer_id: str,
    use_purpose: str,     # "roadmap_planning", "go_no_go_decision", etc.
    context_note: Optional[str] = None,
    referenced_decision_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    记录情报产品的消费事件（IntelligenceUseEvent）
    product_id 必须对应一个已存在的 IntelligenceProduct。
    若提供了 referenced_decision_id，则建立 TRIGGERS 关系。
    """
    use_event_id = generate_use_event_id()

    with driver.session() as session:
        # 1. 检查产品是否存在
        product = session.run(
            "MATCH (b:IntelligenceProduct {brief_id: $pid}) RETURN b",
            pid=product_id,
        ).single()
        if not product:
            raise ValueError(f"情报产品 {product_id} 不存在，无法记录使用事件。")

        # 2. 创建 IntelligenceUseEvent 节点
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

        # 3. 建立 CONSUMES 关系
        session.run(
            """
            MATCH (u:IntelligenceUseEvent {use_event_id: $uid})
            MATCH (b:IntelligenceProduct {brief_id: $pid})
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
            if not decision:
                # 可选：仅警告，不影响事件创建
                print(f"⚠️ 警告: 决策 {referenced_decision_id} 不存在，跳过 TRIGGERS 关系创建。")
            else:
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
        log_action(
            driver,
            domain="ci",
            action_type="CREATE_INTELLIGENCE_USE",
            object_type="IntelligenceUseEvent",
            object_id=use_event_id,
            actor_id=actor_id,
            after_snapshot={
                "product_id": product_id,
                "consumer_type": consumer_type,
                "consumer_id": consumer_id,
                "use_purpose": use_purpose,
            },
            reason=f"{consumer_type} 团队消费情报产品 {product_id}",
        )

        return use_event_id