# src/action_log.py
from neo4j import Driver
from datetime import datetime
import uuid

def log_action(driver: Driver, action_type: str, target_type: str, target_id: str, 
               payload: dict, performed_by: str = "system"):
    """通用审计日志记录函数"""
    with driver.session() as session:
        session.run("""
            CREATE (al:ActionLog {
                action_id: $action_id,
                action_type: $action_type,
                target_type: $target_type,
                target_id: $target_id,
                payload: $payload,
                performed_by: $performed_by,
                timestamp: datetime()
            })
        """, 
        action_id=f"ACT-{uuid.uuid4().hex[:8].upper()}",
        action_type=action_type,
        target_type=target_type,
        target_id=target_id,
        payload=payload,
        performed_by=performed_by)