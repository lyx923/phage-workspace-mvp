# src/ci/use_event_service.py
import uuid
from typing import Optional
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_use_event_id() -> str:
    """
    生成情报使用事件 ID。
    
    Returns:
        str: 格式为 CI:USE:XXXXXXXX 的使用事件唯一标识符
    """
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
    
    追踪情报产品被哪些团队、出于什么目的使用，以及触发了哪些决策。
    
    Args:
        driver: Neo4j 数据库驱动
        product_id: 情报产品 ID（IntelligenceProduct.brief_id）
        consumer_type: 消费方类型（IPD / RD / BD / Clinical / Strategy / IP / Management）
        consumer_id: 消费方具体标识（如团队名称）
        use_purpose: 使用目的（roadmap_planning / go_no_go_decision 等）
        context_note: 上下文说明（可选）
        referenced_decision_id: 触发的决策 ID（可选）
        actor_id: 操作者标识（默认 system）
    
    Returns:
        str: 创建的使用事件 ID（CI:USE:XXXXXXXX）
    
    Raises:
        ValueError: 当情报产品不存在时抛出
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