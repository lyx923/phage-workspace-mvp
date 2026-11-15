# src/agents/core/execution_service.py
"""受控 Agent 最小执行器。"""
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Dict, Optional

from .artifact_service import AgentArtifactService
from .context_service import ContextService
from .errors import AgentError, AgentErrorCode
from .models import (
    AgentArtifact, ArtifactType, Domain, PermissionRequest, PlanStatus,
    StepStatus, TaskStatus,
)
from .permission_service import PermissionService
from .registry import ToolRegistry
from .repositories import (
    AgentArtifactRepository, AgentPlanRepository, AgentStepRepository,
    AgentTaskRepository, ContextSnapshotRepository,
)
from src.agents.tools.base import AgentTool, ToolExecutionContext

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

_ARTIFACT_TYPE_MAP = {
    "query_result": ArtifactType.QUERY_RESULT,
    "missing_data_report": ArtifactType.MISSING_DATA_REPORT,
    "validation_findings": ArtifactType.VALIDATION_FINDINGS,
    "comparison_table": ArtifactType.COMPARISON_TABLE,
    "draft_claim": ArtifactType.DRAFT_CLAIM,
    "draft_evidence_package": ArtifactType.DRAFT_EVIDENCE_PACKAGE,
    "intelligence_brief_draft": ArtifactType.INTELLIGENCE_BRIEF_DRAFT,
    "conflict_report": ArtifactType.CONFLICT_REPORT,
    "final_report": ArtifactType.FINAL_REPORT,
}

