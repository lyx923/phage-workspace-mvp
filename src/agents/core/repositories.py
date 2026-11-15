# src/agents/core/repositories.py
"""Agent 仓储接口及测试用内存实现。"""
from abc import ABC, abstractmethod
from copy import deepcopy
from threading import RLock
from typing import Dict, List, Optional

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentApproval, AgentArtifact, AgentIntervention, AgentPlan, AgentStep,
    AgentTask, ApprovalStatus, ArtifactStatus, ContextSnapshot, ContextStatus,
    TaskStatus,
)
from .state_machine import AgentTaskStateMachine

class AgentTaskRepository(ABC):
    @abstractmethod
    def create(self, task: AgentTask) -> AgentTask: raise NotImplementedError
    @abstractmethod
    def get(self, task_id: str) -> Optional[AgentTask]: raise NotImplementedError
    @abstractmethod
    def save(self, task: AgentTask) -> AgentTask: raise NotImplementedError
    @abstractmethod
    def transition(self, task_id: str, *, expected_status: TaskStatus, target_status: TaskStatus) -> AgentTask: raise NotImplementedError

class AgentPlanRepository(ABC):
    @abstractmethod
    def create(self, plan: AgentPlan) -> AgentPlan: raise NotImplementedError
    @abstractmethod
    def get(self, plan_id: str) -> Optional[AgentPlan]: raise NotImplementedError
    @abstractmethod
    def save(self, plan: AgentPlan) -> AgentPlan: raise NotImplementedError

class AgentStepRepository(ABC):
    @abstractmethod
    def get(self, step_id: str) -> Optional[AgentStep]: raise NotImplementedError
    @abstractmethod
    def save(self, step: AgentStep) -> AgentStep: raise NotImplementedError
    @abstractmethod
    def list_for_plan(self, plan_id: str) -> List[AgentStep]: raise NotImplementedError

class AgentArtifactRepository(ABC):
    @abstractmethod
    def create(self, artifact: AgentArtifact) -> AgentArtifact: raise NotImplementedError
    @abstractmethod
    def get(self, artifact_id: str) -> Optional[AgentArtifact]: raise NotImplementedError
    @abstractmethod
    def save(self, artifact: AgentArtifact) -> AgentArtifact: raise NotImplementedError
    @abstractmethod
    def list_for_task(self, task_id: str) -> List[AgentArtifact]: raise NotImplementedError

class AgentApprovalRepository(ABC):
    @abstractmethod
    def create(self, approval: AgentApproval) -> AgentApproval: raise NotImplementedError
    @abstractmethod
    def get(self, approval_id: str) -> Optional[AgentApproval]: raise NotImplementedError
    @abstractmethod
    def save(self, approval: AgentApproval) -> AgentApproval: raise NotImplementedError
    @abstractmethod
    def find_active(self, *, task_id: str, approval_type: str, plan_id: Optional[str] = None, plan_version: Optional[int] = None, artifact_id: Optional[str] = None, artifact_version: Optional[int] = None) -> List[AgentApproval]: raise NotImplementedError

class AgentInterventionRepository(ABC):
    @abstractmethod
    def create(self, intervention: AgentIntervention) -> AgentIntervention: raise NotImplementedError
    @abstractmethod
    def list_for_task(self, task_id: str) -> List[AgentIntervention]: raise NotImplementedError

class ContextSnapshotRepository(ABC):
    @abstractmethod
    def create(self, snapshot: ContextSnapshot) -> ContextSnapshot: raise NotImplementedError
    @abstractmethod
    def get(self, context_snapshot_id: str) -> Optional[ContextSnapshot]: raise NotImplementedError

# ============================================================
# 内存实现
# ============================================================
class InMemoryAgentTaskRepository(AgentTaskRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentTask] = {}
        self._lock = RLock()
    def create(self, task: AgentTask) -> AgentTask:
        with self._lock:
            if task.task_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, f"任务已存在: {task.task_id}")
            self._records[task.task_id] = deepcopy(task)
            return deepcopy(task)
    def get(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            task = self._records.get(task_id)
            return deepcopy(task) if task else None
    def save(self, task: AgentTask) -> AgentTask:
        with self._lock:
            current = self._records.get(task.task_id)
            if current is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task.task_id}")
            if task.version != current.version: raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "任务版本已变化")
            updated = deepcopy(task)
            updated.version += 1
            self._records[task.task_id] = updated
            return deepcopy(updated)
    def transition(self, task_id: str, *, expected_status: TaskStatus, target_status: TaskStatus) -> AgentTask:
        with self._lock:
            current = self._records.get(task_id)
            if current is None: raise AgentError(AgentErrorCode.TASK_NOT_FOUND, f"任务不存在: {task_id}")
            if current.status != expected_status: raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "任务状态不一致")
            AgentTaskStateMachine.require_transition(current.status, target_status)
            current.status = target_status
            current.version += 1
            self._records[task_id] = current
            return deepcopy(current)

class InMemoryAgentPlanRepository(AgentPlanRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentPlan] = {}
        self._lock = RLock()
    def create(self, plan: AgentPlan) -> AgentPlan:
        with self._lock:
            if plan.plan_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, f"计划已存在: {plan.plan_id}")
            self._records[plan.plan_id] = deepcopy(plan)
            return deepcopy(plan)
    def get(self, plan_id: str) -> Optional[AgentPlan]:
        with self._lock:
            plan = self._records.get(plan_id)
            return deepcopy(plan) if plan else None
    def save(self, plan: AgentPlan) -> AgentPlan:
        with self._lock:
            self._records[plan.plan_id] = deepcopy(plan)
            return deepcopy(plan)

