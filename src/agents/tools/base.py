# src/agents/tools/base.py
"""Agent 工具统一接口。"""
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from src.agents.core.models import SourceReference


@dataclass(frozen=True)
class ToolExecutionContext:
    task_id: str
    step_id: str
    user_id: str
    user_role: str
    agent_id: str
    domain: str
    permission_scope: Dict[str, Any]
    context_snapshot_id: str
    correlation_id: str
    schema_version: str


@dataclass
class ToolResult:
    status: str
    data: Optional[Dict[str, Any]]
    artifact_type: Optional[str]
    source_references: List[SourceReference] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["source_references"] = [
            item.to_dict() for item in self.source_references
        ]
        return result


class AgentTool(ABC):
    tool_id: str
    version: str
    domain: str
    risk_level: str
    access_mode: str

    @abstractmethod
    def validate_input(self, payload: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self,
        payload: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        raise NotImplementedError