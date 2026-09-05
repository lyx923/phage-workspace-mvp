# src/foundation/audit_service.py
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, List
from neo4j import Driver
import json

# ── 受控词表（PRD 6.1.1） ────────────────────────────────────────────────
VALID_ACTION_TYPES = {
    "CREATE",
    "UPDATE",
    "STATUS_CHANGE",
    "LINK_CREATE",
    "LINK_DELETE",
    "REVIEW_APPROVE",
    "REVIEW_REJECT",
    "DATA_CORRECTION",
    "MIGRATION",
}


def write_audit_event(
    driver: Driver,
    action_type: str,
    object_type: str,
    object_id: str,
    actor_id: str,
    delta: Optional[Dict] = None,
    reason: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """
    写入不可变审计日志节点（PRD 6.1.1）。

    约束：
      - AuditEvent 节点只有 CREATE，永远不 UPDATE 或 DELETE
      - action_type 必须是受控词表中的值
      - delta 自动转为 JSON 字符串存储

    返回 audit_id（格式：AUDIT:XXXXXXXX）
    """
    if action_type not in VALID_ACTION_TYPES:
        raise ValueError(
            f"非法 action_type: {action_type}。"
            f"合法值: {VALID_ACTION_TYPES}"
        )

    audit_id = f"AUDIT:{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()
    delta_json = json.dumps(delta, ensure_ascii=False, default=str) if delta else None

    with driver.session() as session:
        session.run(
            """
            CREATE (a:AuditEvent {
                audit_id: $audit_id,
                action_type: $action_type,
                object_type: $object_type,
                object_id: $object_id,
                actor_id: $actor_id,
                delta: $delta,
                reason: $reason,
                session_id: $session_id,
                timestamp: $timestamp
            })
            """,
            audit_id=audit_id,
            action_type=action_type,
            object_type=object_type,
            object_id=object_id,
            actor_id=actor_id,
            delta=delta_json,
            reason=reason,
            session_id=session_id,
            timestamp=timestamp,
        )

    return audit_id


def get_audit_trail(driver: Driver, object_id: str) -> List[Dict]:
    """
    查询指定对象的完整审计历史，按时间升序返回。
    """
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:AuditEvent {object_id: $object_id})
            RETURN a.audit_id AS audit_id,
                   a.action_type AS action_type,
                   a.actor_id AS actor_id,
                   a.delta AS delta,
                   a.reason AS reason,
                   a.timestamp AS timestamp
            ORDER BY a.timestamp ASC
            """,
            object_id=object_id,
        )
        return [dict(record) for record in result]