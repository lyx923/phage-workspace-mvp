# src/agents/core/neo4j_repositories.py
"""Neo4j Agent 仓储实现。"""
from typing import List, Optional

from neo4j import Driver

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentApproval, AgentArtifact, AgentIntervention, AgentPlan, AgentStep,
    AgentTask, ApprovalStatus, ContextSnapshot, TaskStatus,
)
from .neo4j_serialization import (
    approval_from_props, artifact_from_props, context_snapshot_from_props,
    dumps, intervention_from_props, plan_from_props, step_from_props, task_from_props,
)
from .repositories import (
    AgentApprovalRepository, AgentArtifactRepository, AgentInterventionRepository,
    AgentPlanRepository, AgentStepRepository, AgentTaskRepository, ContextSnapshotRepository,
)
from .state_machine import AgentTaskStateMachine

# Task 略（保持原样）
class Neo4jAgentTaskRepository(AgentTaskRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, task: AgentTask) -> AgentTask:
        with self.driver.session() as session:
            record = session.run("""
                CREATE (t:AgentTask {
                    task_id: $task_id, task_type: $task_type, domain: $domain,
                    title: $title, user_request: $user_request, normalized_goal: $normalized_goal,
                    scope_json: $scope_json, submitted_by: $submitted_by, assigned_agent: $assigned_agent,
                    risk_level: $risk_level, status: $status, current_plan_version: $current_plan_version,
                    current_plan_id: $current_plan_id, context_snapshot_id: $context_snapshot_id,
                    correlation_id: $correlation_id, created_at: $created_at, started_at: $started_at,
                    completed_at: $completed_at, result_status: $result_status,
                    cancellation_reason: $cancellation_reason, version: $version
                }) RETURN properties(t) AS props
            """, task_id=task.task_id, task_type=task.task_type, domain=task.domain.value,
                 title=task.title, user_request=task.user_request, normalized_goal=task.normalized_goal,
                 scope_json=dumps(task.scope), submitted_by=task.submitted_by, assigned_agent=task.assigned_agent,
                 risk_level=task.risk_level.value, status=task.status.value, current_plan_version=task.current_plan_version,
                 current_plan_id=task.current_plan_id, context_snapshot_id=task.context_snapshot_id,
                 correlation_id=task.correlation_id, created_at=task.created_at, started_at=task.started_at,
                 completed_at=task.completed_at, result_status=task.result_status,
                 cancellation_reason=task.cancellation_reason, version=task.version).single()
        return task_from_props(record["props"])
    def get(self, task_id: str) -> Optional[AgentTask]:
        with self.driver.session() as session:
            record = session.run("MATCH (t:AgentTask {task_id: $task_id}) RETURN properties(t) AS props", task_id=task_id).single()
        return task_from_props(record["props"]) if record else None
    def save(self, task: AgentTask) -> AgentTask:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id, version: $expected_version})
                SET t.task_type = $task_type, t.domain = $domain, t.title = $title,
                    t.user_request = $user_request, t.normalized_goal = $normalized_goal,
                    t.scope_json = $scope_json, t.submitted_by = $submitted_by,
                    t.assigned_agent = $assigned_agent, t.risk_level = $risk_level,
                    t.status = $status, t.current_plan_version = $current_plan_version,
                    t.current_plan_id = $current_plan_id, t.context_snapshot_id = $context_snapshot_id,
                    t.started_at = $started_at, t.completed_at = $completed_at,
                    t.result_status = $result_status, t.cancellation_reason = $cancellation_reason,
                    t.version = t.version + 1, t.updated_at = datetime()
                RETURN properties(t) AS props
            """, task_id=task.task_id, expected_version=task.version, task_type=task.task_type,
                 domain=task.domain.value, title=task.title, user_request=task.user_request,
                 normalized_goal=task.normalized_goal, scope_json=dumps(task.scope),
                 submitted_by=task.submitted_by, assigned_agent=task.assigned_agent,
                 risk_level=task.risk_level.value, status=task.status.value,
                 current_plan_version=task.current_plan_version, current_plan_id=task.current_plan_id,
                 context_snapshot_id=task.context_snapshot_id, started_at=task.started_at,
                 completed_at=task.completed_at, result_status=task.result_status,
                 cancellation_reason=task.cancellation_reason).single()
            if record is None:
                current = self.get(task.task_id)
                if current is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task.task_id}")
                raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "任务版本已变化, 拒绝覆盖")
        return task_from_props(record["props"])
    def transition(self, task_id: str, *, expected_status: TaskStatus, target_status: TaskStatus) -> AgentTask:
        AgentTaskStateMachine.require_transition(expected_status, target_status)
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id, status: $expected_status})
                SET t.status = $target_status, t.version = t.version + 1, t.updated_at = datetime()
                RETURN properties(t) AS props
            """, task_id=task_id, expected_status=expected_status.value, target_status=target_status.value).single()
            if record is None:
                current = self.get(task_id)
                if current is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}")
                raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "任务当前状态与预期不一致")
        return task_from_props(record["props"])

