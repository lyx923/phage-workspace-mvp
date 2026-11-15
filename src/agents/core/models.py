# src/agents/core/models.py
"""Agent 核心数据结构。

说明：
1. 这些结构不承担数据库持久化；
2. 正式存储由 Repository 实现；
3. 时间统一使用带 UTC 时区的 ISO 8601 字符串；
4. 不在对象中保存密钥、数据库口令或完整敏感输入。
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Domain(str, Enum):
    SCIENTIFIC = "scientific"
    INTELLIGENCE = "intelligence"


class RiskLevel(str, Enum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class TaskStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDERSTANDING = "UNDERSTANDING"
    WAITING_INPUT = "WAITING_INPUT"
    PLANNING = "PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    RESULT_REVIEW = "RESULT_REVIEW"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    PLAN_REVIEW = "PLAN_REVIEW"
    APPROVED = "APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class StepType(str, Enum):
    CLARIFY_INPUT = "CLARIFY_INPUT"
    READ_DATA = "READ_DATA"
    VALIDATE_DATA = "VALIDATE_DATA"
    COMPARE_DATA = "COMPARE_DATA"
    BUILD_ARTIFACT = "BUILD_ARTIFACT"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    SYNTHESIZE_RESULT = "SYNTHESIZE_RESULT"
    SUBMIT_FOR_REVIEW = "SUBMIT_FOR_REVIEW"


class ContextStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class TrustLevel(str, Enum):
    SYSTEM_POLICY = "SYSTEM_POLICY"
    APPROVED_DEFINITION = "APPROVED_DEFINITION"
    VERIFIED_FACT = "VERIFIED_FACT"
    REVIEWED_SOURCE = "REVIEWED_SOURCE"
    UNREVIEWED_SOURCE = "UNREVIEWED_SOURCE"
    CANDIDATE_MAPPING = "CANDIDATE_MAPPING"
    MODEL_GENERATED = "MODEL_GENERATED"
    USER_PROVIDED = "USER_PROVIDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


# ── 第 3 批：Artifact 与 Findings ─────────────────────────────

class ArtifactType(str, Enum):
    QUERY_RESULT = "query_result"
    MISSING_DATA_REPORT = "missing_data_report"
    VALIDATION_FINDINGS = "validation_findings"
    COMPARISON_TABLE = "comparison_table"
    DRAFT_CLAIM = "draft_claim"
    DRAFT_EVIDENCE_PACKAGE = "draft_evidence_package"
    INTELLIGENCE_BRIEF_DRAFT = "intelligence_brief_draft"
    CONFLICT_REPORT = "conflict_report"
    FINAL_REPORT = "final_report"


class ArtifactStatus(str, Enum):
    DRAFT = "DRAFT"
    RESULT_REVIEW = "RESULT_REVIEW"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class FindingSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    BLOCKING = "BLOCKING"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ACCEPTED_RISK = "ACCEPTED_RISK"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class ServiceResult:
    ok: bool
    code: str
    message: str
    data: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourceReference:
    source_id: str
    source_type: str
    source_version: Optional[str] = None
    object_id: Optional[str] = None
    locator: Optional[str] = None
    trust_status: str = "UNREVIEWED_SOURCE"
    review_status: Optional[str] = None
    retrieved_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationFinding:
    finding_id: str
    rule_id: str
    object_type: str
    object_id: str
    field_or_relation: str
    severity: FindingSeverity
    message: str
    observed_value: Any = None
    expected_condition: Optional[str] = None
    source_references: List[SourceReference] = field(default_factory=list)
    validation_run_id: Optional[str] = None
    status: FindingStatus = FindingStatus.OPEN
    resolution_reference: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    record_version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["severity"] = self.severity.value
        result["status"] = self.status.value
        result["source_references"] = [
            item.to_dict() for item in self.source_references
        ]
        return result


@dataclass
class AgentArtifact:
    artifact_id: str
    artifact_family_id: str
    task_id: str
    step_id: str
    artifact_type: ArtifactType
    version: int
    content: Dict[str, Any]
    checksum: str
    created_by: str
    schema_version: str
    context_snapshot_id: str
    source_references: List[SourceReference] = field(default_factory=list)
    status: ArtifactStatus = ArtifactStatus.DRAFT
    supersedes_artifact_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[str] = None
    record_version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["artifact_type"] = self.artifact_type.value
        result["status"] = self.status.value
        result["source_references"] = [
            item.to_dict() for item in self.source_references
        ]
        return result


# ── 任务 / 计划 / 步骤 ─────────────────────────────────────────

@dataclass
class AgentStep:
    step_id: str
    plan_id: str
    sequence: int
    step_type: StepType
    name: str
    description: str
    tool_id: Optional[str]
    input_references: List[str]
    expected_output_type: str
    risk_level: RiskLevel
    approval_required: bool
    can_retry: bool = False
    can_skip: bool = False
    status: StepStatus = StepStatus.PENDING
    retry_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_code: Optional[str] = None
    error_summary: Optional[str] = None
    # 第 3 批新增字段（带默认值，向后兼容）
    tool_version: Optional[str] = None
    record_version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["step_type"] = self.step_type.value
        result["risk_level"] = self.risk_level.value
        result["status"] = self.status.value
        return result


@dataclass
class AgentPlan:
    plan_id: str
    task_id: str
    version: int
    goal_summary: str
    assumptions: List[str]
    open_questions: List[str]
    required_inputs: List[str]
    expected_artifacts: List[str]
    steps: List[AgentStep]
    approval_required: bool = True
    generated_by: str = "system"
    generated_at: str = field(default_factory=utc_now_iso)
    supersedes_plan_id: Optional[str] = None
    context_snapshot_id: Optional[str] = None
    status: PlanStatus = PlanStatus.DRAFT

    def to_dict(self) -> dict:
        result = asdict(self)
        result["status"] = self.status.value
        result["steps"] = [step.to_dict() for step in self.steps]
        return result


@dataclass
class AgentTask:
    task_id: str
    task_type: str
    domain: Domain
    title: str
    user_request: str
    submitted_by: str
    assigned_agent: str
    risk_level: RiskLevel
    correlation_id: str
    normalized_goal: Optional[str] = None
    scope: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.DRAFT
    current_plan_version: Optional[int] = None
    current_plan_id: Optional[str] = None
    context_snapshot_id: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result_status: Optional[str] = None
    cancellation_reason: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["domain"] = self.domain.value
        result["risk_level"] = self.risk_level.value
        result["status"] = self.status.value
        return result


@dataclass(frozen=True)
class ContextItem:
    item_id: str
    item_type: str
    trust_level: TrustLevel
    source_id: Optional[str]
    source_version: Optional[str]
    payload_reference: str

    def to_dict(self) -> dict:
        result = asdict(self)
        result["trust_level"] = self.trust_level.value
        return result


@dataclass
class ContextSnapshot:
    context_snapshot_id: str
    task_id: str
    plan_id: str
    plan_version: int
    domain: Domain
    user_id: str
    agent_id: str
    project_scope: Dict[str, Any]
    permission_scope: Dict[str, Any]
    schema_version: str
    tool_registry_version: str
    context_policy_version: str
    source_items: List[ContextItem]
    allowed_object_types: List[str]
    excluded_object_types: List[str]
    model_version: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: Optional[str] = None
    context_hash: Optional[str] = None
    status: ContextStatus = ContextStatus.DRAFT
    invalidation_reason: Optional[str] = None
    record_version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["domain"] = self.domain.value
        result["status"] = self.status.value
        result["source_items"] = [item.to_dict() for item in self.source_items]
        return result


# ── 审批 ──────────────────────────────────────────────────────

class ApprovalType(str, Enum):
    PLAN = "PLAN"
    STEP = "STEP"
    MODEL_ELIGIBILITY = "MODEL_ELIGIBILITY"
    RESULT = "RESULT"
    CANDIDATE_WRITE = "CANDIDATE_WRITE"


class ApprovalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    NEEDS_REVISION = "NEEDS_REVISION"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ApprovalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    USED = "USED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


@dataclass
class AgentApproval:
    approval_id: str
    task_id: str
    approval_type: ApprovalType
    requested_by: str
    requested_from_role: str
    requested_from_user: Optional[str] = None
    plan_id: Optional[str] = None
    plan_version: Optional[int] = None
    step_id: Optional[str] = None
    artifact_id: Optional[str] = None
    artifact_version: Optional[int] = None
    context_snapshot_id: Optional[str] = None
    decision: ApprovalDecision = ApprovalDecision.PENDING
    status: ApprovalStatus = ApprovalStatus.ACTIVE
    comment: Optional[str] = None
    approved_scope: List[str] = field(default_factory=list)
    rejected_scope: List[str] = field(default_factory=list)
    decided_by: Optional[str] = None
    requested_at: str = field(default_factory=utc_now_iso)
    decided_at: Optional[str] = None
    expires_at: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["approval_type"] = self.approval_type.value
        result["decision"] = self.decision.value
        result["status"] = self.status.value
        return result


@dataclass
class PermissionRequest:
    user_id: str
    user_role: str
    agent_id: str
    agent_roles: List[str]
    resource: str
    action: str
    domain: Domain
    task_id: Optional[str] = None
    project_scope: Dict[str, Any] = field(default_factory=dict)
    data_classification: Optional[str] = None
    approval_id: Optional[str] = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result["domain"] = self.domain.value
        return result


@dataclass
class PermissionDecision:
    allowed: bool
    code: str
    reason: str
    user_allowed: bool
    agent_allowed: bool
    resource_allowed: bool
    domain_allowed: bool
    approval_valid: bool
    policy_version: str
    evaluated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict:
        return asdict(self)


# ── 第 4 批：人工干预 ─────────────────────────────────────────

class InterventionType(str, Enum):
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    CANCEL = "CANCEL"
    REQUEST_REPLAN = "REQUEST_REPLAN"
    EDIT_SCOPE = "EDIT_SCOPE"
    PROVIDE_INPUT = "PROVIDE_INPUT"
    RETRY_STEP = "RETRY_STEP"
    TAKE_OVER = "TAKE_OVER"


@dataclass
class AgentIntervention:
    intervention_id: str
    task_id: str
    intervention_type: InterventionType
    requested_by: str
    instruction: str
    affected_step_id: Optional[str]
    before_state: str
    after_state: str
    created_at: str = field(default_factory=utc_now_iso)
    correlation_id: Optional[str] = None
    version: int = 1

    def to_dict(self) -> dict:
        result = asdict(self)
        result["intervention_type"] = self.intervention_type.value
        return result