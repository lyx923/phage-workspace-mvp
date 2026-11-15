# src/agents/core/context_service.py
"""Agent 上下文快照服务。"""
import hashlib
import json
from dataclasses import replace
from typing import Iterable, Optional

from .errors import AgentError, AgentErrorCode
from .models import (
    ContextItem,
    ContextSnapshot,
    ContextStatus,
    Domain,
    TrustLevel,
)


_EXCLUDED_TRUST_LEVELS = {
    TrustLevel.REJECTED,
    TrustLevel.EXPIRED,
    TrustLevel.REVOKED,
}


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def calculate_context_hash(snapshot: ContextSnapshot) -> str:
    """计算稳定上下文 Hash。展示字段和 record_version 不参与 Hash。"""
    hash_payload = {
        "context_snapshot_id": snapshot.context_snapshot_id,
        "task_id": snapshot.task_id,
        "plan_id": snapshot.plan_id,
        "plan_version": snapshot.plan_version,
        "domain": snapshot.domain.value,
        "user_id": snapshot.user_id,
        "agent_id": snapshot.agent_id,
        "project_scope": snapshot.project_scope,
        "permission_scope": snapshot.permission_scope,
        "schema_version": snapshot.schema_version,
        "model_version": snapshot.model_version,
        "tool_registry_version": snapshot.tool_registry_version,
        "context_policy_version": snapshot.context_policy_version,
        "source_items": [
            item.to_dict()
            for item in sorted(
                snapshot.source_items, key=lambda v: v.item_id
            )
        ],
        "allowed_object_types": sorted(snapshot.allowed_object_types),
        "excluded_object_types": sorted(snapshot.excluded_object_types),
    }
    return hashlib.sha256(_stable_json(hash_payload).encode("utf-8")).hexdigest()


class ContextService:
    def build_snapshot(
        self,
        *,
        context_snapshot_id: str,
        task_id: str,
        plan_id: str,
        plan_version: int,
        domain: Domain,
        user_id: str,
        agent_id: str,
        project_scope: dict,
        permission_scope: dict,
        schema_version: str,
        tool_registry_version: str,
        context_policy_version: str,
        source_items: Iterable[ContextItem],
        allowed_object_types: Iterable[str],
        excluded_object_types: Iterable[str],
        model_version: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> ContextSnapshot:
        filtered_items = [
            item
            for item in source_items
            if item.trust_level not in _EXCLUDED_TRUST_LEVELS
        ]

        snapshot = ContextSnapshot(
            context_snapshot_id=context_snapshot_id,
            task_id=task_id,
            plan_id=plan_id,
            plan_version=plan_version,
            domain=domain,
            user_id=user_id,
            agent_id=agent_id,
            project_scope=dict(project_scope),
            permission_scope=dict(permission_scope),
            schema_version=schema_version,
            model_version=model_version,
            tool_registry_version=tool_registry_version,
            context_policy_version=context_policy_version,
            source_items=list(filtered_items),
            allowed_object_types=sorted(set(allowed_object_types)),
            excluded_object_types=sorted(set(excluded_object_types)),
            expires_at=expires_at,
            status=ContextStatus.DRAFT,
        )
        snapshot.context_hash = calculate_context_hash(snapshot)
        snapshot.status = ContextStatus.ACTIVE
        return snapshot

    def validate_snapshot(
        self,
        snapshot: ContextSnapshot,
        *,
        task_id: str,
        plan_id: str,
        plan_version: int,
        domain: Domain,
        current_tool_registry_version: Optional[str] = None,
    ) -> None:
        if snapshot.status != ContextStatus.ACTIVE:
            raise AgentError(
                AgentErrorCode.CONTEXT_INVALID,
                f"上下文快照不是 ACTIVE 状态: {snapshot.status.value}",
                details={
                    "context_snapshot_id": snapshot.context_snapshot_id,
                    "status": snapshot.status.value,
                },
            )
        if snapshot.task_id != task_id:
            raise AgentError(
                AgentErrorCode.CONTEXT_INVALID,
                "上下文快照属于其他任务",
                details={
                    "expected_task_id": task_id,
                    "actual_task_id": snapshot.task_id,
                },
            )
        if snapshot.plan_id != plan_id or snapshot.plan_version != plan_version:
            raise AgentError(
                AgentErrorCode.PLAN_VERSION_MISMATCH,
                "上下文快照与当前计划版本不一致",
                details={
                    "expected_plan_id": plan_id,
                    "actual_plan_id": snapshot.plan_id,
                    "expected_plan_version": plan_version,
                    "actual_plan_version": snapshot.plan_version,
                },
            )
        if snapshot.domain != domain:
            raise AgentError(
                AgentErrorCode.CONTEXT_DOMAIN_MISMATCH,
                "上下文领域与任务领域不一致",
                details={
                    "expected_domain": domain.value,
                    "actual_domain": snapshot.domain.value,
                },
            )
        actual_hash = calculate_context_hash(snapshot)
        if actual_hash != snapshot.context_hash:
            raise AgentError(
                AgentErrorCode.CONTEXT_HASH_MISMATCH,
                "上下文快照内容已发生变化",
                details={
                    "context_snapshot_id": snapshot.context_snapshot_id,
                    "expected_hash": snapshot.context_hash,
                    "actual_hash": actual_hash,
                },
            )
        if (
            current_tool_registry_version is not None
            and snapshot.tool_registry_version != current_tool_registry_version
        ):
            raise AgentError(
                AgentErrorCode.CONTEXT_INVALID,
                "ContextSnapshot 使用的 Tool Registry 版本已过期",
                details={
                    "snapshot_version": snapshot.tool_registry_version,
                    "current_version": current_tool_registry_version,
                },
            )

    def invalidate(
        self, snapshot: ContextSnapshot, *, reason: str
    ) -> ContextSnapshot:
        if snapshot.status == ContextStatus.INVALIDATED:
            return snapshot
        return replace(
            snapshot,
            status=ContextStatus.INVALIDATED,
            invalidation_reason=reason,
        )