class Neo4jAgentPlanRepository(AgentPlanRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, plan: AgentPlan) -> AgentPlan:
        with self.driver.session() as session:
            def write_plan(tx):
                tx.run("""
                    MATCH (t:AgentTask {task_id: $task_id})
                    CREATE (p:AgentPlan {
                        plan_id: $plan_id, task_id: $task_id, version: $version,
                        goal_summary: $goal_summary, assumptions_json: $assumptions_json,
                        open_questions_json: $open_questions_json, required_inputs_json: $required_inputs_json,
                        expected_artifacts_json: $expected_artifacts_json, approval_required: $approval_required,
                        generated_by: $generated_by, generated_at: $generated_at, supersedes_plan_id: $supersedes_plan_id,
                        context_snapshot_id: $context_snapshot_id, status: $status
                    }) CREATE (t)-[:HAS_PLAN]->(p)
                """, plan_id=plan.plan_id, task_id=plan.task_id, version=plan.version, goal_summary=plan.goal_summary,
                     assumptions_json=dumps(plan.assumptions), open_questions_json=dumps(plan.open_questions),
                     required_inputs_json=dumps(plan.required_inputs), expected_artifacts_json=dumps(plan.expected_artifacts),
                     approval_required=plan.approval_required, generated_by=plan.generated_by, generated_at=plan.generated_at,
                     supersedes_plan_id=plan.supersedes_plan_id, context_snapshot_id=plan.context_snapshot_id, status=plan.status.value)
                for step in plan.steps:
                    tx.run("""
                        MATCH (p:AgentPlan {plan_id: $plan_id})
                        CREATE (s:AgentStep {
                            step_id: $step_id, plan_id: $plan_id, sequence: $sequence, step_type: $step_type,
                            name: $name, description: $description, tool_id: $tool_id, tool_version: $tool_version,
                            input_references_json: $input_references_json, expected_output_type: $expected_output_type,
                            risk_level: $risk_level, approval_required: $approval_required, can_retry: $can_retry,
                            can_skip: $can_skip, status: $status, retry_count: $retry_count, started_at: $started_at,
                            completed_at: $completed_at, error_code: $error_code, error_summary: $error_summary,
                            record_version: $record_version
                        }) CREATE (p)-[:HAS_STEP]->(s)
                    """, step_id=step.step_id, plan_id=plan.plan_id, sequence=step.sequence, step_type=step.step_type.value,
                         name=step.name, description=step.description, tool_id=step.tool_id, tool_version=step.tool_version,
                         input_references_json=dumps(step.input_references), expected_output_type=step.expected_output_type,
                         risk_level=step.risk_level.value, approval_required=step.approval_required, can_retry=step.can_retry,
                         can_skip=step.can_skip, status=step.status.value, retry_count=step.retry_count, started_at=step.started_at,
                         completed_at=step.completed_at, error_code=step.error_code, error_summary=step.error_summary,
                         record_version=step.record_version)
            session.execute_write(write_plan)
        loaded = self.get(plan.plan_id)
        if loaded is None: raise AgentError(AgentErrorCode.PLAN_NOT_FOUND, "计划创建后无法读取")
        return loaded
    def get(self, plan_id: str) -> Optional[AgentPlan]:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (p:AgentPlan {plan_id: $plan_id})
                OPTIONAL MATCH (p)-[:HAS_STEP]->(s:AgentStep)
                WITH p, s ORDER BY s.sequence
                RETURN properties(p) AS props, collect(CASE WHEN s IS NULL THEN null ELSE properties(s) END) AS step_props
            """, plan_id=plan_id).single()
        if record is None: return None
        steps = [step_from_props(props) for props in record["step_props"] if props is not None]
        return plan_from_props(record["props"], steps)
    def save(self, plan: AgentPlan) -> AgentPlan:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (p:AgentPlan {plan_id: $plan_id})
                SET p.status = $status, p.goal_summary = $goal_summary,
                    p.assumptions_json = $assumptions_json, p.open_questions_json = $open_questions_json,
                    p.required_inputs_json = $required_inputs_json, p.expected_artifacts_json = $expected_artifacts_json,
                    p.approval_required = $approval_required, p.generated_by = $generated_by,
                    p.supersedes_plan_id = $supersedes_plan_id, p.context_snapshot_id = $context_snapshot_id,
                    p.updated_at = datetime()
                RETURN properties(p) AS props
            """, plan_id=plan.plan_id, status=plan.status.value, goal_summary=plan.goal_summary,
                 assumptions_json=dumps(plan.assumptions), open_questions_json=dumps(plan.open_questions),
                 required_inputs_json=dumps(plan.required_inputs), expected_artifacts_json=dumps(plan.expected_artifacts),
                 approval_required=plan.approval_required, generated_by=plan.generated_by,
                 supersedes_plan_id=plan.supersedes_plan_id, context_snapshot_id=plan.context_snapshot_id).single()
            if record is None: raise AgentError(AgentErrorCode.PLAN_NOT_FOUND, f"计划不存在: {plan.plan_id}")
        # 重新读取步骤
        steps = []
        with self.driver.session() as session:
            res = session.run("MATCH (s:AgentStep {plan_id: $plan_id}) RETURN properties(s) AS props ORDER BY s.sequence", plan_id=plan.plan_id)
            steps = [step_from_props(r["props"]) for r in res]
        return plan_from_props(record["props"], steps)

