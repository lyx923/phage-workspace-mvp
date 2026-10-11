# data_access/audit.py
"""Dash 前端统一 AuditEvent 写入。"""
from config import get_driver
from src.shared.audit_service import write_audit_event


def audit(action_type: str, object_type: str, object_id: str,
          actor_id: str = "dash_frontend",
          delta=None, reason=None):
    """action_type 必须在 VALID_ACTION_TYPES 里：
    CREATE / UPDATE / STATUS_CHANGE / LINK_CREATE / LINK_DELETE
    / REVIEW_APPROVE / REVIEW_REJECT / DATA_CORRECTION / MIGRATION"""
    return write_audit_event(
        get_driver(),
        action_type=action_type,
        object_type=object_type,
        object_id=object_id,
        actor_id=actor_id,
        delta=delta or {},
        reason=reason,
    )


def audit_danger_op(action_id: str, detail: str = "",
                    actor_id: str = "dash_frontend"):
    return audit(
        action_type="MIGRATION",   # 受控词表里的值
        object_type="System",
        object_id=action_id,
        actor_id=actor_id,
        delta={"detail": detail},
        reason=f"危险操作：{action_id}",
    )