# src/agents/core/scientific_s1_service.py
"""SCI-S1 固定模板任务创建服务。不调用 LLM。"""
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentPlan,
    AgentStep,
    Domain,
    PlanStatus,
    RiskLevel,
    StepType,
    TaskStatus,
)


class ScientificS1Service:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def create_task(
        self,
        *,
        experiment_batch_id: str,
        submitted_by: str,
        user_role: str,
    ):
        if not experiment_batch_id.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "experiment_batch_id 不能为空",
            )

        task = self.runtime.task_service.create_task(
            task_type="SCI-S1-BATCH-COMPLETENESS",
            domain=Domain.SCIENTIFIC,
            title=f"实验批次完整性检查：{experiment_batch_id}",
            user_request=f"检查实验批次 {experiment_batch_id} 的数据完整性",
            submitted_by=submitted_by,
            assigned_agent="scientific-agent",
            risk_level=RiskLevel.R0,
            scope={"experiment_batch_id": experiment_batch_id},
        )
        task = self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.DRAFT,
            target_status=TaskStatus.UNDERSTANDING,
            actor_id=submitted_by,
            reason="开始解析 SCI-S1 固定模板任务",
        )
        task = self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.UNDERSTANDING,
            target_status=TaskStatus.PLANNING,
            actor_id="scientific-agent",
            reason="SCI-S1 模板匹配成功",
        )

        plan_id = f"PLAN-{uuid4().hex[:12].upper()}"
        step = AgentStep(
            step_id=f"STEP-{uuid4().hex[:12].upper()}",
            plan_id=plan_id,
            sequence=1,
            step_type=StepType.VALIDATE_DATA,
            name="检查实验批次完整性",
            description=(
                "只读检查批次关联记录、来源、审核和页面明确必填字段"
            ),
            tool_id="scientific.batch_completeness",
            tool_version=self.runtime.batch_tool.version,
            input_references=["experiment_batch_id"],
            expected_output_type="missing_data_report",
            risk_level=RiskLevel.R0,
            approval_required=False,
            can_retry=True,
        )
        plan = AgentPlan(
            plan_id=plan_id,
            task_id=task.task_id,
            version=1,
            goal_summary="生成实验批次数据完整性报告，不修改任何业务数据",
            assumptions=[],
            open_questions=[],
            required_inputs=["experiment_batch_id"],
            expected_artifacts=["missing_data_report"],
            steps=[step],
            approval_required=True,
            generated_by="SCI-S1-TEMPLATE",
            status=PlanStatus.VALIDATED,
        )
        self.runtime.task_service.attach_plan(
            task.task_id, plan=plan, actor_id="scientific-agent"
        )
        self.runtime.task_service.submit_plan_for_review(
            task.task_id, actor_id="scientific-agent"
        )
        return task, plan

    def activate_approved_task(
        self,
        *,
        task_id: str,
        actor_id: str,
        user_role: str,
    ):
        """在任务已 APPROVED 后创建 ContextSnapshot 并进入 EXECUTING。"""
        task = self.runtime.task_repository.get(task_id)
        if task is None:
            raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "任务不存在")
        if task.status != TaskStatus.APPROVED:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "任务当前不在 APPROVED 状态",
                correlation_id=task.correlation_id,
            )
        plan = self.runtime.plan_repository.get(task.current_plan_id)
        if plan is None:
            raise AgentError(
                AgentErrorCode.PLAN_NOT_FOUND, "计划不存在",
                correlation_id=task.correlation_id,
            )
        snapshot = self.runtime.context_service.build_snapshot(
            context_snapshot_id=f"CTX-{uuid4().hex[:12].upper()}",
            task_id=task.task_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            domain=Domain.SCIENTIFIC,
            user_id=task.submitted_by,
            agent_id=task.assigned_agent,
            project_scope=task.scope,
            permission_scope={"role": user_role, "actions": ["read"]},
            schema_version=self.runtime.schema_version,
            tool_registry_version=self.runtime.tool_registry.version,
            context_policy_version="0.1",
            source_items=[],
            allowed_object_types=[
                "ExperimentBatch",
                "LysisAssay",
                "BiofilmAssay",
                "EnzymeGene",
                "SourceArtifact",
                "Review",
            ],
            excluded_object_types=["Patient", "ClinicalCase"],
        )
        saved = self.runtime.context_repository.create(snapshot)
        task.context_snapshot_id = saved.context_snapshot_id
        self.runtime.task_repository.save(task)
        self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.APPROVED,
            target_status=TaskStatus.EXECUTING,
            actor_id=actor_id,
            reason="计划批准后启动 SCI-S1 任务",
        )
        return self.runtime.task_repository.get(task.task_id)