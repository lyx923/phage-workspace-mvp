# src/agents/core/intervention_service.py
"""Agent 人工干预服务。"""
from typing import Callable, Optional
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentIntervention,
    InterventionType,
    TaskStatus,
)
from .repositories import (
    AgentInterventionRepository,
    AgentTaskRepository,
)


class AgentInterventionService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        intervention_repository: AgentInterventionRepository,
        task_service,
        audit_writer: Callable[..., str],
        id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.task_repository = task_repository
        self.intervention_repository = intervention_repository
        self.task_service = task_service
        self.audit_writer = audit_writer
        self.id_factory = id_factory or (
            lambda: f"INTV-{uuid4().hex[:12].upper()}"
        )

    def _record(
        self,
        *,
        task_id: str,
        intervention_type: InterventionType,
        requested_by: str,
        instruction: str,
        before_state: TaskStatus,
        after_state: TaskStatus,
        affected_step_id: Optional[str] = None,
    ) -> AgentIntervention:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        return self.intervention_repository.create(
            AgentIntervention(
                intervention_id=self.id_factory(),
                task_id=task_id,
                intervention_type=intervention_type,
                requested_by=requested_by,
                instruction=instruction,
                affected_step_id=affected_step_id,
                before_state=before_state.value,
                after_state=after_state.value,
                correlation_id=task.correlation_id,
            )
        )

    def pause(self, task_id: str, *, requested_by: str, reason: str):
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status not in {
            TaskStatus.EXECUTING,
            TaskStatus.WAITING_INPUT,
            TaskStatus.WAITING_APPROVAL,
        }:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "当前任务状态不能暂停",
                correlation_id=task.correlation_id,
            )
        updated = self.task_service.transition_task(
            task_id,
            expected_status=task.status,
            target_status=TaskStatus.PAUSED,
            actor_id=requested_by,
            reason=reason,
        )
        self._record(
            task_id=task_id,
            intervention_type=InterventionType.PAUSE,
            requested_by=requested_by,
            instruction=reason,
            before_state=task.status,
            after_state=TaskStatus.PAUSED,
        )
        return updated

    def resume(self, task_id: str, *, requested_by: str, reason: str):
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status != TaskStatus.PAUSED:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "只有 PAUSED 任务可以恢复",
                correlation_id=task.correlation_id,
            )
        updated = self.task_service.transition_task(
            task_id,
            expected_status=TaskStatus.PAUSED,
            target_status=TaskStatus.EXECUTING,
            actor_id=requested_by,
            reason=reason,
        )
        self._record(
            task_id=task_id,
            intervention_type=InterventionType.RESUME,
            requested_by=requested_by,
            instruction=reason,
            before_state=TaskStatus.PAUSED,
            after_state=TaskStatus.EXECUTING,
        )
        return updated

    def cancel(self, task_id: str, *, requested_by: str, reason: str):
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status in {
            TaskStatus.CANCELLED,
            TaskStatus.COMPLETED,
            TaskStatus.REJECTED,
        }:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "终态任务不能再次取消",
                correlation_id=task.correlation_id,
            )
        updated = self.task_service.transition_task(
            task_id,
            expected_status=task.status,
            target_status=TaskStatus.CANCELLED,
            actor_id=requested_by,
            reason=reason,
        )
        self._record(
            task_id=task_id,
            intervention_type=InterventionType.CANCEL,
            requested_by=requested_by,
            instruction=reason,
            before_state=task.status,
            after_state=TaskStatus.CANCELLED,
        )
        return updated

    def request_replan(self, task_id: str, *, requested_by: str, comment: str):
        if not comment.strip():
            raise AgentError(
                AgentErrorCode.PLAN_REVIEW_COMMENT_REQUIRED,
                "退回重规划必须填写原因",
            )
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status not in {
            TaskStatus.PLAN_REVIEW,
            TaskStatus.NEEDS_REVISION,
            TaskStatus.FAILED,
        }:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "当前状态不允许请求重规划",
                correlation_id=task.correlation_id,
            )
        target = TaskStatus.NEEDS_REVISION
        if task.status != target:
            updated = self.task_service.transition_task(
                task_id,
                expected_status=task.status,
                target_status=target,
                actor_id=requested_by,
                reason=comment,
            )
        else:
            updated = task
        self._record(
            task_id=task_id,
            intervention_type=InterventionType.REQUEST_REPLAN,
            requested_by=requested_by,
            instruction=comment,
            before_state=task.status,
            after_state=target,
        )
        return updated