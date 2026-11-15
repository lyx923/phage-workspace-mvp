# src/agents/core/step_retry_service.py
"""失败步骤的受控重试。"""
from dataclasses import replace
from typing import Callable, Tuple

from .errors import AgentError, AgentErrorCode
from .models import AgentStep, AgentTask, StepStatus, TaskStatus
from .repositories import AgentStepRepository, AgentTaskRepository
from .retry_policy import RetryPolicy


class AgentStepRetryService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        step_repository: AgentStepRepository,
        task_service,
        retry_policy: RetryPolicy,
        audit_writer: Callable[..., str],
    ) -> None:
        self.task_repository = task_repository
        self.step_repository = step_repository
        self.task_service = task_service
        self.retry_policy = retry_policy
        self.audit_writer = audit_writer

    def prepare_retry(
        self,
        *,
        task_id: str,
        step_id: str,
        requested_by: str,
        reason: str,
    ) -> Tuple[AgentTask, AgentStep]:
        if not reason or not reason.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "重试必须填写原因"
            )

        task = self.task_repository.get(task_id)
        step = self.step_repository.get(step_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if step is None:
            raise AgentError(
                AgentErrorCode.STEP_NOT_FOUND, "步骤不存在",
                correlation_id=task.correlation_id,
            )
        if step.status != StepStatus.FAILED:
            raise AgentError(
                AgentErrorCode.RETRY_NOT_AUTHORIZED,
                "只有 FAILED 步骤可以重试",
                correlation_id=task.correlation_id,
            )
        if task.status not in {TaskStatus.FAILED, TaskStatus.PAUSED}:
            raise AgentError(
                AgentErrorCode.RETRY_NOT_AUTHORIZED,
                "当前任务状态不允许重试步骤",
                correlation_id=task.correlation_id,
            )

        decision = self.retry_policy.evaluate(
            error_code=step.error_code,
            retry_count=step.retry_count,
            can_retry=step.can_retry,
        )
        if not decision.allowed:
            raise AgentError(
                AgentErrorCode.RETRY_NOT_AUTHORIZED,
                decision.reason,
                correlation_id=task.correlation_id,
                details={
                    "step_id": step_id,
                    "error_code": step.error_code,
                    "retry_count": step.retry_count,
                },
            )

        reset_step = replace(
            step,
            status=StepStatus.PENDING,
            retry_count=decision.next_retry_count,
            started_at=None,
            completed_at=None,
            error_summary=None,
        )
        saved_step = self.step_repository.save(reset_step)

        if task.status == TaskStatus.PAUSED:
            task = self.task_service.transition_task(
                task_id,
                expected_status=TaskStatus.PAUSED,
                target_status=TaskStatus.EXECUTING,
                actor_id=requested_by,
                reason=reason,
            )
        elif task.status == TaskStatus.FAILED:
            task = self.task_service.transition_task(
                task_id,
                expected_status=TaskStatus.FAILED,
                target_status=TaskStatus.EXECUTING,
                actor_id=requested_by,
                reason=reason,
            )

        self.audit_writer(
            action_type="AGENT_STEP_RETRY",
            object_type="AgentStep",
            object_id=step_id,
            actor_id=requested_by,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task_id,
            step_id=step_id,
            delta={
                "retry_count": {
                    "before": step.retry_count,
                    "after": decision.next_retry_count,
                },
                "previous_error_code": step.error_code,
            },
            reason=reason,
        )
        return task, saved_step