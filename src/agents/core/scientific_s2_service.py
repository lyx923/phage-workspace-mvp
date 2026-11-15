# src/agents/core/scientific_s2_service.py
"""SCI-S2 证据包草稿固定模板。不调用 LLM。"""
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentPlan, AgentStep, Domain, PlanStatus, RiskLevel, StepType, TaskStatus,
)


class ScientificS2Service:
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def create_task(
        self,
        *,
        phage_id: str,
        host_strain_id: str,
        submitted_by: str,
        user_role: str,
    ):
        if not phage_id.strip() or not host_strain_id.strip():
            raise AgentError(AgentErrorCode.TOOL_INPUT_INVALID, "噬菌体和宿主菌株 ID 不能为空")

        task = self.runtime.task_service.create_task(
            task_type="SCI-S2-EVIDENCE-PACKAGE-DRAFT",
            domain=Domain.SCIENTIFIC,
            title=f"证据包草稿：{phage_id} × {host_strain_id}",
            user_request=f"基于 {phage_id} 和 {host_strain_id} 生成证据包草稿",
            submitted_by=submitted_by,
            assigned_agent="scientific-agent",
            risk_level=RiskLevel.R1,  # R1 分析任务
            scope={"phage_id": phage_id, "host_strain_id": host_strain_id},
        )
        task = self.runtime.task_service.transition_task(
            task.task_id, expected_status=TaskStatus.DRAFT,
            target_status=TaskStatus.UNDERSTANDING, actor_id=submitted_by, reason="开始解析 SCI-S2",
        )
        task = self.runtime.task_service.transition_task(
            task.task_id, expected_status=TaskStatus.UNDERSTANDING,
            target_status=TaskStatus.PLANNING, actor_id="scientific-agent", reason="SCI-S2 模板匹配成功",
        )

        plan_id = f"PLAN-{uuid4().hex[:12].upper()}"
        step = AgentStep(
            step_id=f"STEP-{uuid4().hex[:12].upper()}",
            plan_id=plan_id,
            sequence=1,
            step_type=StepType.BUILD_ARTIFACT,
            name="生成证据包草稿",
            description="检索相关实验记录、来源和审核状态，组装证据包草稿",
            tool_id="scientific.draft_evidence_package",
            tool_version=self.runtime.s2_draft_tool.version,
            input_references=["phage_id", "host_strain_id"],
            expected_output_type="draft_evidence_package",
            risk_level=RiskLevel.R1,
            approval_required=False,
            can_retry=True,
        )
        plan = AgentPlan(
            plan_id=plan_id,
            task_id=task.task_id,
            version=1,
            goal_summary="生成可追溯的证据包草稿，不生成临床结论",
            assumptions=[],
            open_questions=[],
            required_inputs=["phage_id", "host_strain_id"],
            expected_artifacts=["draft_evidence_package"],
            steps=[step],
            approval_required=True,
            generated_by="SCI-S2-TEMPLATE",
            status=PlanStatus.VALIDATED,
        )
        self.runtime.task_service.attach_plan(task.task_id, plan=plan, actor_id="scientific-agent")
        self.runtime.task_service.submit_plan_for_review(task.task_id, actor_id="scientific-agent")
        return task, plan

    def activate_approved_task(self, *, task_id: str, actor_id: str, user_role: str):
        task = self.runtime.task_repository.get(task_id)
        if task is None or task.status != TaskStatus.APPROVED:
            raise AgentError(AgentErrorCode.INVALID_STATE_TRANSITION, "任务不在 APPROVED 状态")
        
        plan = self.runtime.plan_repository.get(task.current_plan_id)
        snapshot = self.runtime.context_service.build_snapshot(
            context_snapshot_id=f"CTX-{uuid4().hex[:12].upper()}",
            task_id=task.task_id,
            plan_id=plan.plan_id,
            plan_version=plan.version,
            domain=Domain.SCIENTIFIC,
            user_id=task.submitted_by,
            agent_id=task.assigned_agent,
            project_scope=task.scope,
            permission_scope={"role": user_role, "actions": ["read", "create"]},
            schema_version=self.runtime.schema_version,
            tool_registry_version=self.runtime.tool_registry.version,
            context_policy_version="0.1",
            source_items=[],
            allowed_object_types=["Phage", "HostStrain", "LysisAssay", "SourceArtifact"],
            excluded_object_types=["Patient", "ClinicalCase"],
        )
        saved = self.runtime.context_repository.create(snapshot)
        task.context_snapshot_id = saved.context_snapshot_id
        self.runtime.task_repository.save(task)
        self.runtime.task_service.transition_task(
            task.task_id, expected_status=TaskStatus.APPROVED,
            target_status=TaskStatus.EXECUTING, actor_id=actor_id, reason="计划批准后启动 SCI-S2",
        )
        return self.runtime.task_repository.get(task.task_id)