class Neo4jAgentStepRepository(AgentStepRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def get(self, step_id: str) -> Optional[AgentStep]:
        with self.driver.session() as session:
            record = session.run("MATCH (s:AgentStep {step_id: $step_id}) RETURN properties(s) AS props", step_id=step_id).single()
        return step_from_props(record["props"]) if record else None
    def save(self, step: AgentStep) -> AgentStep:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (s:AgentStep {step_id: $step_id, record_version: $expected_version})
                SET s.status = $status, s.retry_count = $retry_count, s.started_at = $started_at,
                    s.completed_at = $completed_at, s.error_code = $error_code, s.error_summary = $error_summary,
                    s.record_version = s.record_version + 1, s.updated_at = datetime()
                RETURN properties(s) AS props
            """, step_id=step.step_id, expected_version=step.record_version, status=step.status.value,
                 retry_count=step.retry_count, started_at=step.started_at, completed_at=step.completed_at,
                 error_code=step.error_code, error_summary=step.error_summary).single()
            if record is None:
                current = self.get(step.step_id)
                if current is None: raise AgentError(AgentErrorCode.STEP_NOT_FOUND, f"步骤不存在: {step.step_id}")
                raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "步骤版本已变化, 拒绝覆盖")
        return step_from_props(record["props"])
    def list_for_plan(self, plan_id: str) -> List[AgentStep]:
        with self.driver.session() as session:
            records = session.run("MATCH (s:AgentStep {plan_id: $plan_id}) RETURN properties(s) AS props ORDER BY s.sequence", plan_id=plan_id)
            return [step_from_props(r["props"]) for r in records]

class Neo4jAgentArtifactRepository(AgentArtifactRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, artifact: AgentArtifact) -> AgentArtifact:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id}) MATCH (s:AgentStep {step_id: $step_id})
                CREATE (a:AgentArtifact {
                    artifact_id: $artifact_id, artifact_family_id: $artifact_family_id, task_id: $task_id,
                    step_id: $step_id, artifact_type: $artifact_type, artifact_version: $artifact_version,
                    content_json: $content_json, checksum: $checksum, created_by: $created_by,
                    schema_version: $schema_version, context_snapshot_id: $context_snapshot_id,
                    source_references_json: $source_references_json, status: $status,
                    supersedes_artifact_id: $supersedes_artifact_id, created_at: $created_at,
                    reviewed_at: $reviewed_at, reviewed_by: $reviewed_by, record_version: $record_version
                }) CREATE (s)-[:PRODUCED]->(a) CREATE (t)-[:HAS_ARTIFACT]->(a)
                RETURN properties(a) AS props
            """, artifact_id=artifact.artifact_id, artifact_family_id=artifact.artifact_family_id, task_id=artifact.task_id,
                 step_id=artifact.step_id, artifact_type=artifact.artifact_type.value, artifact_version=artifact.version,
                 content_json=dumps(artifact.content), checksum=artifact.checksum, created_by=artifact.created_by,
                 schema_version=artifact.schema_version, context_snapshot_id=artifact.context_snapshot_id,
                 source_references_json=dumps([item.to_dict() for item in artifact.source_references]),
                 status=artifact.status.value, supersedes_artifact_id=artifact.supersedes_artifact_id,
                 created_at=artifact.created_at, reviewed_at=artifact.reviewed_at, reviewed_by=artifact.reviewed_by,
                 record_version=artifact.record_version).single()
            if record is None: raise AgentError(AgentErrorCode.TOOL_OUTPUT_INVALID, "Artifact 创建失败: 任务或步骤不存在")
        return artifact_from_props(record["props"])
    def get(self, artifact_id: str) -> Optional[AgentArtifact]:
        with self.driver.session() as session:
            record = session.run("MATCH (a:AgentArtifact {artifact_id: $artifact_id}) RETURN properties(a) AS props", artifact_id=artifact_id).single()
        return artifact_from_props(record["props"]) if record else None
    def save(self, artifact: AgentArtifact) -> AgentArtifact:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (a:AgentArtifact {artifact_id: $artifact_id, record_version: $expected_version})
                SET a.content_json = $content_json, a.checksum = $checksum, a.status = $status,
                    a.reviewed_at = $reviewed_at, a.reviewed_by = $reviewed_by,
                    a.record_version = a.record_version + 1, a.updated_at = datetime()
                RETURN properties(a) AS props
            """, artifact_id=artifact.artifact_id, expected_version=artifact.record_version,
                 content_json=dumps(artifact.content), checksum=artifact.checksum, status=artifact.status.value,
                 reviewed_at=artifact.reviewed_at, reviewed_by=artifact.reviewed_by).single()
            if record is None:
                current = self.get(artifact.artifact_id)
                if current is None: raise AgentError(AgentErrorCode.TOOL_OUTPUT_INVALID, "Artifact 不存在")
                raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "Artifact 版本已变化, 拒绝覆盖")
        return artifact_from_props(record["props"])
    def list_for_task(self, task_id: str) -> List[AgentArtifact]:
        with self.driver.session() as session:
            records = session.run("MATCH (a:AgentArtifact {task_id: $task_id}) RETURN properties(a) AS props ORDER BY a.created_at, a.artifact_version", task_id=task_id)
            return [artifact_from_props(r["props"]) for r in records]

class Neo4jAgentApprovalRepository(AgentApprovalRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, approval: AgentApproval) -> AgentApproval:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id})
                CREATE (a:AgentApproval {
                    approval_id: $approval_id, task_id: $task_id, approval_type: $approval_type,
                    requested_by: $requested_by, requested_from_role: $requested_from_role,
                    requested_from_user: $requested_from_user, plan_id: $plan_id, plan_version: $plan_version,
                    step_id: $step_id, artifact_id: $artifact_id, artifact_version: $artifact_version,
                    context_snapshot_id: $context_snapshot_id, decision: $decision, status: $status,
                    comment: $comment, approved_scope_json: $approved_scope_json,
                    rejected_scope_json: $rejected_scope_json, decided_by: $decided_by,
                    requested_at: $requested_at, decided_at: $decided_at, expires_at: $expires_at, version: $version
                }) CREATE (t)-[:HAS_APPROVAL]->(a) RETURN properties(a) AS props
            """, approval_id=approval.approval_id, task_id=approval.task_id, approval_type=approval.approval_type.value,
                 requested_by=approval.requested_by, requested_from_role=approval.requested_from_role,
                 requested_from_user=approval.requested_from_user, plan_id=approval.plan_id, plan_version=approval.plan_version,
                 step_id=approval.step_id, artifact_id=approval.artifact_id, artifact_version=approval.artifact_version,
                 context_snapshot_id=approval.context_snapshot_id, decision=approval.decision.value,
                 status=approval.status.value, comment=approval.comment, approved_scope_json=dumps(approval.approved_scope),
                 rejected_scope_json=dumps(approval.rejected_scope), decided_by=approval.decided_by,
                 requested_at=approval.requested_at, decided_at=approval.decided_at, expires_at=approval.expires_at,
                 version=approval.version).single()
            if record is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "审批创建失败: 任务不存在")
        return approval_from_props(record["props"])
    def get(self, approval_id: str) -> Optional[AgentApproval]:
        with self.driver.session() as session:
            record = session.run("MATCH (a:AgentApproval {approval_id: $approval_id}) RETURN properties(a) AS props", approval_id=approval_id).single()
        return approval_from_props(record["props"]) if record else None
    def save(self, approval: AgentApproval) -> AgentApproval:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (a:AgentApproval {approval_id: $approval_id, version: $expected_version})
                SET a.decision = $decision, a.status = $status, a.comment = $comment,
                    a.approved_scope_json = $approved_scope_json, a.rejected_scope_json = $rejected_scope_json,
                    a.decided_by = $decided_by, a.decided_at = $decided_at, a.version = a.version + 1,
                    a.updated_at = datetime()
                RETURN properties(a) AS props
            """, approval_id=approval.approval_id, expected_version=approval.version, decision=approval.decision.value,
                 status=approval.status.value, comment=approval.comment,
                 approved_scope_json=dumps(approval.approved_scope), rejected_scope_json=dumps(approval.rejected_scope),
                 decided_by=approval.decided_by, decided_at=approval.decided_at).single()
            if record is None:
                current = self.get(approval.approval_id)
                if current is None: raise AgentError(AgentErrorCode.APPROVAL_REQUIRED, "审批不存在")
                raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "审批版本已变化, 拒绝覆盖")
        return approval_from_props(record["props"])
    def find_active(self, *, task_id: str, approval_type: str, plan_id: Optional[str] = None, plan_version: Optional[int] = None, artifact_id: Optional[str] = None, artifact_version: Optional[int] = None) -> List[AgentApproval]:
        with self.driver.session() as session:
            records = session.run("""
                MATCH (a:AgentApproval)
                WHERE a.task_id = $task_id AND a.approval_type = $approval_type AND a.status = $active_status
                  AND ($plan_id IS NULL OR a.plan_id = $plan_id)
                  AND ($plan_version IS NULL OR a.plan_version = $plan_version)
                  AND ($artifact_id IS NULL OR a.artifact_id = $artifact_id)
                  AND ($artifact_version IS NULL OR a.artifact_version = $artifact_version)
                RETURN properties(a) AS props
            """, task_id=task_id, approval_type=approval_type, active_status=ApprovalStatus.ACTIVE.value,
                 plan_id=plan_id, plan_version=plan_version, artifact_id=artifact_id, artifact_version=artifact_version)
            return [approval_from_props(r["props"]) for r in records]

class Neo4jAgentInterventionRepository(AgentInterventionRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, intervention: AgentIntervention) -> AgentIntervention:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id})
                CREATE (i:AgentIntervention {
                    intervention_id: $intervention_id, task_id: $task_id, intervention_type: $intervention_type,
                    requested_by: $requested_by, instruction: $instruction, affected_step_id: $affected_step_id,
                    before_state: $before_state, after_state: $after_state, created_at: $created_at,
                    correlation_id: $correlation_id, version: $version
                }) CREATE (i)-[:INTERVENES_IN]->(t) RETURN properties(i) AS props
            """, intervention_id=intervention.intervention_id, task_id=intervention.task_id,
                 intervention_type=intervention.intervention_type.value, requested_by=intervention.requested_by,
                 instruction=intervention.instruction, affected_step_id=intervention.affected_step_id,
                 before_state=intervention.before_state, after_state=intervention.after_state,
                 created_at=intervention.created_at, correlation_id=intervention.correlation_id, version=intervention.version).single()
            if record is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, "干预记录创建失败：任务不存在")
        return intervention_from_props(record["props"])
    def list_for_task(self, task_id: str) -> List[AgentIntervention]:
        with self.driver.session() as session:
            records = session.run("MATCH (i:AgentIntervention {task_id: $task_id}) RETURN properties(i) AS props ORDER BY i.created_at", task_id=task_id)
            return [intervention_from_props(r["props"]) for r in records]

