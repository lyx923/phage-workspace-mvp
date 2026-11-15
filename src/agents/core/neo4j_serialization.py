# src/agents/core/neo4j_serialization.py
"""Agent 对象与 Neo4j 属性之间的序列化。"""
import json
from typing import Any, List, Optional

from .models import (
    AgentApproval,
    AgentArtifact,
    AgentIntervention,
    AgentPlan,
    AgentStep,
    AgentTask,
    ApprovalDecision,
    ApprovalStatus,
    ApprovalType,
    ArtifactStatus,
    ArtifactType,
    ContextItem,
    ContextSnapshot,
    ContextStatus,
    Domain,
    InterventionType,
    PlanStatus,
    RiskLevel,
    SourceReference,
    StepStatus,
    StepType,
    TaskStatus,
    TrustLevel,
)


def dumps(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def loads(value: Optional[str], default: Any) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


# ── 单对象转换 ───────────────────────────────────────────────

def task_from_props(props: dict) -> AgentTask:
    return AgentTask(
        task_id=props["task_id"],
        task_type=props["task_type"],
        domain=Domain(props["domain"]),
        title=props["title"],
        user_request=props["user_request"],
        submitted_by=props["submitted_by"],
        assigned_agent=props["assigned_agent"],
        risk_level=RiskLevel(props["risk_level"]),
        correlation_id=props["correlation_id"],
        normalized_goal=props.get("normalized_goal"),
        scope=loads(props.get("scope_json"), {}),
        status=TaskStatus(props["status"]),
        current_plan_version=props.get("current_plan_version"),
        current_plan_id=props.get("current_plan_id"),
        context_snapshot_id=props.get("context_snapshot_id"),
        created_at=str(props["created_at"]),
        started_at=str(props["started_at"]) if props.get("started_at") else None,
        completed_at=(
            str(props["completed_at"]) if props.get("completed_at") else None
        ),
        result_status=props.get("result_status"),
        cancellation_reason=props.get("cancellation_reason"),
        version=int(props.get("version", 1)),
    )


def step_from_props(props: dict) -> AgentStep:
    return AgentStep(
        step_id=props["step_id"],
        plan_id=props["plan_id"],
        sequence=int(props["sequence"]),
        step_type=StepType(props["step_type"]),
        name=props["name"],
        description=props["description"],
        tool_id=props.get("tool_id"),
        tool_version=props.get("tool_version"),
        input_references=loads(props.get("input_references_json"), []),
        expected_output_type=props["expected_output_type"],
        risk_level=RiskLevel(props["risk_level"]),
        approval_required=bool(props.get("approval_required", False)),
        can_retry=bool(props.get("can_retry", False)),
        can_skip=bool(props.get("can_skip", False)),
        status=StepStatus(props["status"]),
        retry_count=int(props.get("retry_count", 0)),
        started_at=str(props["started_at"]) if props.get("started_at") else None,
        completed_at=(
            str(props["completed_at"]) if props.get("completed_at") else None
        ),
        error_code=props.get("error_code"),
        error_summary=props.get("error_summary"),
        record_version=int(props.get("record_version", 1)),
    )


def plan_from_props(props: dict, steps: List[AgentStep]) -> AgentPlan:
    return AgentPlan(
        plan_id=props["plan_id"],
        task_id=props["task_id"],
        version=int(props["version"]),
        goal_summary=props["goal_summary"],
        assumptions=loads(props.get("assumptions_json"), []),
        open_questions=loads(props.get("open_questions_json"), []),
        required_inputs=loads(props.get("required_inputs_json"), []),
        expected_artifacts=loads(props.get("expected_artifacts_json"), []),
        steps=steps,
        approval_required=bool(props.get("approval_required", True)),
        generated_by=props["generated_by"],
        generated_at=str(props["generated_at"]),
        supersedes_plan_id=props.get("supersedes_plan_id"),
        context_snapshot_id=props.get("context_snapshot_id"),
        status=PlanStatus(props["status"]),
    )


def source_reference_from_dict(value: dict) -> SourceReference:
    return SourceReference(
        source_id=value["source_id"],
        source_type=value["source_type"],
        source_version=value.get("source_version"),
        object_id=value.get("object_id"),
        locator=value.get("locator"),
        trust_status=value.get("trust_status", "UNREVIEWED_SOURCE"),
        review_status=value.get("review_status"),
        retrieved_at=value.get("retrieved_at", ""),
    )


def artifact_from_props(props: dict) -> AgentArtifact:
    refs = [
        source_reference_from_dict(item)
        for item in loads(props.get("source_references_json"), [])
    ]
    return AgentArtifact(
        artifact_id=props["artifact_id"],
        artifact_family_id=props["artifact_family_id"],
        task_id=props["task_id"],
        step_id=props["step_id"],
        artifact_type=ArtifactType(props["artifact_type"]),
        version=int(props["artifact_version"]),
        content=loads(props.get("content_json"), {}),
        checksum=props["checksum"],
        created_by=props["created_by"],
        schema_version=props["schema_version"],
        context_snapshot_id=props["context_snapshot_id"],
        source_references=refs,
        status=ArtifactStatus(props["status"]),
        supersedes_artifact_id=props.get("supersedes_artifact_id"),
        created_at=str(props["created_at"]),
        reviewed_at=(
            str(props["reviewed_at"]) if props.get("reviewed_at") else None
        ),
        reviewed_by=props.get("reviewed_by"),
        record_version=int(props.get("record_version", 1)),
    )


def approval_from_props(props: dict) -> AgentApproval:
    return AgentApproval(
        approval_id=props["approval_id"],
        task_id=props["task_id"],
        approval_type=ApprovalType(props["approval_type"]),
        requested_by=props["requested_by"],
        requested_from_role=props["requested_from_role"],
        requested_from_user=props.get("requested_from_user"),
        plan_id=props.get("plan_id"),
        plan_version=props.get("plan_version"),
        step_id=props.get("step_id"),
        artifact_id=props.get("artifact_id"),
        artifact_version=props.get("artifact_version"),
        context_snapshot_id=props.get("context_snapshot_id"),
        decision=ApprovalDecision(props["decision"]),
        status=ApprovalStatus(props["status"]),
        comment=props.get("comment"),
        approved_scope=loads(props.get("approved_scope_json"), []),
        rejected_scope=loads(props.get("rejected_scope_json"), []),
        decided_by=props.get("decided_by"),
        requested_at=str(props["requested_at"]),
        decided_at=(
            str(props["decided_at"]) if props.get("decided_at") else None
        ),
        expires_at=(
            str(props["expires_at"]) if props.get("expires_at") else None
        ),
        version=int(props.get("version", 1)),
    )


def context_item_from_dict(value: dict) -> ContextItem:
    return ContextItem(
        item_id=value["item_id"],
        item_type=value["item_type"],
        trust_level=TrustLevel(value["trust_level"]),
        source_id=value.get("source_id"),
        source_version=value.get("source_version"),
        payload_reference=value["payload_reference"],
    )


def context_snapshot_from_props(props: dict) -> ContextSnapshot:
    return ContextSnapshot(
        context_snapshot_id=props["context_snapshot_id"],
        task_id=props["task_id"],
        plan_id=props["plan_id"],
        plan_version=int(props["plan_version"]),
        domain=Domain(props["domain"]),
        user_id=props["user_id"],
        agent_id=props["agent_id"],
        project_scope=loads(props.get("project_scope_json"), {}),
        permission_scope=loads(props.get("permission_scope_json"), {}),
        schema_version=props["schema_version"],
        model_version=props.get("model_version"),
        tool_registry_version=props["tool_registry_version"],
        context_policy_version=props["context_policy_version"],
        source_items=[
            context_item_from_dict(item)
            for item in loads(props.get("source_items_json"), [])
        ],
        allowed_object_types=loads(props.get("allowed_object_types_json"), []),
        excluded_object_types=loads(props.get("excluded_object_types_json"), []),
        created_at=str(props["created_at"]),
        expires_at=(
            str(props["expires_at"]) if props.get("expires_at") else None
        ),
        context_hash=props.get("context_hash"),
        status=ContextStatus(props["status"]),
        invalidation_reason=props.get("invalidation_reason"),
        record_version=int(props.get("record_version", 1)),
    )


def intervention_from_props(props: dict) -> AgentIntervention:
    return AgentIntervention(
        intervention_id=props["intervention_id"],
        task_id=props["task_id"],
        intervention_type=InterventionType(props["intervention_type"]),
        requested_by=props["requested_by"],
        instruction=props["instruction"],
        affected_step_id=props.get("affected_step_id"),
        before_state=props["before_state"],
        after_state=props["after_state"],
        created_at=str(props["created_at"]),
        correlation_id=props.get("correlation_id"),
        version=int(props.get("version", 1)),
    )