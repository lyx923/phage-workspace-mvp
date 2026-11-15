# src/agents/core/result_review_service.py
"""Agent 结果审核与任务状态联动。

批准只表示 Agent 产物通过流程审核，不代表产物中的实验事实、
科学主张或临床结论自动成为正式业务事实。
"""
from datetime import datetime, timezone
from typing import Callable, Optional

from .approval_service import ApprovalService
from .errors import AgentError, AgentErrorCode
from .models import (
    ApprovalDecision,
    ApprovalType,
    ArtifactStatus,
    TaskStatus,
)
from .repositories import (
    AgentArtifactRepository,
    AgentTaskRepository,
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentResultReviewService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        artifact_repository: AgentArtifactRepository,
        approval_service: ApprovalService,
        task_service,
        audit_writer: Callable[..., str],
    ) -> None:
        self.task_repository = task_repository
        self.artifact_repository = artifact_repository
        self.approval_service = approval_service
        self.task_service = task_service
        self.audit_writer = audit_writer

    def request_review(
        self,
        *,
        task_id: str,
        artifact_id: str,
        requested_by: str,
        reviewer_role: str,
        reviewer_user_id: Optional[str] = None,
    ):
        task = self.task_repository.get(task_id)
        artifact = self.artifact_repository.get(artifact_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if artifact is None:
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID, "Artifact 不存在",
                correlation_id=task.correlation_id,
            )
        if task.status != TaskStatus.RESULT_REVIEW:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "任务当前不在结果审核状态",
                correlation_id=task.correlation_id,
            )
        if artifact.status != ArtifactStatus.RESULT_REVIEW:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "Artifact 当前不在结果审核状态",
                correlation_id=task.correlation_id,
            )
        return self.approval_service.request_approval(
            task_id=task_id,
            approval_type=ApprovalType.RESULT,
            requested_by=requested_by,
            requested_from_role=reviewer_role,
            requested_from_user=reviewer_user_id,
            plan_id=task.current_plan_id,
            plan_version=task.current_plan_version,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.version,
            context_snapshot_id=task.context_snapshot_id,
            correlation_id=task.correlation_id,
        )

    def decide(
        self,
        *,
        approval_id: str,
        decision: ApprovalDecision,
        reviewer_id: str,
        reviewer_role: str,
        comment: str,
        approved_scope: Optional[list] = None,
        rejected_scope: Optional[list] = None,
    ):
        approval = self.approval_service.repository.get(approval_id)
        if approval is None:
            raise AgentError(AgentErrorCode.APPROVAL_REQUIRED, "结果审批不存在")
        if approval.approval_type != ApprovalType.RESULT:
            raise AgentError(AgentErrorCode.APPROVAL_REQUIRED, "审批类型不是 RESULT")

        task = self.task_repository.get(approval.task_id)
        artifact = self.artifact_repository.get(approval.artifact_id or "")
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if artifact is None:
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID, "待审核 Artifact 不存在",
                correlation_id=task.correlation_id,
            )

        self.approval_service.decide(
            approval_id,
            decision=decision,
            decided_by=reviewer_id,
            decided_by_role=reviewer_role,
            comment=comment,
            approved_scope=approved_scope,
            rejected_scope=rejected_scope,
            correlation_id=task.correlation_id,
        )

        if decision == ApprovalDecision.APPROVED:
            artifact.status = ArtifactStatus.APPROVED
            artifact.reviewed_by = reviewer_id
            artifact.reviewed_at = _utc_now_iso()
            saved = self.artifact_repository.save(artifact)
            self.task_service.transition_task(
                task.task_id,
                expected_status=TaskStatus.RESULT_REVIEW,
                target_status=TaskStatus.COMPLETED,
                actor_id=reviewer_id,
                reason="Agent 结果审核通过；仅表示执行报告获批",
            )
            self.approval_service.consume(
                approval_id,
                actor_id=reviewer_id,
                correlation_id=task.correlation_id,
            )
            self.audit_writer(
                action_type="AGENT_RESULT_APPROVE",
                object_type="AgentArtifact",
                object_id=artifact.artifact_id,
                actor_id=reviewer_id,
                correlation_id=task.correlation_id,
                domain=task.domain.value,
                task_id=task.task_id,
                step_id=artifact.step_id,
                delta={
                    "artifact_status": {
                        "before": ArtifactStatus.RESULT_REVIEW.value,
                        "after": ArtifactStatus.APPROVED.value,
                    },
                    "approval_id": approval_id,
                },
                reason=comment,
            )
            return saved

        if decision == ApprovalDecision.PARTIALLY_APPROVED:
            artifact.status = ArtifactStatus.PARTIALLY_APPROVED
            artifact.reviewed_by = reviewer_id
            artifact.reviewed_at = _utc_now_iso()
            saved = self.artifact_repository.save(artifact)
            self.task_service.transition_task(
                task.task_id,
                expected_status=TaskStatus.RESULT_REVIEW,
                target_status=TaskStatus.NEEDS_REVISION,
                actor_id=reviewer_id,
                reason="Agent 结果部分批准，需要修订",
            )
            self.approval_service.consume(
                approval_id,
                actor_id=reviewer_id,
                correlation_id=task.correlation_id,
            )
            return saved

        if decision == ApprovalDecision.NEEDS_REVISION:
            artifact.status = ArtifactStatus.NEEDS_REVISION
            artifact.reviewed_by = reviewer_id
            artifact.reviewed_at = _utc_now_iso()
            saved = self.artifact_repository.save(artifact)
            self.task_service.transition_task(
                task.task_id,
                expected_status=TaskStatus.RESULT_REVIEW,
                target_status=TaskStatus.NEEDS_REVISION,
                actor_id=reviewer_id,
                reason=comment,
            )
            return saved

        if decision == ApprovalDecision.REJECTED:
            artifact.status = ArtifactStatus.REJECTED
            artifact.reviewed_by = reviewer_id
            artifact.reviewed_at = _utc_now_iso()
            saved = self.artifact_repository.save(artifact)
            self.task_service.transition_task(
                task.task_id,
                expected_status=TaskStatus.RESULT_REVIEW,
                target_status=TaskStatus.REJECTED,
                actor_id=reviewer_id,
                reason=comment,
            )
            return saved

        raise AgentError(
            AgentErrorCode.TOOL_INPUT_INVALID,
            "结果审核只支持 APPROVED / PARTIALLY_APPROVED / NEEDS_REVISION / REJECTED",
            correlation_id=task.correlation_id,
        )