class AgentExecutionService:
    def __init__(
        self,
        *,
        task_repository: AgentTaskRepository,
        plan_repository: AgentPlanRepository,
        step_repository: AgentStepRepository,
        context_repository: ContextSnapshotRepository,
        artifact_repository: AgentArtifactRepository,
        artifact_service: AgentArtifactService,
        permission_service: PermissionService,
        context_service: ContextService,
        tool_registry: ToolRegistry,
        tools: Dict[str, AgentTool],
        audit_writer: Callable[..., str],
        task_service=None,
    ) -> None:
        self.task_repository = task_repository
        self.plan_repository = plan_repository
        self.step_repository = step_repository
        self.context_repository = context_repository
        self.artifact_repository = artifact_repository
        self.artifact_service = artifact_service
        self.permission_service = permission_service
        self.context_service = context_service
        self.tool_registry = tool_registry
        self.tools = tools
        self.audit_writer = audit_writer
        self.task_service = task_service

    def execute_step(
        self,
        *,
        task_id: str,
        step_id: str,
        payload: dict,
        user_id: str,
        user_role: str,
        tool_version: str,
        supersedes_artifact_id: Optional[str] = None,
    ) -> AgentArtifact:
        task = self.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}")
        if task.status == TaskStatus.PAUSED:
            raise AgentError(AgentErrorCode.TASK_PAUSED, "任务已暂停", correlation_id=task.correlation_id)
        if task.status == TaskStatus.CANCELLED:
            raise AgentError(AgentErrorCode.TASK_CANCELLED, "任务已取消", correlation_id=task.correlation_id)
        if task.status != TaskStatus.EXECUTING:
            raise AgentError(AgentErrorCode.INVALID_STATE_TRANSITION, "只有 EXECUTING 任务可以执行步骤", correlation_id=task.correlation_id)

        plan = self.plan_repository.get(task.current_plan_id) if task.current_plan_id else None
        if plan is None:
            raise AgentError(AgentErrorCode.PLAN_NOT_FOUND, "任务当前计划不存在", correlation_id=task.correlation_id)

        # 严格校验计划状态
        if plan.status != PlanStatus.APPROVED:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_APPROVED,
                "计划状态不是 APPROVED，拒绝执行；请走计划审核流程",
                correlation_id=task.correlation_id,
                details={
                    "plan_id": plan.plan_id,
                    "plan_status": plan.status.value,
                },
            )

        if plan.version != task.current_plan_version:
            raise AgentError(AgentErrorCode.PLAN_VERSION_MISMATCH, "任务与计划版本不一致", correlation_id=task.correlation_id)

        step = self.step_repository.get(step_id)
        if step is None:
            raise AgentError(AgentErrorCode.STEP_NOT_FOUND, f"步骤不存在: {step_id}", correlation_id=task.correlation_id)
        if step.plan_id != plan.plan_id:
            raise AgentError(AgentErrorCode.PLAN_VERSION_MISMATCH, "步骤不属于当前计划", correlation_id=task.correlation_id)
        if step.status != StepStatus.PENDING:
            raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, "只有 PENDING 步骤可以首次执行", correlation_id=task.correlation_id)
        if step.approval_required:
            raise AgentError(AgentErrorCode.APPROVAL_REQUIRED, "该步骤需要独立审批", correlation_id=task.correlation_id)
        if not step.tool_id:
            raise AgentError(AgentErrorCode.TOOL_NOT_REGISTERED, "当前步骤没有指定工具", correlation_id=task.correlation_id)

        planned_tool_version = step.tool_version or tool_version
        if step.tool_version is not None and step.tool_version != tool_version:
            raise AgentError(AgentErrorCode.TOOL_NOT_REGISTERED, "请求工具版本与计划版本不一致", correlation_id=task.correlation_id)

        tool_definition = self.tool_registry.require_domain(step.tool_id, planned_tool_version, task.domain)
        tool = self.tools.get(step.tool_id)
        if tool is None:
            raise AgentError(AgentErrorCode.TOOL_NOT_REGISTERED, "工具有注册定义，但没有运行实现", correlation_id=task.correlation_id)
        if tool.version != planned_tool_version:
            raise AgentError(AgentErrorCode.TOOL_NOT_REGISTERED, "工具实现版本与注册版本不一致", correlation_id=task.correlation_id)
        if user_role not in tool_definition.allowed_roles:
            raise AgentError(AgentErrorCode.PERMISSION_DENIED, "当前角色不在工具允许角色范围内", correlation_id=task.correlation_id)

        permission = self.permission_service.require(
            PermissionRequest(
                user_id=user_id, user_role=user_role, agent_id=task.assigned_agent, agent_roles=[],
                resource=tool_definition.permission_resource, action=tool_definition.permission_action,
                domain=task.domain, task_id=task.task_id, project_scope=task.scope,
            )
        )

        if not task.context_snapshot_id:
            raise AgentError(AgentErrorCode.CONTEXT_INVALID, "任务没有 ContextSnapshot", correlation_id=task.correlation_id)
        snapshot = self.context_repository.get(task.context_snapshot_id)
        if snapshot is None:
            raise AgentError(AgentErrorCode.CONTEXT_INVALID, "ContextSnapshot 不存在", correlation_id=task.correlation_id)

        self.context_service.validate_snapshot(
            snapshot, task_id=task.task_id, plan_id=plan.plan_id, plan_version=plan.version,
            domain=task.domain, current_tool_registry_version=self.tool_registry.version,
        )

        executing_step = replace(step, status=StepStatus.EXECUTING, started_at=_utc_now_iso())
        executing_step = self.step_repository.save(executing_step)

        self.audit_writer(
            action_type="AGENT_STEP_START", object_type="AgentStep", object_id=step.step_id,
            actor_id=task.assigned_agent, correlation_id=task.correlation_id, domain=task.domain.value,
            task_id=task.task_id, step_id=step.step_id,
            delta={"tool_id": step.tool_id, "tool_version": planned_tool_version, "permission_decision": permission.to_dict()},
            reason="开始执行 Agent 步骤",
        )

        context = ToolExecutionContext(
            task_id=task.task_id, step_id=step.step_id, user_id=user_id, user_role=user_role,
            agent_id=task.assigned_agent, domain=task.domain.value, permission_scope=snapshot.permission_scope,
            context_snapshot_id=snapshot.context_snapshot_id, correlation_id=task.correlation_id,
            schema_version=snapshot.schema_version,
        )

        try:
            tool.validate_input(payload)
            result = tool.execute(payload, context)

            artifact_type = _ARTIFACT_TYPE_MAP.get(result.artifact_type or "")
            if artifact_type is None:
                raise AgentError(AgentErrorCode.TOOL_OUTPUT_INVALID, f"工具返回了未允许的 Artifact 类型: {result.artifact_type}", correlation_id=task.correlation_id)

            artifact = self.artifact_service.create(
                task_id=task.task_id, step_id=step.step_id, artifact_type=artifact_type,
                content=result.data or {}, created_by=task.assigned_agent,
                schema_version=snapshot.schema_version, context_snapshot_id=snapshot.context_snapshot_id,
                source_references=result.source_references, correlation_id=task.correlation_id,
                domain=task.domain.value, supersedes_artifact_id=supersedes_artifact_id,
            )

            completed_step = replace(executing_step, status=StepStatus.COMPLETED, completed_at=_utc_now_iso())
            self.step_repository.save(completed_step)

            self.audit_writer(
                action_type="AGENT_STEP_COMPLETE", object_type="AgentStep", object_id=step.step_id,
                actor_id=task.assigned_agent, correlation_id=task.correlation_id, domain=task.domain.value,
                task_id=task.task_id, step_id=step.step_id,
                delta={"artifact_id": artifact.artifact_id, "tool_status": result.status, "warnings": result.warnings},
                reason="Agent 步骤执行完成",
            )

            if self.task_service is not None:
                other_steps = [s for s in self.step_repository.list_for_plan(plan.plan_id) if s.step_id != step.step_id]
                all_others_done = all(s.status in {StepStatus.COMPLETED, StepStatus.SKIPPED} for s in other_steps)
                if all_others_done:
                    try:
                        self.artifact_service.submit_for_review(artifact.artifact_id, actor_id=task.assigned_agent, correlation_id=task.correlation_id, domain=task.domain.value)
                        self.task_service.transition_task(task.task_id, expected_status=TaskStatus.EXECUTING, target_status=TaskStatus.RESULT_REVIEW, actor_id=task.assigned_agent, reason="当前计划全部步骤完成，提交结果审核")
                    except Exception as submit_err:
                        self.audit_writer(
                            action_type="AGENT_STEP_FAIL", object_type="AgentStep", object_id=step.step_id,
                            actor_id=task.assigned_agent, correlation_id=task.correlation_id, domain=task.domain.value,
                            task_id=task.task_id, step_id=step.step_id, delta={"error": str(submit_err), "phase": "auto_submit"}, reason="自动送审失败",
                        )
            return artifact

        except Exception as exc:
            failed_step = replace(
                executing_step, status=StepStatus.FAILED, completed_at=_utc_now_iso(),
                error_code=exc.code.value if isinstance(exc, AgentError) else "AGENT_TOOL_EXECUTION_FAILED",
                error_summary=exc.message if isinstance(exc, AgentError) else "工具执行失败",
            )
            try:
                self.step_repository.save(failed_step)
            except Exception:
                pass
                
            self.audit_writer(
                action_type="AGENT_STEP_FAIL", object_type="AgentStep", object_id=step.step_id,
                actor_id=task.assigned_agent, correlation_id=task.correlation_id, domain=task.domain.value,
                task_id=task.task_id, step_id=step.step_id,
                delta={"error_code": failed_step.error_code, "exception_type": type(exc).__name__},
                reason=failed_step.error_summary or "Agent 步骤失败",
            )

            # ★ 新增：如果步骤失败，且当前任务还是执行中，把任务状态同步转为 FAILED
            if self.task_service is not None:
                try:
                    current_task = self.task_repository.get(task_id)
                    if current_task and current_task.status == TaskStatus.EXECUTING:
                        self.task_service.transition_task(
                            task_id, 
                            expected_status=TaskStatus.EXECUTING, 
                            target_status=TaskStatus.FAILED, 
                            actor_id=task.assigned_agent, 
                            reason=f"步骤执行失败: {failed_step.error_summary}"
                        )
                except Exception:
                    pass # 避免掩盖真实的执行错误

            raise