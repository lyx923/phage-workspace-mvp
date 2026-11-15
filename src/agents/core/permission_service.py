# src/agents/core/permission_service.py
"""Agent 确定性权限服务。"""
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, Optional, Tuple

from .errors import AgentError, AgentErrorCode
from .models import (
    Domain,
    PermissionDecision,
    PermissionRequest,
)

PermissionKey = Tuple[str, str]


@dataclass(frozen=True)
class AgentPermissionProfile:
    agent_id: str
    domains: FrozenSet[Domain]
    permissions: FrozenSet[PermissionKey]
    enabled: bool = True


@dataclass(frozen=True)
class PermissionPolicy:
    version: str
    role_permissions: Dict[str, FrozenSet[PermissionKey]]
    agent_profiles: Dict[str, AgentPermissionProfile]
    approval_required: FrozenSet[PermissionKey] = field(default_factory=frozenset)


DEFAULT_ROLE_PERMISSIONS: Dict[str, FrozenSet[PermissionKey]] = {
    "researcher": frozenset(
        {
            ("Phage", "read"),
            ("HostStrain", "read"),
            ("Pathogen", "read"),
            ("LysisAssay", "read"),
            ("BiofilmAssay", "read"),
            ("EnzymeGene", "read"),
            ("ExperimentBatch", "read"),
            ("SourceArtifact", "read"),
            ("Review", "read"),
            ("AgentTask", "create"),
            ("AgentTask", "read"),
            ("AgentTask", "cancel_own"),
            ("AgentResult", "read"),
        }
    ),
    "clinician": frozenset(
        {
            ("Phage", "read"),
            ("HostStrain", "read"),
            ("Pathogen", "read"),
            ("ClinicalCase", "read"),
            ("LysisAssay", "read"),
            ("AgentTask", "create"),
            ("AgentTask", "read"),
            ("AgentTask", "cancel_own"),
            ("AgentResult", "read"),
        }
    ),
    "analyst": frozenset(
        {
            ("Organization", "read"),
            ("DevelopmentProgram", "read"),
            ("IntelligenceEvent", "read"),
            ("IntelligenceSignal", "read"),
            ("EngineeringStrategy", "read"),
            ("TechnologyAssessment", "read"),
            ("SourceArtifact", "read"),
            ("Review", "read"),
            ("AgentTask", "create"),
            ("AgentTask", "read"),
            ("AgentTask", "cancel_own"),
            ("AgentResult", "read"),
            # ★ 新增：允许发起情报简报任务
            ("IntelligenceBriefDraft", "create"),
        }
    ),
    "data_manager": frozenset(
        {
            ("Phage", "read"),
            ("HostStrain", "read"),
            ("Pathogen", "read"),
            ("LysisAssay", "read"),
            ("BiofilmAssay", "read"),
            ("EnzymeGene", "read"),
            ("ExperimentBatch", "read"),
            ("Organization", "read"),
            ("DevelopmentProgram", "read"),
            ("IntelligenceEvent", "read"),
            ("SourceArtifact", "read"),
            ("Review", "read"),
            ("AuditEvent", "read"),
            ("AgentTask", "create"),
            ("AgentTask", "read"),
            ("AgentResult", "read"),
            ("AgentPlan", "approve"),
            ("AgentResult", "approve"),
            # ★ 新增：允许发起情报简报任务
            ("IntelligenceBriefDraft", "create"),
        }
    ),
    "admin": frozenset({("*", "*")}),
}


DEFAULT_AGENT_PROFILES: Dict[str, AgentPermissionProfile] = {
    "scientific-agent": AgentPermissionProfile(
        agent_id="scientific-agent",
        domains=frozenset({Domain.SCIENTIFIC}),
        permissions=frozenset(
            {
                ("Phage", "read"),
                ("HostStrain", "read"),
                ("Pathogen", "read"),
                ("LysisAssay", "read"),
                ("BiofilmAssay", "read"),
                ("EnzymeGene", "read"),
                ("ExperimentBatch", "read"),
                ("SourceArtifact", "read"),
                ("Review", "read"),
                ("AuditEvent", "read"),
            }
        ),
    ),
    "intelligence-agent": AgentPermissionProfile(
        agent_id="intelligence-agent",
        domains=frozenset({Domain.INTELLIGENCE}),
        permissions=frozenset(
            {
                ("Organization", "read"),
                ("DevelopmentProgram", "read"),
                ("IntelligenceEvent", "read"),
                ("IntelligenceSignal", "read"),
                ("EngineeringStrategy", "read"),
                ("EngineeredPhageConstruct", "read"),
                ("TechnicalClaim", "read"),
                ("TechnicalResult", "read"),
                ("TechnologyAssessment", "read"),
                ("DecisionRecord", "read"),
                ("SourceArtifact", "read"),
                ("Review", "read"),
                ("AuditEvent", "read"),
                # ★ 新增：允许生成简报
                ("IntelligenceBriefDraft", "create"),
            }
        ),
    ),
}


