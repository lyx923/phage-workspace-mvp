# src/agents/core/__init__.py
"""受控 Agent 任务执行模块基础层。"""

from .errors import AgentError, AgentErrorCode

from .models import (
    Domain, RiskLevel,
    AgentTask, TaskStatus,
    AgentPlan, PlanStatus,
    AgentStep, StepStatus, StepType,
    ContextItem, ContextSnapshot, ContextStatus, TrustLevel,
    ServiceResult, utc_now_iso,
    AgentApproval, ApprovalType, ApprovalDecision, ApprovalStatus,
    PermissionRequest, PermissionDecision,
    AgentArtifact, ArtifactType, ArtifactStatus,
    FindingSeverity, FindingStatus,
    SourceReference, ValidationFinding,
    AgentIntervention, InterventionType,
)

from .state_machine import AgentTaskStateMachine
from .registry import ToolDefinition, ToolRegistry
from .context_service import ContextService, calculate_context_hash
from .repositories import (
    AgentTaskRepository, AgentPlanRepository,
    AgentStepRepository, AgentArtifactRepository,
    AgentApprovalRepository, AgentInterventionRepository,
    ContextSnapshotRepository,
    InMemoryAgentTaskRepository, InMemoryAgentPlanRepository,
    InMemoryAgentStepRepository, InMemoryAgentArtifactRepository,
    InMemoryAgentApprovalRepository, InMemoryAgentInterventionRepository,
    InMemoryContextSnapshotRepository,
)
from .neo4j_repositories import (
    Neo4jAgentTaskRepository, Neo4jAgentPlanRepository,
    Neo4jAgentStepRepository, Neo4jAgentArtifactRepository,
    Neo4jAgentApprovalRepository, Neo4jAgentInterventionRepository,
    Neo4jContextSnapshotRepository,
)
from .neo4j_command_service import Neo4jAgentCommandService
from .permission_service import (
    PermissionService, PermissionPolicy, AgentPermissionProfile,
    DEFAULT_ROLE_PERMISSIONS, DEFAULT_AGENT_PROFILES, build_default_policy,
)
from .approval_service import ApprovalService, _is_expired
from .approval_expiry_service import ApprovalExpiryService
from .audit_adapter import AgentAuditRecord, InMemoryAuditWriter, Neo4jAuditWriter
from .task_service import AgentTaskService
from .artifact_service import (
    AgentArtifactService, calculate_artifact_checksum, stable_content_json,
)
from .execution_service import AgentExecutionService
from .result_review_service import AgentResultReviewService
from .intervention_service import AgentInterventionService
from .replan_service import AgentReplanService
from .retry_policy import RetryPolicy, RetryDecision
from .step_retry_service import AgentStepRetryService
from .artifact_revision_service import ArtifactRevisionService
from .timeline_service import AgentTimelineService
from .scientific_s1_service import ScientificS1Service
from .intelligence_i1_service import IntelligenceI1Service
from .intent_router import IntentRouter, IntentType, IntentResult
from .runtime import AgentRuntime, get_agent_runtime


__all__ = [
    "AgentError", "AgentErrorCode",
    "Domain", "RiskLevel",
    "AgentTask", "TaskStatus",
    "AgentPlan", "PlanStatus",
    "AgentStep", "StepStatus", "StepType",
    "ContextItem", "ContextSnapshot", "ContextStatus", "TrustLevel",
    "ContextService", "calculate_context_hash",
    "ServiceResult", "utc_now_iso",
    "AgentTaskStateMachine",
    "ToolDefinition", "ToolRegistry",
    "AgentArtifact", "ArtifactType", "ArtifactStatus",
    "FindingSeverity", "FindingStatus",
    "SourceReference", "ValidationFinding",
    "AgentArtifactService",
    "calculate_artifact_checksum", "stable_content_json",
    "AgentIntervention", "InterventionType",
    "AgentTaskRepository", "AgentPlanRepository",
    "AgentStepRepository", "AgentArtifactRepository",
    "AgentApprovalRepository", "AgentInterventionRepository",
    "ContextSnapshotRepository",
    "InMemoryAgentTaskRepository", "InMemoryAgentPlanRepository",
    "InMemoryAgentStepRepository", "InMemoryAgentArtifactRepository",
    "InMemoryAgentApprovalRepository", "InMemoryAgentInterventionRepository",
    "InMemoryContextSnapshotRepository",
    "Neo4jAgentTaskRepository", "Neo4jAgentPlanRepository",
    "Neo4jAgentStepRepository", "Neo4jAgentArtifactRepository",
    "Neo4jAgentApprovalRepository", "Neo4jAgentInterventionRepository",
    "Neo4jContextSnapshotRepository",
    "Neo4jAgentCommandService",
    "PermissionService", "PermissionPolicy", "AgentPermissionProfile",
    "PermissionRequest", "PermissionDecision",
    "DEFAULT_ROLE_PERMISSIONS", "DEFAULT_AGENT_PROFILES",
    "build_default_policy",
    "AgentApproval", "ApprovalType", "ApprovalDecision", "ApprovalStatus",
    "ApprovalService", "_is_expired", "ApprovalExpiryService",
    "AgentAuditRecord", "InMemoryAuditWriter", "Neo4jAuditWriter",
    "AgentTaskService",
    "AgentExecutionService",
    "AgentResultReviewService",
    "AgentInterventionService",
    "AgentReplanService",
    "RetryPolicy", "RetryDecision", "AgentStepRetryService",
    "ArtifactRevisionService",
    "AgentTimelineService",
    "ScientificS1Service",
    "IntelligenceI1Service",
    "IntentRouter", "IntentType", "IntentResult",
    "AgentRuntime", "get_agent_runtime",
]