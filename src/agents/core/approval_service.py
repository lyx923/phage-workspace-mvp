# src/agents/core/approval_service.py
"""Agent 审批服务。

审批必须绑定具体任务、计划或产物版本。
Agent 不能作为正式审批人。
"""
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, List, Optional
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentApproval,
    ApprovalDecision,
    ApprovalStatus,
    ApprovalType,
)
from .repositories import AgentApprovalRepository


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AgentError(
            AgentErrorCode.TOOL_INPUT_INVALID,
            "审批 expires_at 不是合法 ISO 8601 时间",
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_expired(
    expires_at: Optional[str],
    *,
    now: Optional[datetime] = None,
) -> bool:
    parsed = _parse_datetime(expires_at)
    if parsed is None:
        return False
    current = now or datetime.now(timezone.utc)
    return current >= parsed


class ApprovalService:
    def __init__(
        self,
        repository: AgentApprovalRepository,
        *,
        audit_writer: Callable[..., str],
        id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.repository = repository
        self.audit_writer = audit_writer
        self.id_factory = id_factory or (
            lambda: f"APPR-{uuid4().hex[:12].upper()}"
        )

    def request_approval(
        self,
        *,
        task_id: str,
        approval_type: ApprovalType,
        requested_by: str,
        requested_from_role: str,
        plan_id: Optional[str] = None,
        plan_version: Optional[int] = None,
        requested_from_user: Optional[str] = None,
        step_id: Optional[str] = None,
        artifact_id: Optional[str] = None,
        artifact_version: Optional[int] = None,
        context_snapshot_id: Optional[str] = None,
        expires_at: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> AgentApproval:
        # 提交时如未给 expires_at 则不检查；给了就必须合法
        _parse_datetime(expires_at)

        approval = AgentApproval(
            approval_id=self.id_factory(),
            task_id=task_id,
            approval_type=approval_type,
            requested_by=requested_by,
            requested_from_role=requested_from_role,
            requested_from_user=requested_from_user,
            plan_id=plan_id,
            plan_version=plan_version,
            step_id=step_id,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            context_snapshot_id=context_snapshot_id,
            expires_at=expires_at,
        )
        created = self.repository.create(approval)

        self.audit_writer(
            action_type="AGENT_APPROVAL_REQUEST",
            object_type="AgentApproval",
            object_id=created.approval_id,
            actor_id=requested_by,
            correlation_id=correlation_id,
            delta={
                "task_id": task_id,
                "approval_type": approval_type.value,
                "plan_id": plan_id,
                "plan_version": plan_version,
                "artifact_id": artifact_id,
                "artifact_version": artifact_version,
                "expires_at": expires_at,
            },
            reason="创建 Agent 审批请求",
        )
        return created

    def decide(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        decided_by: str,
        decided_by_role: str,
        comment: str = "",
        approved_scope: Optional[List[str]] = None,
        rejected_scope: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
    ) -> AgentApproval:
        approval = self.repository.get(approval_id)
        if approval is None:
            raise AgentError(
                AgentErrorCode.APPROVAL_REQUIRED,
                f"审批不存在: {approval_id}",
                correlation_id=correlation_id,
            )

        if _is_expired(approval.expires_at):
            expired = replace(
                approval,
                decision=ApprovalDecision.EXPIRED,
                status=ApprovalStatus.EXPIRED,
                decided_at=_utc_now_iso(),
                comment="审批已过期",
            )
            try:
                self.repository.save(expired)
            except Exception:
                pass
            self.audit_writer(
                action_type="AGENT_APPROVAL_EXPIRE",
                object_type="AgentApproval",
                object_id=approval.approval_id,
                actor_id="system",
                correlation_id=correlation_id,
                task_id=approval.task_id,
                delta={
                    "status": {
                        "before": ApprovalStatus.ACTIVE.value,
                        "after": ApprovalStatus.EXPIRED.value,
                    }
                },
                reason="审批超过有效期",
            )
            raise AgentError(
                AgentErrorCode.APPROVAL_EXPIRED,
                "审批已过期",
                correlation_id=correlation_id,
            )

        if approval.status != ApprovalStatus.ACTIVE:
            raise AgentError(
                AgentErrorCode.APPROVAL_EXPIRED,
                "审批已经失效或被使用",
                correlation_id=correlation_id,
                details={
                    "approval_id": approval_id,
                    "status": approval.status.value,
                },
            )

        if approval.decision != ApprovalDecision.PENDING:
            raise AgentError(
                AgentErrorCode.DUPLICATE_OPERATION,
                "审批已经作出决定",
                correlation_id=correlation_id,
            )

        if (
            approval.requested_from_user is not None
            and approval.requested_from_user != decided_by
        ):
            raise AgentError(
                AgentErrorCode.PERMISSION_DENIED,
                "该审批已指定其他审核人",
                correlation_id=correlation_id,
            )

        if approval.requested_from_role != decided_by_role:
            raise AgentError(
                AgentErrorCode.PERMISSION_DENIED,
                "当前角色不是该审批要求的角色",
                correlation_id=correlation_id,
                details={
                    "required_role": approval.requested_from_role,
                    "actual_role": decided_by_role,
                },
            )

        if decided_by == approval.requested_by:
            raise AgentError(
                AgentErrorCode.PERMISSION_DENIED,
                "提交人不能审批自己提交的 Agent 请求",
                correlation_id=correlation_id,
            )

        if decision == ApprovalDecision.PENDING:
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "不能把审批决定设置为 PENDING",
                correlation_id=correlation_id,
            )

        if (
            decision == ApprovalDecision.PARTIALLY_APPROVED
            and not approved_scope
        ):
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "部分批准必须明确 approved_scope",
                correlation_id=correlation_id,
            )

        updated = replace(
            approval,
            decision=decision,
            comment=comment,
            approved_scope=list(approved_scope or []),
            rejected_scope=list(rejected_scope or []),
            decided_by=decided_by,
            decided_at=_utc_now_iso(),
        )
        saved = self.repository.save(updated)

        action_type = {
            ApprovalDecision.APPROVED: "AGENT_APPROVAL_APPROVE",
            ApprovalDecision.PARTIALLY_APPROVED: "AGENT_APPROVAL_APPROVE",
            ApprovalDecision.NEEDS_REVISION: "AGENT_APPROVAL_REJECT",
            ApprovalDecision.REJECTED: "AGENT_APPROVAL_REJECT",
            ApprovalDecision.WITHDRAWN: "AGENT_APPROVAL_WITHDRAW",
            ApprovalDecision.EXPIRED: "AGENT_APPROVAL_EXPIRE",
            ApprovalDecision.SUPERSEDED: "AGENT_APPROVAL_SUPERSEDE",
        }.get(decision, "AGENT_APPROVAL_APPROVE")

        self.audit_writer(
            action_type=action_type,
            object_type="AgentApproval",
            object_id=saved.approval_id,
            actor_id=decided_by,
            correlation_id=correlation_id,
            delta={
                "decision": {
                    "before": ApprovalDecision.PENDING.value,
                    "after": decision.value,
                },
                "approved_scope": saved.approved_scope,
                "rejected_scope": saved.rejected_scope,
            },
            reason=comment,
        )
        return saved

    def is_valid_approval(
        self,
        approval_id: str,
        *,
        task_id: str,
        approval_type: ApprovalType,
        plan_id: Optional[str] = None,
        plan_version: Optional[int] = None,
        artifact_id: Optional[str] = None,
        artifact_version: Optional[int] = None,
    ) -> bool:
        approval = self.repository.get(approval_id)
        if approval is None:
            return False
        if approval.status != ApprovalStatus.ACTIVE:
            return False
        if _is_expired(approval.expires_at):
            return False
        if approval.decision not in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.PARTIALLY_APPROVED,
        }:
            return False
        if approval.task_id != task_id:
            return False
        if approval.approval_type != approval_type:
            return False
        if plan_id is not None and approval.plan_id != plan_id:
            return False
        if (
            plan_version is not None
            and approval.plan_version != plan_version
        ):
            return False
        if artifact_id is not None and approval.artifact_id != artifact_id:
            return False
        if (
            artifact_version is not None
            and approval.artifact_version != artifact_version
        ):
            return False
        return True

    def consume(
        self,
        approval_id: str,
        *,
        actor_id: str,
        correlation_id: Optional[str] = None,
    ) -> AgentApproval:
        approval = self.repository.get(approval_id)
        if approval is None:
            raise AgentError(
                AgentErrorCode.APPROVAL_REQUIRED,
                "审批不存在",
                correlation_id=correlation_id,
            )
        if _is_expired(approval.expires_at):
            raise AgentError(
                AgentErrorCode.APPROVAL_EXPIRED,
                "审批已过期，不能消费",
                correlation_id=correlation_id,
            )
        if approval.status != ApprovalStatus.ACTIVE:
            raise AgentError(
                AgentErrorCode.APPROVAL_EXPIRED,
                "审批不是可消费状态",
                correlation_id=correlation_id,
            )
        if approval.decision not in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.PARTIALLY_APPROVED,
            ApprovalDecision.NEEDS_REVISION,
            ApprovalDecision.REJECTED,
        }:
            raise AgentError(
                AgentErrorCode.APPROVAL_REQUIRED,
                "审批尚无可消费的最终决定",
                correlation_id=correlation_id,
            )

        updated = replace(approval, status=ApprovalStatus.USED)
        saved = self.repository.save(updated)

        self.audit_writer(
            action_type="AGENT_APPROVAL_CONSUME",
            object_type="AgentApproval",
            object_id=approval_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            delta={
                "status": {
                    "before": ApprovalStatus.ACTIVE.value,
                    "after": ApprovalStatus.USED.value,
                }
            },
            reason="消费 Agent 审批决定",
        )
        return saved