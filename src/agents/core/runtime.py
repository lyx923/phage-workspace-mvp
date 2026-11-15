# src/agents/core/runtime.py
"""Agent 运行时服务装配。"""
from typing import Optional

from config import Config, get_driver
from src.shared.audit_service import write_audit_event

from .approval_expiry_service import ApprovalExpiryService
from .approval_service import ApprovalService
from .artifact_revision_service import ArtifactRevisionService
from .artifact_service import AgentArtifactService
from .audit_adapter import Neo4jAuditWriter
from .context_service import ContextService
from .execution_service import AgentExecutionService
from .intelligence_i1_service import IntelligenceI1Service
from .intervention_service import AgentInterventionService
from .models import Domain, RiskLevel
from .neo4j_command_service import Neo4jAgentCommandService
from .neo4j_repositories import (
    Neo4jAgentApprovalRepository, Neo4jAgentArtifactRepository,
    Neo4jAgentInterventionRepository, Neo4jAgentPlanRepository,
    Neo4jAgentStepRepository, Neo4jAgentTaskRepository,
    Neo4jContextSnapshotRepository,
)
from .permission_service import PermissionService
from .registry import ToolDefinition, ToolRegistry
from .replan_service import AgentReplanService
from .result_review_service import AgentResultReviewService
from .retry_policy import RetryPolicy
from .scientific_s1_service import ScientificS1Service
from .scientific_s2_service import ScientificS2Service
from .step_retry_service import AgentStepRetryService
from .task_service import AgentTaskService
from .timeline_service import AgentTimelineService
from src.agents.tools.intelligence_read_tools import PeriodicIntelligenceBriefTool
from src.agents.tools.scientific_read_tools import BatchCompletenessTool
from src.agents.tools.scientific_draft_tools import EvidencePackageDraftTool


def _query_runner(cypher: str, **params):
    database = getattr(Config, "NEO4J_DATABASE", None)
    with get_driver().session(database=database) as session:
        return [dict(record) for record in session.run(cypher, **params)]

def _enabled() -> bool:
    return bool(getattr(Config, "AGENT_VALIDATION_ENABLED", False))

def _schema_version() -> str:
    return str(getattr(Config, "CURRENT_SCHEMA_VERSION", "0.8.0"))

