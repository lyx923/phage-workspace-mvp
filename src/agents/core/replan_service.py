# src/agents/core/replan_service.py
"""Agent 重规划服务。

从 NEEDS_REVISION 生成新版本计划；旧 ContextSnapshot 在下次 validate 时
会因为 plan_version 不匹配自动失效，无需显式标记 INVALIDATED。
"""
from dataclasses import replace
from typing import Callable
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentPlan,
    PlanStatus,
    StepStatus,
    TaskStatus,
)
from .repositories import (
    AgentPlanRepository,
    AgentTaskRepository,
)


class AgentReplanService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        plan_repository: AgentPlanRepository,
        task_service,
        audit_writer: Callable[..., str],
    ) -> None:
        self.task_repository = task_repository
        self.plan_repository = plan_repository
        self.task_service = task_service
        self.audit_writer = audit_writer

    def create_revised_plan(
        self,
        task_id: str,
        *,
        revision_comment: str,
        generated_by: str,
    ) -> AgentPlan:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status != TaskStatus.NEEDS_REVISION:
            raise AgentError(
                AgentErrorCode.REPLAN_REQUIRED,
                "任务当前不在待修订状态",
                correlation_id=task.correlation_id,
            )
        if not task.current_plan_id:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_FOUND, "任务没有旧计划",
                correlation_id=task.correlation_id,
            )
        old_plan = self.plan_repository.get(task.current_plan_id)
        if old_plan is None:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_FOUND, "旧计划不存在",
                correlation_id=task.correlation_id,
            )

        new_plan_id = f"PLAN-{uuid4().hex[:12].upper()}"
        new_steps = [
            replace(
                step,
                step_id=f"STEP-{uuid4().hex[:12].upper()}",
                plan_id=new_plan_id,
                status=StepStatus.PENDING,
                retry_count=0,
                started_at=None,
                completed_at=None,
                error_code=None,
                error_summary=None,
            )
            for step in old_plan.steps
        ]
        revised = AgentPlan(
            plan_id=new_plan_id,
            task_id=task.task_id,
            version=old_plan.version + 1,
            goal_summary=old_plan.goal_summary,
            assumptions=[
                *old_plan.assumptions,
                f"人工退回意见：{revision_comment}",
            ],
            open_questions=list(old_plan.open_questions),
            required_inputs=list(old_plan.required_inputs),
            expected_artifacts=list(old_plan.expected_artifacts),
            steps=new_steps,
            approval_required=True,
            generated_by=generated_by,
            supersedes_plan_id=old_plan.plan_id,
            status=PlanStatus.VALIDATED,
        )

        self.plan_repository.create(revised)
        task.current_plan_id = revised.plan_id
        task.current_plan_version = revised.version
        task.context_snapshot_id = None
        self.task_repository.save(task)
        self.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.NEEDS_REVISION,
            target_status=TaskStatus.PLANNING,
            actor_id=generated_by,
            reason="创建修订计划",
        )

        self.audit_writer(
            action_type="AGENT_PLAN_REVISE",
            object_type="AgentPlan",
            object_id=revised.plan_id,
            actor_id=generated_by,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task.task_id,
            delta={
                "old_plan_id": old_plan.plan_id,
                "new_plan_id": revised.plan_id,
                "new_plan_version": revised.version,
                "revision_comment": revision_comment,
            },
            reason=revision_comment,
        )
        return revised