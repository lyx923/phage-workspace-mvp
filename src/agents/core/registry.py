# src/agents/core/registry.py
"""版本化 Agent 工具注册表。"""
from dataclasses import asdict, dataclass
from typing import Dict, FrozenSet, Iterable, Optional

from .errors import AgentError, AgentErrorCode
from .models import Domain, RiskLevel


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    name: str
    domain: Domain
    version: str
    description: str
    access_mode: str
    allowed_object_types: FrozenSet[str]
    allowed_roles: FrozenSet[str]
    risk_level: RiskLevel
    approval_required: bool
    max_results: int
    timeout_seconds: int
    audit_required: bool
    enabled: bool
    implementation_ref: str
    permission_resource: str = ""
    permission_action: str = "read"

    def __post_init__(self) -> None:
        if self.access_mode not in {"read", "candidate_write"}:
            raise ValueError("access_mode 只能是 read 或 candidate_write")
        if self.max_results <= 0:
            raise ValueError("max_results 必须大于 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds 必须大于 0")
        if not self.permission_resource:
            raise ValueError("permission_resource 不能为空")
        if not self.permission_action:
            raise ValueError("permission_action 不能为空")

    def to_dict(self) -> dict:
        result = asdict(self)
        result["domain"] = self.domain.value
        result["risk_level"] = self.risk_level.value
        result["allowed_object_types"] = sorted(self.allowed_object_types)
        result["allowed_roles"] = sorted(self.allowed_roles)
        return result


class ToolRegistry:
    def __init__(
        self,
        version: str,
        tools: Optional[Iterable[ToolDefinition]] = None,
    ) -> None:
        self.version = version
        self._tools: Dict[str, ToolDefinition] = {}
        for tool in tools or []:
            self.register(tool)

    @staticmethod
    def _key(tool_id: str, version: str) -> str:
        return f"{tool_id}@{version}"

    def register(self, tool: ToolDefinition) -> None:
        key = self._key(tool.tool_id, tool.version)
        if key in self._tools:
            raise AgentError(
                AgentErrorCode.DUPLICATE_OPERATION,
                f"工具已经注册：{key}",
            )
        self._tools[key] = tool

    def get(self, tool_id: str, version: str) -> ToolDefinition:
        key = self._key(tool_id, version)
        tool = self._tools.get(key)
        if tool is None:
            raise AgentError(
                AgentErrorCode.TOOL_NOT_REGISTERED,
                f"工具未注册：{key}",
            )
        if not tool.enabled:
            raise AgentError(
                AgentErrorCode.TOOL_DISABLED,
                f"工具已停用：{key}",
            )
        return tool

    def require_domain(
        self,
        tool_id: str,
        version: str,
        domain: Domain,
    ) -> ToolDefinition:
        tool = self.get(tool_id, version)
        if tool.domain != domain:
            raise AgentError(
                AgentErrorCode.TOOL_DOMAIN_MISMATCH,
                f"工具 {tool.tool_id} 属于 {tool.domain.value}, "
                f"不能用于 {domain.value}",
            )
        return tool

    def list_enabled(
        self,
        *,
        domain: Optional[Domain] = None,
    ) -> list[ToolDefinition]:
        tools = [t for t in self._tools.values() if t.enabled]
        if domain is not None:
            tools = [t for t in tools if t.domain == domain]
        return sorted(tools, key=lambda item: (item.domain.value, item.tool_id))