class AgentRuntime:
    def __init__(self) -> None:
        if not _enabled():
            raise RuntimeError("Agent 验证功能未启用：请设置 AGENT_VALIDATION_ENABLED=true")

        driver = get_driver()
        self.driver = driver
        database = getattr(Config, "NEO4J_DATABASE", None)

        self.audit_writer = Neo4jAuditWriter(driver=driver, write_function=write_audit_event)
        self.command_service = Neo4jAgentCommandService(driver, database=database)

        # 仓储
        self.task_repository = Neo4jAgentTaskRepository(driver)
        self.plan_repository = Neo4jAgentPlanRepository(driver)
        self.step_repository = Neo4jAgentStepRepository(driver)
        self.artifact_repository = Neo4jAgentArtifactRepository(driver)
        self.approval_repository = Neo4jAgentApprovalRepository(driver)
        self.intervention_repository = Neo4jAgentInterventionRepository(driver)
        self.context_repository = Neo4jContextSnapshotRepository(driver)

        # 基础服务
        self.permission_service = PermissionService()
        self.context_service = ContextService()
        self.approval_service = ApprovalService(self.approval_repository, audit_writer=self.audit_writer)
        self.approval_expiry_service = ApprovalExpiryService(repository=self.approval_repository, audit_writer=self.audit_writer)
        self.task_service = AgentTaskService(
            task_repository=self.task_repository, plan_repository=self.plan_repository,
            audit_writer=self.audit_writer, command_service=self.command_service,
        )
        self.artifact_service = AgentArtifactService(repository=self.artifact_repository, audit_writer=self.audit_writer)

        # 工具
        self.batch_tool = BatchCompletenessTool(query_runner=_query_runner)
        self.i1_brief_tool = PeriodicIntelligenceBriefTool(query_runner=_query_runner)
        self.s2_draft_tool = EvidencePackageDraftTool(query_runner=_query_runner) # ★ 新增 S2 工具

        scientific_definition = ToolDefinition(
            tool_id=self.batch_tool.tool_id, name="实验批次完整性检查", domain=Domain.SCIENTIFIC,
            version=self.batch_tool.version, description="只读完整性检查", access_mode="read",
            allowed_object_types=frozenset({"ExperimentBatch", "LysisAssay", "BiofilmAssay", "EnzymeGene", "SourceArtifact", "Review"}),
            allowed_roles=frozenset({"researcher", "data_manager", "admin"}), risk_level=RiskLevel.R0,
            approval_required=False, max_results=500, timeout_seconds=30, audit_required=True, enabled=True,
            implementation_ref="src.agents.tools.scientific_read_tools:BatchCompletenessTool",
            permission_resource="ExperimentBatch", permission_action="read",
        )
        intelligence_definition = ToolDefinition(
            tool_id=self.i1_brief_tool.tool_id, name="周期情报简报草稿", domain=Domain.INTELLIGENCE,
            version=self.i1_brief_tool.version, description="按病原体和时间范围读取研发项目、情报事件和来源，生成受控简报草稿", access_mode="read",
            allowed_object_types=frozenset({"Pathogen", "DevelopmentProgram", "IntelligenceEvent", "Organization", "SourceArtifact"}),
            allowed_roles=frozenset({"analyst", "data_manager", "admin"}), risk_level=RiskLevel.R1,
            approval_required=False, max_results=500, timeout_seconds=30, audit_required=True, enabled=True,
            implementation_ref="src.agents.tools.intelligence_read_tools:PeriodicIntelligenceBriefTool",
            permission_resource="IntelligenceBriefDraft", permission_action="create",
        )
        s2_definition = ToolDefinition( # ★ 新增 S2 注册
            tool_id=self.s2_draft_tool.tool_id, name="生成证据包草稿", domain=Domain.SCIENTIFIC,
            version=self.s2_draft_tool.version, description="检索相关实验和来源，组装证据包草稿", access_mode="candidate_write",
            allowed_object_types=frozenset({"Phage", "HostStrain", "LysisAssay", "SourceArtifact"}),
            allowed_roles=frozenset({"researcher", "data_manager", "admin"}), risk_level=RiskLevel.R1,
            approval_required=False, max_results=500, timeout_seconds=30, audit_required=True, enabled=True,
            implementation_ref="src.agents.tools.scientific_draft_tools:EvidencePackageDraftTool",
            permission_resource="EvidencePackage", permission_action="create",
        )
        self.tool_registry = ToolRegistry(version="0.3", tools=[scientific_definition, intelligence_definition, s2_definition])

        # 执行器
        self.execution_service = AgentExecutionService(
            task_repository=self.task_repository, plan_repository=self.plan_repository, step_repository=self.step_repository,
            context_repository=self.context_repository, artifact_repository=self.artifact_repository, artifact_service=self.artifact_service,
            permission_service=self.permission_service, context_service=self.context_service, tool_registry=self.tool_registry,
            tools={self.batch_tool.tool_id: self.batch_tool, self.i1_brief_tool.tool_id: self.i1_brief_tool, self.s2_draft_tool.tool_id: self.s2_draft_tool},
            audit_writer=self.audit_writer, task_service=self.task_service,
        )

        self.result_review_service = AgentResultReviewService(
            task_repository=self.task_repository, artifact_repository=self.artifact_repository,
            approval_service=self.approval_service, task_service=self.task_service, audit_writer=self.audit_writer,
        )
        self.replan_service = AgentReplanService(
            task_repository=self.task_repository, plan_repository=self.plan_repository,
            task_service=self.task_service, audit_writer=self.audit_writer,
        )
        self.intervention_service = AgentInterventionService(
            task_repository=self.task_repository, intervention_repository=self.intervention_repository,
            task_service=self.task_service, audit_writer=self.audit_writer,
        )
        self.retry_policy = RetryPolicy(max_retries=int(getattr(Config, "AGENT_MAX_RETRIES", 1)))
        self.step_retry_service = AgentStepRetryService(
            task_repository=self.task_repository, step_repository=self.step_repository,
            task_service=self.task_service, retry_policy=self.retry_policy, audit_writer=self.audit_writer,
        )
        self.artifact_revision_service = ArtifactRevisionService(
            task_repository=self.task_repository, step_repository=self.step_repository, artifact_repository=self.artifact_repository,
            artifact_service=self.artifact_service, task_service=self.task_service, execution_service=self.execution_service, audit_writer=self.audit_writer,
        )
        self.timeline_service = AgentTimelineService(driver, database=database)

        # 固定模板
        self.s1_service = ScientificS1Service(self)
        self.s2_service = ScientificS2Service(self) # ★ 注入 S2 服务
        self.i1_service = IntelligenceI1Service(self)

        self.schema_version = _schema_version()

_runtime: Optional[AgentRuntime] = None

def get_agent_runtime() -> AgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AgentRuntime()
    return _runtime