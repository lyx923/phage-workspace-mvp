# src/shared/audit_service.py
"""不可变审计事件写入与查询。

变更说明（Agent v0.8 批次）：
- 扩展 write_audit_event 支持 correlation_id / domain / task_id / step_id；
- 追加 4 个可选参数，现有调用不变；
- AuditEvent 节点新增对应字段与索引。
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from neo4j import Driver


# ── 受控词表 ─────────────────────────────────────────────────────
VALID_ACTION_TYPES = {
    "CREATE",
    "UPDATE",
    "DELETE",
    "STATUS_CHANGE",
    "LINK_CREATE",
    "LINK_DELETE",
    "REVIEW_APPROVE",
    "REVIEW_REJECT",
    "DATA_CORRECTION",
    "MIGRATION",

    # Agent 核心生命周期动作
    "AGENT_TASK_CREATE",
    "AGENT_TASK_STATUS_CHANGE",
    "AGENT_PLAN_CREATE",
    "AGENT_PLAN_REVISE",
    "AGENT_PLAN_APPROVE",
    "AGENT_PLAN_REJECT",
    "AGENT_RUN_START",
    "AGENT_STEP_START",
    "AGENT_STEP_COMPLETE",
    "AGENT_STEP_FAIL",
    "AGENT_STEP_RETRY",
    "AGENT_TOOL_CALL",
    "AGENT_PAUSE",
    "AGENT_RESUME",
    "AGENT_CANCEL",
    "AGENT_INTERVENTION",
    "AGENT_APPROVAL_REQUEST",
    "AGENT_APPROVAL_APPROVE",
    "AGENT_APPROVAL_REJECT",
    "AGENT_APPROVAL_WITHDRAW",
    "AGENT_APPROVAL_EXPIRE",
    "AGENT_APPROVAL_SUPERSEDE",
    "AGENT_APPROVAL_CONSUME",
    "AGENT_ARTIFACT_CREATE",
    "AGENT_ARTIFACT_SUPERSEDE",
    "AGENT_RESULT_SUBMIT",
    "AGENT_RESULT_APPROVE",
    "AGENT_RESULT_REJECT",
    "AGENT_RESULT_REVISION_START",
    "AGENT_PUBLISH",
    "CONTEXT_SNAPSHOT_INVALIDATE",

    # 模型准入与执行动作
    "MODEL_ELIGIBILITY_ASSESS",
    "MODEL_INPUT_SNAPSHOT_CREATE",
    "MODEL_CALL_START",
    "MODEL_CALL_COMPLETE",
    "MODEL_CALL_FAIL",
    "MODEL_CONTRACT_CREATE",

    # 数据校验
    "VALIDATION_RUN_COMPLETE",
    "VALIDATION_RUN_FAIL",
}


class AuditWriteError(Exception):
    """关键审计写入失败时抛出，用于阻断后续操作。"""


def write_audit_event(
    driver: Driver,
    action_type: str,
    object_type: str,
    object_id: str,
    actor_id: str,
    delta: Optional[Dict] = None,
    reason: Optional[str] = None,
    session_id: Optional[str] = None,
    # ── v0.8 Agent 批次新增（全部可选，向后兼容） ──
    correlation_id: Optional[str] = None,
    domain: Optional[str] = None,
    task_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> str:
    """写入不可变审计日志节点（PRD 6.1.1 / 15）。"""
    if action_type not in VALID_ACTION_TYPES:
        raise ValueError(
            f"非法 action_type: {action_type}。合法值: {sorted(VALID_ACTION_TYPES)}"
        )

    audit_id = f"AUDIT:{uuid.uuid4().hex[:8].upper()}"
    timestamp = datetime.now(timezone.utc).isoformat()
    delta_json = (
        json.dumps(delta, ensure_ascii=False, default=str) if delta else None
    )

    try:
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
                    correlation_id: $correlation_id,
                    domain: $domain,
                    task_id: $task_id,
                    step_id: $step_id,
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
                correlation_id=correlation_id,
                domain=domain,
                task_id=task_id,
                step_id=step_id,
                timestamp=timestamp,
            )
    except Exception as exc:
        raise AuditWriteError(
            f"审计写入失败，系统已阻断后续操作: {exc}"
        ) from exc

    return audit_id


def get_audit_trail(driver: Driver, object_id: str) -> List[Dict]:
    """查询指定对象的完整审计历史。"""
    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:AuditEvent {object_id: $object_id})
            RETURN a.audit_id AS audit_id,
                   a.action_type AS action_type,
                   a.actor_id AS actor_id,
                   a.delta AS delta,
                   a.reason AS reason,
                   a.correlation_id AS correlation_id,
                   a.domain AS domain,
                   a.task_id AS task_id,
                   a.step_id AS step_id,
                   a.timestamp AS timestamp
            ORDER BY a.timestamp ASC
            """,
            object_id=object_id,
        )
        return [dict(record) for record in result]