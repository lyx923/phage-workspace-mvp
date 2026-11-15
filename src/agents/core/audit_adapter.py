# src/agents/core/audit_adapter.py
"""Agent 审计适配。

- InMemoryAuditWriter：内存实现，仅用于测试；
- Neo4jAuditWriter：把 Agent 的审计请求转发到 src.shared.audit_service，
  并直接传递 correlation_id / domain / task_id / step_id。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from .errors import AgentError, AgentErrorCode


@dataclass(frozen=True)
class AgentAuditRecord:
    audit_id: str
    action_type: str
    object_type: str
    object_id: str
    actor_id: str
    correlation_id: Optional[str]
    domain: Optional[str]
    task_id: Optional[str]
    step_id: Optional[str]
    delta: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None


class InMemoryAuditWriter:
    """仅用于测试，不得作为生产默认审计实现。"""

    def __init__(self, *, fail_writes: bool = False) -> None:
        self.records: List[AgentAuditRecord] = []
        self.fail_writes = fail_writes

    def __call__(
        self,
        *,
        action_type: str,
        object_type: str,
        object_id: str,
        actor_id: str,
        delta: Optional[dict] = None,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
        domain: Optional[str] = None,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> str:
        if self.fail_writes:
            raise AgentError(
                AgentErrorCode.AUDIT_WRITE_FAILED,
                "测试审计写入失败",
                correlation_id=correlation_id,
            )

        audit_id = f"TEST-AUDIT-{uuid4().hex[:8].upper()}"
        self.records.append(
            AgentAuditRecord(
                audit_id=audit_id,
                action_type=action_type,
                object_type=object_type,
                object_id=object_id,
                actor_id=actor_id,
                correlation_id=correlation_id,
                domain=domain,
                task_id=task_id,
                step_id=step_id,
                delta=dict(delta or {}),
                reason=reason,
            )
        )
        return audit_id


class Neo4jAuditWriter:
    """正式审计适配器。

    依赖 src.shared.audit_service.write_audit_event 的扩展签名
    （v0.8 起支持 correlation_id / domain / task_id / step_id）。
    """

    def __init__(
        self,
        driver,
        write_function: Callable,
    ) -> None:
        self.driver = driver
        self.write_function = write_function

    def __call__(
        self,
        *,
        action_type: str,
        object_type: str,
        object_id: str,
        actor_id: str,
        delta: Optional[dict] = None,
        reason: Optional[str] = None,
        correlation_id: Optional[str] = None,
        domain: Optional[str] = None,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> str:
        try:
            return self.write_function(
                self.driver,
                action_type=action_type,
                object_type=object_type,
                object_id=object_id,
                actor_id=actor_id,
                delta=delta or None,
                reason=reason,
                correlation_id=correlation_id,
                domain=domain,
                task_id=task_id,
                step_id=step_id,
            )
        except AgentError:
            raise
        except Exception as exc:
            raise AgentError(
                AgentErrorCode.AUDIT_WRITE_FAILED,
                "Agent 审计写入失败",
                correlation_id=correlation_id,
                details={"exception_type": type(exc).__name__},
            ) from exc