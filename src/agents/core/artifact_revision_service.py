# src/agents/core/artifact_revision_service.py
"""Artifact 修订闭环。

修订流程：
1. 结果审核退回（NEEDS_REVISION / PARTIALLY_APPROVED）；
2. 重置原步骤为 PENDING；
3. 任务 NEEDS_REVISION → EXECUTING；
4. 重新执行（传入 supersedes_artifact_id）→ 生成 Artifact v2；
5. 旧版本标记 SUPERSEDED，须重新审核。
"""
from dataclasses import replace
from typing import Callable

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentArtifact,
    AgentStep,
    AgentTask,
    ArtifactStatus,
    StepStatus,
    TaskStatus,
)
from .repositories import (
    AgentArtifactRepository,
    AgentStepRepository,
    AgentTaskRepository,
)


class ArtifactRevisionService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        step_repository: AgentStepRepository,
        artifact_repository: AgentArtifactRepository,
        artifact_service,
        task_service,
        execution_service,
        audit_writer: Callable[..., str],
    ) -> None:
        self.task_repository = task_repository
        self.step_repository = step_repository
        self.artifact_repository = artifact_repository
        self.artifact_service = artifact_service
        self.task_service = task_service
        self.execution_service = execution_service
        self.audit_writer = audit_writer

    def prepare_revision(
        self,
        *,
        task_id: str,
        artifact_id: str,
        requested_by: str,
        revision_instruction: str,
    ) -> tuple[AgentTask, AgentStep, AgentArtifact]:
        if not revision_instruction or not revision_instruction.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "结果修订必须提供明确意见"
            )

        task = self.task_repository.get(task_id)
        artifact = self.artifact_repository.get(artifact_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if artifact is None:
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID, "Artifact 不存在",
                correlation_id=task.correlation_id,
            )
        if artifact.task_id != task_id:
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID,
                "Artifact 不属于当前任务",
                correlation_id=task.correlation_id,
            )
        if task.status != TaskStatus.NEEDS_REVISION:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "任务当前不在待修订状态",
                correlation_id=task.correlation_id,
            )
        if artifact.status not in {
            ArtifactStatus.NEEDS_REVISION,
            ArtifactStatus.PARTIALLY_APPROVED,
        }:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "当前 Artifact 不需要修订",
                correlation_id=task.correlation_id,
            )

        step = self.step_repository.get(artifact.step_id)
        if step is None:
            raise AgentError(
                AgentErrorCode.STEP_NOT_FOUND, "原执行步骤不存在",
                correlation_id=task.correlation_id,
            )

        reset_step = replace(
            step,
            status=StepStatus.PENDING,
            started_at=None,
            completed_at=None,
            error_code=None,
            error_summary=None,
        )
        saved_step = self.step_repository.save(reset_step)

        task = self.task_service.transition_task(
            task_id,
            expected_status=TaskStatus.NEEDS_REVISION,
            target_status=TaskStatus.EXECUTING,
            actor_id=requested_by,
            reason=f"按结果审核意见重新执行：{revision_instruction}",
        )

        self.audit_writer(
            action_type="AGENT_RESULT_REVISION_START",
            object_type="AgentArtifact",
            object_id=artifact.artifact_id,
            actor_id=requested_by,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task.task_id,
            step_id=artifact.step_id,
            delta={
                "artifact_family_id": artifact.artifact_family_id,
                "artifact_version": artifact.version,
                "revision_instruction": revision_instruction,
            },
            reason=revision_instruction,
        )
        return task, saved_step, artifact

    def execute_revision(
        self,
        *,
        task_id: str,
        previous_artifact_id: str,
        payload: dict,
        user_id: str,
        user_role: str,
        tool_version: str,
        revision_instruction: str,
    ) -> AgentArtifact:
        _, step, previous = self.prepare_revision(
            task_id=task_id,
            artifact_id=previous_artifact_id,
            requested_by=user_id,
            revision_instruction=revision_instruction,
        )
        return self.execution_service.execute_step(
            task_id=task_id,
            step_id=step.step_id,
            payload=payload,
            user_id=user_id,
            user_role=user_role,
            tool_version=tool_version,
            supersedes_artifact_id=previous.artifact_id,
        )