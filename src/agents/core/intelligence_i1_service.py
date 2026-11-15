# src/agents/core/intelligence_i1_service.py
"""INT-I1 周期情报简报固定模板。不调用 LLM。"""
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


class IntelligenceI1Service:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def create_task(
        self,
        *,
        pathogen_id: str,
        date_from: str,
        date_to: str,
        submitted_by: str,
        user_role: str,
    ):
        if not pathogen_id or not pathogen_id.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "pathogen_id 不能为空"
            )
        if not date_from or not date_to:
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "日期范围不能为空"
            )

        task = self.runtime.task_service.create_task(
            task_type="INT-I1-PERIODIC-BRIEF-DRAFT",
            domain=Domain.INTELLIGENCE,
            title=f"周期情报简报：{pathogen_id}",
            user_request=(
                f"汇总 {date_from} 至 {date_to} 与 {pathogen_id} 相关的"
                "研发项目和情报事件，生成简报草稿"
            ),
            submitted_by=submitted_by,
            assigned_agent="intelligence-agent",
            risk_level=RiskLevel.R1,
            scope={
                "pathogen_id": pathogen_id,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        task = self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.DRAFT,
            target_status=TaskStatus.UNDERSTANDING,
            actor_id=submitted_by,
            reason="开始解析 INT-I1 固定模板任务",
        )
        task = self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.UNDERSTANDING,
            target_status=TaskStatus.PLANNING,
            actor_id="intelligence-agent",
            reason="INT-I1 模板匹配成功",
        )

        plan_id = f"PLAN-{uuid4().hex[:12].upper()}"
        step = AgentStep(
            step_id=f"STEP-{uuid4().hex[:12].upper()}",
            plan_id=plan_id,
            sequence=1,
            step_type=StepType.SYNTHESIZE_RESULT,
            name="生成周期情报简报草稿",
            description=(
                "只读检索病原体相关项目、事件与来源；按审核状态分层；"
                "确定性生成草稿"
            ),
            tool_id="intelligence.periodic_brief",
            tool_version=self.runtime.i1_brief_tool.version,
            input_references=["pathogen_id", "date_from", "date_to"],
            expected_output_type="intelligence_brief_draft",
            risk_level=RiskLevel.R1,
            approval_required=False,
            can_retry=True,
        )
        plan = AgentPlan(
            plan_id=plan_id,
            task_id=task.task_id,
            version=1,
            goal_summary=(
                "生成可追溯、分层展示审核状态的情报简报草稿，"
                "不发布正式情报产品"
            ),
            assumptions=[],
            open_questions=[],
            required_inputs=["pathogen_id", "date_from", "date_to"],
            expected_artifacts=["intelligence_brief_draft"],
            steps=[step],
            approval_required=True,
            generated_by="INT-I1-TEMPLATE",
            status=PlanStatus.VALIDATED,
        )
        self.runtime.task_service.attach_plan(
            task.task_id, plan=plan, actor_id="intelligence-agent"
        )
        self.runtime.task_service.submit_plan_for_review(
            task.task_id, actor_id="intelligence-agent"
        )
        return task, plan

    def activate_approved_task(
        self,
        *,
        task_id: str,
        actor_id: str,
        user_role: str,
    ):
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
            domain=Domain.INTELLIGENCE,
            user_id=task.submitted_by,
            agent_id=task.assigned_agent,
            project_scope=task.scope,
            permission_scope={"role": user_role, "actions": ["read"]},
            schema_version=self.runtime.schema_version,
            tool_registry_version=self.runtime.tool_registry.version,
            context_policy_version="0.1",
            source_items=[],
            allowed_object_types=[
                "Pathogen",
                "DevelopmentProgram",
                "IntelligenceEvent",
                "Organization",
                "SourceArtifact",
            ],
            excluded_object_types=[
                "Patient",
                "ClinicalCase",
                "HostStrain",
                "LysisAssay",
                "BiofilmAssay",
            ],
        )
        saved = self.runtime.context_repository.create(snapshot)
        task.context_snapshot_id = saved.context_snapshot_id
        self.runtime.task_repository.save(task)
        self.runtime.task_service.transition_task(
            task.task_id,
            expected_status=TaskStatus.APPROVED,
            target_status=TaskStatus.EXECUTING,
            actor_id=actor_id,
            reason="计划批准后启动 INT-I1 任务",
        )
        return self.runtime.task_repository.get(task.task_id)