class Neo4jContextSnapshotRepository(ContextSnapshotRepository):
    def __init__(self, driver: Driver) -> None: self.driver = driver
    def create(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        with self.driver.session() as session:
            record = session.run("""
                MATCH (t:AgentTask {task_id: $task_id}) MATCH (p:AgentPlan {plan_id: $plan_id})
                CREATE (c:ContextSnapshot {
                    context_snapshot_id: $context_snapshot_id, task_id: $task_id, plan_id: $plan_id,
                    plan_version: $plan_version, domain: $domain, user_id: $user_id, agent_id: $agent_id,
                    project_scope_json: $project_scope_json, permission_scope_json: $permission_scope_json,
                    schema_version: $schema_version, model_version: $model_version,
                    tool_registry_version: $tool_registry_version, context_policy_version: $context_policy_version,
                    source_items_json: $source_items_json, allowed_object_types_json: $allowed_object_types_json,
                    excluded_object_types_json: $excluded_object_types_json, created_at: $created_at,
                    expires_at: $expires_at, context_hash: $context_hash, status: $status,
                    invalidation_reason: $invalidation_reason, record_version: $record_version
                }) CREATE (t)-[:USES_CONTEXT]->(c) CREATE (p)-[:USES_CONTEXT]->(c)
                SET t.context_snapshot_id = c.context_snapshot_id, t.updated_at = datetime()
                RETURN properties(c) AS props
            """, context_snapshot_id=snapshot.context_snapshot_id, task_id=snapshot.task_id, plan_id=snapshot.plan_id,
                 plan_version=snapshot.plan_version, domain=snapshot.domain.value, user_id=snapshot.user_id,
                 agent_id=snapshot.agent_id, project_scope_json=dumps(snapshot.project_scope),
                 permission_scope_json=dumps(snapshot.permission_scope), schema_version=snapshot.schema_version,
                 model_version=snapshot.model_version, tool_registry_version=snapshot.tool_registry_version,
                 context_policy_version=snapshot.context_policy_version,
                 source_items_json=dumps([item.to_dict() for item in snapshot.source_items]),
                 allowed_object_types_json=dumps(snapshot.allowed_object_types),
                 excluded_object_types_json=dumps(snapshot.excluded_object_types),
                 created_at=snapshot.created_at, expires_at=snapshot.expires_at, context_hash=snapshot.context_hash,
                 status=snapshot.status.value, invalidation_reason=snapshot.invalidation_reason,
                 record_version=snapshot.record_version).single()
            if record is None: raise AgentError(AgentErrorCode.CONTEXT_INVALID, "ContextSnapshot 创建失败：任务或计划不存在")
        return context_snapshot_from_props(record["props"])
    def get(self, context_snapshot_id: str) -> Optional[ContextSnapshot]:
        with self.driver.session() as session:
            record = session.run("MATCH (c:ContextSnapshot {context_snapshot_id: $cid}) RETURN properties(c) AS props", cid=context_snapshot_id).single()
        return context_snapshot_from_props(record["props"]) if record else None