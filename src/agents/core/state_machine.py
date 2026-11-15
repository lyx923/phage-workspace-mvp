# src/agents/core/state_machine.py
"""AgentTask 确定性状态机。"""
from typing import Dict, FrozenSet

from .errors import AgentError, AgentErrorCode
from .models import TaskStatus


_ALLOWED_TRANSITIONS: Dict[TaskStatus, FrozenSet[TaskStatus]] = {
    TaskStatus.DRAFT: frozenset(
        {TaskStatus.UNDERSTANDING, TaskStatus.CANCELLED}
    ),
    TaskStatus.UNDERSTANDING: frozenset(
        {
            TaskStatus.WAITING_INPUT,
            TaskStatus.PLANNING,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_INPUT: frozenset(
        {
            TaskStatus.UNDERSTANDING,
            TaskStatus.PLANNING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PLANNING: frozenset(
        {
            TaskStatus.PLAN_REVIEW,
            TaskStatus.WAITING_INPUT,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PLAN_REVIEW: frozenset(
        {
            TaskStatus.APPROVED,
            TaskStatus.NEEDS_REVISION,
            TaskStatus.REJECTED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.APPROVED: frozenset(
        {TaskStatus.EXECUTING, TaskStatus.CANCELLED}
    ),
    TaskStatus.EXECUTING: frozenset(
        {
            TaskStatus.WAITING_INPUT,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.RESULT_REVIEW,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {
            TaskStatus.EXECUTING,
            TaskStatus.NEEDS_REVISION,
            TaskStatus.PAUSED,
            TaskStatus.REJECTED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {TaskStatus.EXECUTING, TaskStatus.CANCELLED}
    ),
    TaskStatus.FAILED: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RESULT_REVIEW: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.NEEDS_REVISION,
            TaskStatus.REJECTED,
        }
    ),
    TaskStatus.NEEDS_REVISION: frozenset(
        {
            TaskStatus.PLANNING,
            TaskStatus.EXECUTING,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.REJECTED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
    TaskStatus.COMPLETED: frozenset(),
}


class AgentTaskStateMachine:
    """只负责判断和执行任务状态转换，不执行数据库写入。"""

    @staticmethod
    def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
        if current == target:
            return True
        return target in _ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def require_transition(
        cls,
        current: TaskStatus,
        target: TaskStatus,
        *,
        correlation_id: str | None = None,
    ) -> None:
        if not cls.can_transition(current, target):
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                f"不允许从 {current.value} 转换到 {target.value}",
                correlation_id=correlation_id,
                details={
                    "current_status": current.value,
                    "target_status": target.value,
                },
            )

    @classmethod
    def transition(
        cls,
        current: TaskStatus,
        target: TaskStatus,
        *,
        correlation_id: str | None = None,
    ) -> TaskStatus:
        cls.require_transition(
            current, target, correlation_id=correlation_id
        )
        return target

    @staticmethod
    def is_terminal(status: TaskStatus) -> bool:
        return status in {
            TaskStatus.REJECTED,
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
        }

    @staticmethod
    def allows_tool_execution(status: TaskStatus) -> bool:
        return status == TaskStatus.EXECUTING