# src/foundation/audit_service.py
from neo4j import Driver
from datetime import datetime
import uuid
import json

def _generate_audit_id(domain: str) -> str:
    """
    生成符合 PRD 7.2 的 AuditEvent ID：<DOMAIN>:AUDIT:<LOCAL_ID>
    其中 DOMAIN 取 domain 的大写形式（如 SCIENTIFIC, CI, IPD），
    若 domain 为 'scientific' 则映射为 'SCI'，'foundation' 则映射为 'FOUNDATION'。
    也可根据实际需要调整映射。
    """
    # 简单映射：将 domain 转换为大写，但保留常见简称
    domain_map = {
        'scientific': 'SCI',
        'ci': 'CI',
        'ipd': 'IPD',
        'foundation': 'FOUNDATION'
    }
    domain_prefix = domain_map.get(domain.lower(), domain.upper())
    local_id = uuid.uuid4().hex[:8].upper()
    return f"{domain_prefix}:AUDIT:{local_id}"

def log_action(
    driver: Driver,
    domain: str,
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
    """记录审计事件（升级为 AuditEvent，符合 PRD 5.7 节）"""
    audit_event_id = _generate_audit_id(domain)
    if correlation_id is None:
        correlation_id = f"CORR-{uuid.uuid4().hex[:8].upper()}"
    
    # 将 before/after 转为 JSON 字符串（如果存在）
    before_json = json.dumps(before_snapshot, ensure_ascii=False, default=str) if before_snapshot else None
    after_json = json.dumps(after_snapshot, ensure_ascii=False, default=str) if after_snapshot else None

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
                before_snapshot: $before_snapshot,
                after_snapshot: $after_snapshot,
                reason: $reason,
                request_id: $request_id,
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
        before_snapshot=before_json,
        after_snapshot=after_json,
        reason=reason,
        request_id=request_id,
        schema_version=schema_version)
    return audit_event_id