# src/agents/core/neo4j_command_service.py
"""Agent Neo4j 事务化命令服务。

当前事务范围：
- 更新 AgentTask 状态 + 关键时间字段；
- 写入对应 AuditEvent。

不覆盖 Plan / Step / Artifact / Approval 的跨对象事务。
任何一步失败都整体回滚。
"""
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from neo4j import Driver

from .errors import AgentError, AgentErrorCode
from .models import AgentTask, TaskStatus
from .neo4j_serialization import task_from_props
from .state_machine import AgentTaskStateMachine


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_id() -> str:
    return f"AUDIT:{uuid4().hex[:8].upper()}"


_TARGET_ACTION_MAP = {
    TaskStatus.PAUSED: "AGENT_PAUSE",
    TaskStatus.CANCELLED: "AGENT_CANCEL",
    TaskStatus.RESULT_REVIEW: "AGENT_RESULT_SUBMIT",
    TaskStatus.COMPLETED: "AGENT_TASK_STATUS_CHANGE",
    TaskStatus.NEEDS_REVISION: "AGENT_TASK_STATUS_CHANGE",
    TaskStatus.REJECTED: "AGENT_TASK_STATUS_CHANGE",
    TaskStatus.FAILED: "AGENT_TASK_STATUS_CHANGE",
}


class Neo4jAgentCommandService:
    def __init__(
        self,
        driver: Driver,
        *,
        database: Optional[str] = None,
    ) -> None:
        self.driver = driver
        self.database = database

    def transition_task(
        self,
        *,
        task_id: str,
        expected_status: TaskStatus,
        target_status: TaskStatus,
        actor_id: str,
        reason: str,
        action_type: Optional[str] = None,
    ) -> AgentTask:
        AgentTaskStateMachine.require_transition(expected_status, target_status)
        if not actor_id:
            raise AgentError(
                AgentErrorCode.PERMISSION_DENIED, "actor_id 不能为空"
            )
        if not reason or not reason.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "状态变更原因不能为空"
            )

        with self.driver.session(database=self.database) as session:
            try:
                result = session.execute_write(
                    self._transition_tx,
                    task_id=task_id,
                    expected_status=expected_status,
                    target_status=target_status,
                    actor_id=actor_id,
                    reason=reason.strip(),
                    action_type=(
                        action_type
                        or _TARGET_ACTION_MAP.get(
                            target_status, "AGENT_TASK_STATUS_CHANGE"
                        )
                    ),
                )
            except AgentError:
                raise
            except Exception as exc:
                raise AgentError(
                    AgentErrorCode.TRANSACTION_FAILED,
                    "Agent 任务事务执行失败",
                    details={"exception_type": type(exc).__name__},
                ) from exc
        return task_from_props(result["props"])

    @staticmethod
    def _transition_tx(
        tx,
        *,
        task_id: str,
        expected_status: TaskStatus,
        target_status: TaskStatus,
        actor_id: str,
        reason: str,
        action_type: str,
    ) -> dict:
        current = tx.run(
            """
            MATCH (t:AgentTask {task_id: $task_id})
            RETURN t.status AS status,
                   t.version AS version,
                   t.correlation_id AS correlation_id,
                   t.domain AS domain
            """,
            task_id=task_id,
        ).single()
        if current is None:
            raise AgentError(
                AgentErrorCode.TASK_NOT_FOUND, f"任务不存在：{task_id}"
            )
        if current["status"] != expected_status.value:
            raise AgentError(
                AgentErrorCode.CONCURRENT_UPDATE,
                "任务当前状态与预期不一致",
                correlation_id=current["correlation_id"],
                details={
                    "expected_status": expected_status.value,
                    "actual_status": current["status"],
                },
            )

        now = _utc_now_iso()
        started_at = (
            now
            if (
                target_status == TaskStatus.EXECUTING
                and expected_status == TaskStatus.APPROVED
            )
            else None
        )
        completed_at = (
            now
            if target_status
            in {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.REJECTED}
            else None
        )

        updated = tx.run(
            """
            MATCH (t:AgentTask {
                task_id: $task_id,
                status: $expected_status,
                version: $expected_version
            })
            SET t.status = $target_status,
                t.started_at = CASE
                    WHEN $started_at IS NULL THEN t.started_at
                    ELSE coalesce(t.started_at, $started_at)
                END,
                t.completed_at = CASE
                    WHEN $completed_at IS NULL THEN t.completed_at
                    ELSE $completed_at
                END,
                t.cancellation_reason = CASE
                    WHEN $target_status = 'CANCELLED' THEN $reason
                    ELSE t.cancellation_reason
                END,
                t.updated_at = $now,
                t.version = t.version + 1
            RETURN properties(t) AS props
            """,
            task_id=task_id,
            expected_status=expected_status.value,
            expected_version=current["version"],
            target_status=target_status.value,
            started_at=started_at,
            completed_at=completed_at,
            reason=reason,
            now=now,
        ).single()

        if updated is None:
            raise AgentError(
                AgentErrorCode.CONCURRENT_UPDATE,
                "任务在事务执行期间被其他操作更新",
                correlation_id=current["correlation_id"],
            )

        audit_id = _audit_id()
        delta = json.dumps(
            {
                "status": {
                    "before": expected_status.value,
                    "after": target_status.value,
                }
            },
            ensure_ascii=False,
            sort_keys=True,
        )

        tx.run(
            """
            CREATE (a:AuditEvent {
                audit_id: $audit_id,
                action_type: $action_type,
                object_type: 'AgentTask',
                object_id: $task_id,
                actor_id: $actor_id,
                delta: $delta,
                reason: $reason,
                correlation_id: $correlation_id,
                domain: $domain,
                task_id: $task_id,
                timestamp: $timestamp
            })
            """,
            audit_id=audit_id,
            action_type=action_type,
            task_id=task_id,
            actor_id=actor_id,
            delta=delta,
            reason=reason,
            correlation_id=current["correlation_id"],
            domain=current["domain"],
            timestamp=now,
        )

        return {"props": updated["props"], "audit_id": audit_id}