# src/agents/core/task_service.py
"""Agent 任务服务。"""
from dataclasses import replace
from typing import Callable, Optional
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentPlan,
    AgentTask,
    ApprovalType,
    Domain,
    PlanStatus,
    RiskLevel,
    TaskStatus,
)
from .repositories import AgentPlanRepository, AgentTaskRepository


class AgentTaskService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        plan_repository: AgentPlanRepository,
        audit_writer: Callable[..., str],
        command_service=None,
        task_id_factory: Optional[Callable[[], str]] = None,
        correlation_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.task_repository = task_repository
        self.plan_repository = plan_repository
        self.audit_writer = audit_writer
        self.command_service = command_service
        self.task_id_factory = task_id_factory or (
            lambda: f"TASK-{uuid4().hex[:12].upper()}"
        )
        self.correlation_id_factory = correlation_id_factory or (
            lambda: f"CORR-{uuid4().hex[:12].upper()}"
        )

    def create_task(
        self,
        *,
        task_type: str,
        domain: Domain,
        title: str,
        user_request: str,
        submitted_by: str,
        assigned_agent: str,
        risk_level: RiskLevel,
        scope: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> AgentTask:
        if not user_request.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "任务请求不能为空"
            )

        task = AgentTask(
            task_id=self.task_id_factory(),
            task_type=task_type,
            domain=domain,
            title=title.strip(),
            user_request=user_request.strip(),
            submitted_by=submitted_by,
            assigned_agent=assigned_agent,
            risk_level=risk_level,
            correlation_id=correlation_id or self.correlation_id_factory(),
            scope=dict(scope or {}),
        )

        created = self.task_repository.create(task)

        try:
            self.audit_writer(
                action_type="AGENT_TASK_CREATE",
                object_type="AgentTask",
                object_id=created.task_id,
                actor_id=submitted_by,
                correlation_id=created.correlation_id,
                domain=domain.value,
                task_id=created.task_id,
                delta={
                    "task_type": task_type,
                    "risk_level": risk_level.value,
                    "assigned_agent": assigned_agent,
                },
                reason="创建 Agent 任务",
            )
        except Exception as exc:
            raise AgentError(
                AgentErrorCode.AUDIT_WRITE_FAILED,
                "任务已写入仓储, 但创建审计失败; 禁止继续执行",
                correlation_id=created.correlation_id,
                details={"task_id": created.task_id},
            ) from exc

        return created

    def attach_plan(
        self, task_id: str, *, plan: AgentPlan, actor_id: str
    ) -> AgentTask:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(
                AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}"
            )
        if plan.task_id != task_id:
            raise AgentError(
                AgentErrorCode.PLAN_VERSION_MISMATCH, "计划不属于当前任务",
                correlation_id=task.correlation_id,
            )
        if task.status not in {
            TaskStatus.PLANNING,
            TaskStatus.NEEDS_REVISION,
        }:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "当前任务状态不允许绑定新计划",
                correlation_id=task.correlation_id,
            )

        self.plan_repository.create(plan)
        updated = replace(
            task,
            current_plan_id=plan.plan_id,
            current_plan_version=plan.version,
        )
        saved = self.task_repository.save(updated)

        self.audit_writer(
            action_type="AGENT_PLAN_CREATE",
            object_type="AgentPlan",
            object_id=plan.plan_id,
            actor_id=actor_id,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task.task_id,
            delta={
                "plan_version": plan.version,
                "status": plan.status.value,
            },
            reason="创建并绑定 Agent 计划",
        )
        return saved

    def submit_plan_for_review(
        self, task_id: str, *, actor_id: str
    ) -> AgentTask:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(
                AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}"
            )
        if not task.current_plan_id:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_FOUND, "任务尚未绑定计划",
                correlation_id=task.correlation_id,
            )

        # 先同步 Plan 状态为 PLAN_REVIEW；Task 再迁移。
        # 这样 execution_service 的 plan.status == APPROVED 检查才有意义。
        plan = self.plan_repository.get(task.current_plan_id)
        if plan is not None and plan.status != PlanStatus.PLAN_REVIEW:
            plan.status = PlanStatus.PLAN_REVIEW
            self.plan_repository.save(plan)

        updated = self.task_repository.transition(
            task_id,
            expected_status=TaskStatus.PLANNING,
            target_status=TaskStatus.PLAN_REVIEW,
        )

        self.audit_writer(
            action_type="AGENT_TASK_STATUS_CHANGE",
            object_type="AgentTask",
            object_id=task_id,
            actor_id=actor_id,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task_id,
            delta={
                "status": {
                    "before": TaskStatus.PLANNING.value,
                    "after": TaskStatus.PLAN_REVIEW.value,
                }
            },
            reason="提交 Agent 计划审核",
        )
        return updated

    def approve_plan(
        self,
        task_id: str,
        *,
        approval_id: str,
        approval_validator: Callable[..., bool],
        actor_id: str,
    ) -> AgentTask:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(
                AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}"
            )
        if not task.current_plan_id:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_FOUND, "任务尚未绑定计划",
                correlation_id=task.correlation_id,
            )

        # 注意：必须传 ApprovalType.PLAN 枚举；传字符串会让 is_valid_approval
        # 的 `approval.approval_type != approval_type` 恒为 True，从而永远返回 False。
        valid = approval_validator(
            approval_id,
            task_id=task.task_id,
            approval_type=ApprovalType.PLAN,
            plan_id=task.current_plan_id,
            plan_version=task.current_plan_version,
        )
        if not valid:
            raise AgentError(
                AgentErrorCode.APPROVAL_REQUIRED,
                "没有匹配当前计划版本的有效批准",
                correlation_id=task.correlation_id,
            )

        # 先迁移 Task，成功后再同步 Plan，避免出现 Plan 已 APPROVED 但 Task 卡在 PLAN_REVIEW。
        updated = self.task_repository.transition(
            task_id,
            expected_status=TaskStatus.PLAN_REVIEW,
            target_status=TaskStatus.APPROVED,
        )

        plan = self.plan_repository.get(task.current_plan_id)
        if plan is not None and plan.status != PlanStatus.APPROVED:
            plan.status = PlanStatus.APPROVED
            self.plan_repository.save(plan)

        self.audit_writer(
            action_type="AGENT_PLAN_APPROVE",
            object_type="AgentPlan",
            object_id=task.current_plan_id,
            actor_id=actor_id,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task.task_id,
            delta={
                "approval_id": approval_id,
                "plan_version": task.current_plan_version,
            },
            reason="Agent 计划审核通过",
        )
        return updated

    def transition_task(
        self,
        task_id: str,
        *,
        expected_status: TaskStatus,
        target_status: TaskStatus,
        actor_id: str,
        reason: str,
    ) -> AgentTask:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(
                AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}"
            )

        # 优先使用事务化命令服务（生产路径）
        if self.command_service is not None:
            self.command_service.transition_task(
                task_id=task_id,
                expected_status=expected_status,
                target_status=target_status,
                actor_id=actor_id,
                reason=reason,
            )
            updated = self.task_repository.get(task_id)
            if updated is None:
                raise AgentError(
                    AgentErrorCode.TASK_NOT_FOUND,
                    "事务完成后无法读取任务",
                )
            return updated

        # 内存路径（测试用）：先更新再写审计
        updated = self.task_repository.transition(
            task_id,
            expected_status=expected_status,
            target_status=target_status,
        )

        action_type = {
            TaskStatus.PAUSED: "AGENT_PAUSE",
            TaskStatus.CANCELLED: "AGENT_CANCEL",
            TaskStatus.EXECUTING: (
                "AGENT_RESUME"
                if expected_status == TaskStatus.PAUSED
                else "AGENT_RUN_START"
            ),
        }.get(target_status, "AGENT_TASK_STATUS_CHANGE")

        self.audit_writer(
            action_type=action_type,
            object_type="AgentTask",
            object_id=task_id,
            actor_id=actor_id,
            correlation_id=task.correlation_id,
            domain=task.domain.value,
            task_id=task_id,
            delta={
                "status": {
                    "before": expected_status.value,
                    "after": target_status.value,
                }
            },
            reason=reason,
        )
        return updated