def build_default_policy() -> PermissionPolicy:
    return PermissionPolicy(
        version="agent-permission-policy-0.1",
        role_permissions=DEFAULT_ROLE_PERMISSIONS,
        agent_profiles=DEFAULT_AGENT_PROFILES,
        approval_required=frozenset(
            {
                ("AgentPlan", "approve"),
                ("AgentResult", "approve"),
                ("CandidateArtifact", "create"),
                ("EvidenceUpgradeProposal", "create"),
            }
        ),
    )


class PermissionService:
    def __init__(self, policy: Optional[PermissionPolicy] = None) -> None:
        self.policy = policy or build_default_policy()

    @staticmethod
    def _has_permission(
        permissions: Iterable[PermissionKey],
        resource: str,
        action: str,
    ) -> bool:
        key = (resource, action)
        return key in permissions or ("*", "*") in permissions

    def evaluate(
        self,
        request: PermissionRequest,
        *,
        valid_approval_ids: Optional[Iterable[str]] = None,
    ) -> PermissionDecision:
        role_permissions = self.policy.role_permissions.get(
            request.user_role, frozenset()
        )
        user_allowed = self._has_permission(
            role_permissions, request.resource, request.action
        )

        profile = self.policy.agent_profiles.get(request.agent_id)
        agent_enabled = bool(profile and profile.enabled)
        domain_allowed = bool(profile and request.domain in profile.domains)
        agent_allowed = bool(
            profile
            and self._has_permission(
                profile.permissions, request.resource, request.action
            )
        )

        resource_allowed = request.resource != "" and request.action != ""

        permission_key = (request.resource, request.action)
        approval_is_required = permission_key in self.policy.approval_required

        valid_approval_set = set(valid_approval_ids or [])
        approval_valid = (
            not approval_is_required
            or (
                request.approval_id is not None
                and request.approval_id in valid_approval_set
            )
        )

        allowed = all(
            [
                user_allowed,
                agent_enabled,
                agent_allowed,
                domain_allowed,
                resource_allowed,
                approval_valid,
            ]
        )

        failed_checks = []
        if not user_allowed:
            failed_checks.append("user_role")
        if not agent_enabled:
            failed_checks.append("agent_disabled_or_missing")
        if not agent_allowed:
            failed_checks.append("agent_permission")
        if not domain_allowed:
            failed_checks.append("domain")
        if not resource_allowed:
            failed_checks.append("resource")
        if not approval_valid:
            failed_checks.append("approval")

        return PermissionDecision(
            allowed=allowed,
            code=(
                "PERMISSION_ALLOWED"
                if allowed
                else AgentErrorCode.PERMISSION_DENIED.value
            ),
            reason=(
                "权限检查通过"
                if allowed
                else "权限检查失败: " + ", ".join(failed_checks)
            ),
            user_allowed=user_allowed,
            agent_allowed=agent_allowed and agent_enabled,
            resource_allowed=resource_allowed,
            domain_allowed=domain_allowed,
            approval_valid=approval_valid,
            policy_version=self.policy.version,
        )

    def require(
        self,
        request: PermissionRequest,
        *,
        valid_approval_ids: Optional[Iterable[str]] = None,
    ) -> PermissionDecision:
        decision = self.evaluate(
            request, valid_approval_ids=valid_approval_ids
        )
        if not decision.allowed:
            raise AgentError(
                AgentErrorCode.PERMISSION_DENIED,
                decision.reason,
                details={
                    "permission_request": request.to_dict(),
                    "permission_decision": decision.to_dict(),
                },
            )
        return decision