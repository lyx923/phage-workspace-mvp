# src/foundation/audit_service.py
from neo4j import Driver
from datetime import datetime
import uuid
import json

def log_action(
    driver: Driver,
    domain: str,               # 'scientific' / 'ci' / 'ipd'
    action_type: str,
    object_type: str,
    object_id: str,
    actor_id: str,
    before_snapshot: dict = None,
    after_snapshot: dict = None,
    reason: str = None,
    correlation_id: str = None,
    request_id: str = None,
    schema_version: str = "v1"
) -> str:
    """记录审计事件（升级为 AuditEvent）"""
    audit_event_id = f"AUDIT-{uuid.uuid4().hex[:8].upper()}"
    if correlation_id is None:
        correlation_id = f"CORR-{uuid.uuid4().hex[:8].upper()}"
    
    payload = {
        "before": before_snapshot,
        "after": after_snapshot,
        "reason": reason,
        "request_id": request_id
    }
    payload_str = json.dumps(payload, ensure_ascii=False, default=str)

    with driver.session() as session:
        session.run("""
            CREATE (ae:AuditEvent {
                audit_event_id: $audit_event_id,
                domain: $domain,
                action_type: $action_type,
                object_type: $object_type,
                object_id: $object_id,
                actor_id: $actor_id,
                occurred_at: datetime(),
                correlation_id: $correlation_id,
                payload: $payload,
                schema_version: $schema_version
            })
        """,
        audit_event_id=audit_event_id,
        domain=domain,
        action_type=action_type,
        object_type=object_type,
        object_id=object_id,
        actor_id=actor_id,
        correlation_id=correlation_id,
        payload=payload_str,
        schema_version=schema_version)
    return audit_event_id