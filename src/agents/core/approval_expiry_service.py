# src/agents/core/approval_expiry_service.py
"""审批到期处理。"""
from dataclasses import replace
from typing import Callable, Optional

from .approval_service import _is_expired
from .models import ApprovalDecision, ApprovalStatus


class ApprovalExpiryService:
    def __init__(
        self,
        *,
        repository,
        audit_writer: Callable[..., str],
    ) -> None:
        self.repository = repository
        self.audit_writer = audit_writer

    def expire_if_needed(self, approval_id: str) -> Optional[object]:
        approval = self.repository.get(approval_id)
        if approval is None:
            return None
        if approval.status != ApprovalStatus.ACTIVE:
            return approval
        if not _is_expired(approval.expires_at):
            return approval

        expired = replace(
            approval,
            decision=ApprovalDecision.EXPIRED,
            status=ApprovalStatus.EXPIRED,
            comment="审批已过期",
        )
        saved = self.repository.save(expired)
        self.audit_writer(
            action_type="AGENT_APPROVAL_EXPIRE",
            object_type="AgentApproval",
            object_id=saved.approval_id,
            actor_id="system",
            task_id=saved.task_id,
            delta={"expires_at": saved.expires_at},
            reason="审批有效期结束",
        )
        return saved