class InMemoryAgentStepRepository(AgentStepRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentStep] = {}
        self._lock = RLock()
    def seed(self, step: AgentStep) -> None:
        with self._lock: self._records[step.step_id] = deepcopy(step)
    def get(self, step_id: str) -> Optional[AgentStep]:
        with self._lock:
            step = self._records.get(step_id)
            return deepcopy(step) if step else None
    def save(self, step: AgentStep) -> AgentStep:
        with self._lock:
            current = self._records.get(step.step_id)
            if current is None: raise AgentError(AgentErrorCode.STEP_NOT_FOUND, f"步骤不存在: {step.step_id}")
            if step.record_version != current.record_version: raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "步骤版本已变化")
            updated = deepcopy(step)
            updated.record_version += 1
            self._records[step.step_id] = updated
            return deepcopy(updated)
    def list_for_plan(self, plan_id: str) -> List[AgentStep]:
        with self._lock:
            return sorted([deepcopy(s) for s in self._records.values() if s.plan_id == plan_id], key=lambda s: s.sequence)

class InMemoryAgentArtifactRepository(AgentArtifactRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentArtifact] = {}
        self._lock = RLock()
    def create(self, artifact: AgentArtifact) -> AgentArtifact:
        with self._lock:
            if artifact.artifact_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, f"Artifact 已存在: {artifact.artifact_id}")
            self._records[artifact.artifact_id] = deepcopy(artifact)
            return deepcopy(artifact)
    def get(self, artifact_id: str) -> Optional[AgentArtifact]:
        with self._lock:
            a = self._records.get(artifact_id)
            return deepcopy(a) if a else None
    def save(self, artifact: AgentArtifact) -> AgentArtifact:
        with self._lock:
            current = self._records.get(artifact.artifact_id)
            if current is None: raise AgentError(AgentErrorCode.TOOL_OUTPUT_INVALID, f"Artifact 不存在: {artifact.artifact_id}")
            if artifact.record_version != current.record_version: raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "Artifact 版本已变化")
            updated = deepcopy(artifact)
            updated.record_version += 1
            self._records[artifact.artifact_id] = updated
            return deepcopy(updated)
    def list_for_task(self, task_id: str) -> List[AgentArtifact]:
        with self._lock:
            return [deepcopy(a) for a in self._records.values() if a.task_id == task_id]

class InMemoryAgentApprovalRepository(AgentApprovalRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentApproval] = {}
        self._lock = RLock()
    def create(self, approval: AgentApproval) -> AgentApproval:
        with self._lock:
            if approval.approval_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, f"审批已存在: {approval.approval_id}")
            self._records[approval.approval_id] = deepcopy(approval)
            return deepcopy(approval)
    def get(self, approval_id: str) -> Optional[AgentApproval]:
        with self._lock:
            a = self._records.get(approval_id)
            return deepcopy(a) if a else None
    def save(self, approval: AgentApproval) -> AgentApproval:
        with self._lock:
            current = self._records.get(approval.approval_id)
            if current is None: raise AgentError(AgentErrorCode.APPROVAL_REQUIRED, f"审批不存在: {approval.approval_id}")
            if approval.version != current.version: raise AgentError(AgentErrorCode.CONCURRENT_UPDATE, "审批版本已变化")
            updated = deepcopy(approval)
            updated.version += 1
            self._records[approval.approval_id] = updated
            return deepcopy(updated)
    def find_active(self, *, task_id: str, approval_type: str, plan_id: Optional[str] = None, plan_version: Optional[int] = None, artifact_id: Optional[str] = None, artifact_version: Optional[int] = None) -> List[AgentApproval]:
        with self._lock:
            matched: List[AgentApproval] = []
            for a in self._records.values():
                if a.task_id != task_id or a.approval_type.value != approval_type: continue
                if a.status != ApprovalStatus.ACTIVE: continue
                if plan_id is not None and a.plan_id != plan_id: continue
                if plan_version is not None and a.plan_version != plan_version: continue
                if artifact_id is not None and a.artifact_id != artifact_id: continue
                if artifact_version is not None and a.artifact_version != artifact_version: continue
                matched.append(deepcopy(a))
            return matched

class InMemoryAgentInterventionRepository(AgentInterventionRepository):
    def __init__(self) -> None:
        self._records: Dict[str, AgentIntervention] = {}
        self._lock = RLock()
    def create(self, intervention: AgentIntervention) -> AgentIntervention:
        with self._lock:
            if intervention.intervention_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, "人工干预记录已经存在")
            self._records[intervention.intervention_id] = deepcopy(intervention)
            return deepcopy(intervention)
    def list_for_task(self, task_id: str) -> List[AgentIntervention]:
        with self._lock:
            records = [deepcopy(item) for item in self._records.values() if item.task_id == task_id]
            records.sort(key=lambda i: i.created_at)
            return records

class InMemoryContextSnapshotRepository(ContextSnapshotRepository):
    def __init__(self) -> None:
        self._records: Dict[str, ContextSnapshot] = {}
        self._lock = RLock()
    def create(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        with self._lock:
            if snapshot.context_snapshot_id in self._records: raise AgentError(AgentErrorCode.DUPLICATE_OPERATION, "ContextSnapshot 已存在")
            self._records[snapshot.context_snapshot_id] = deepcopy(snapshot)
            return deepcopy(snapshot)
    def get(self, context_snapshot_id: str) -> Optional[ContextSnapshot]:
        with self._lock:
            item = self._records.get(context_snapshot_id)
            return deepcopy(item) if item else None