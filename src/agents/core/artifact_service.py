# src/agents/core/artifact_service.py
"""AgentArtifact 创建、校验和版本管理。"""
import hashlib
import json
from typing import Callable, List, Optional
from uuid import uuid4

from .errors import AgentError, AgentErrorCode
from .models import (
    AgentArtifact,
    ArtifactStatus,
    ArtifactType,
    SourceReference,
)
from .repositories import AgentArtifactRepository


def stable_content_json(content: dict) -> str:
    return json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def calculate_artifact_checksum(content: dict) -> str:
    return hashlib.sha256(stable_content_json(content).encode("utf-8")).hexdigest()


class AgentArtifactService:
    def __init__(
        self,
        *,
        repository: AgentArtifactRepository,
        audit_writer: Callable[..., str],
        artifact_id_factory: Optional[Callable[[], str]] = None,
        family_id_factory: Optional[Callable[[], str]] = None,
    ) -> None:
        self.repository = repository
        self.audit_writer = audit_writer
        self.artifact_id_factory = artifact_id_factory or (
            lambda: f"ART-{uuid4().hex[:12].upper()}"
        )
        self.family_id_factory = family_id_factory or (
            lambda: f"ARTF-{uuid4().hex[:12].upper()}"
        )

    def create(
        self,
        *,
        task_id: str,
        step_id: str,
        artifact_type: ArtifactType,
        content: dict,
        created_by: str,
        schema_version: str,
        context_snapshot_id: str,
        source_references: Optional[List[SourceReference]] = None,
        correlation_id: Optional[str] = None,
        domain: Optional[str] = None,
        artifact_family_id: Optional[str] = None,
        supersedes_artifact_id: Optional[str] = None,
    ) -> AgentArtifact:
        if not isinstance(content, dict):
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID,
                "Artifact content 必须是字典",
                correlation_id=correlation_id,
            )

        version = 1
        previous: Optional[AgentArtifact] = None
        if supersedes_artifact_id:
            previous = self.repository.get(supersedes_artifact_id)
            if previous is None:
                raise AgentError(
                    AgentErrorCode.TOOL_OUTPUT_INVALID,
                    "被替代的 Artifact 不存在",
                    correlation_id=correlation_id,
                )
            version = previous.version + 1
            artifact_family_id = previous.artifact_family_id

        artifact = AgentArtifact(
            artifact_id=self.artifact_id_factory(),
            artifact_family_id=artifact_family_id or self.family_id_factory(),
            task_id=task_id,
            step_id=step_id,
            artifact_type=artifact_type,
            version=version,
            content=dict(content),
            checksum=calculate_artifact_checksum(content),
            created_by=created_by,
            schema_version=schema_version,
            context_snapshot_id=context_snapshot_id,
            source_references=list(source_references or []),
            supersedes_artifact_id=supersedes_artifact_id,
        )

        created = self.repository.create(artifact)

        self.audit_writer(
            action_type="AGENT_ARTIFACT_CREATE",
            object_type="AgentArtifact",
            object_id=created.artifact_id,
            actor_id=created_by,
            correlation_id=correlation_id,
            domain=domain,
            task_id=task_id,
            step_id=step_id,
            delta={
                "artifact_type": artifact_type.value,
                "artifact_family_id": created.artifact_family_id,
                "artifact_version": created.version,
                "checksum": created.checksum,
                "supersedes_artifact_id": supersedes_artifact_id,
            },
            reason="创建 Agent 执行产物",
        )

        if previous is not None:
            previous.status = ArtifactStatus.SUPERSEDED
            self.repository.save(previous)
            self.audit_writer(
                action_type="AGENT_ARTIFACT_SUPERSEDE",
                object_type="AgentArtifact",
                object_id=previous.artifact_id,
                actor_id=created_by,
                correlation_id=correlation_id,
                domain=domain,
                task_id=task_id,
                step_id=step_id,
                delta={
                    "superseded_by": created.artifact_id,
                    "new_version": created.version,
                },
                reason="创建 Artifact 修订版本",
            )

        return created

    def submit_for_review(
        self,
        artifact_id: str,
        *,
        actor_id: str,
        correlation_id: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> AgentArtifact:
        artifact = self.repository.get(artifact_id)
        if artifact is None:
            raise AgentError(
                AgentErrorCode.TOOL_OUTPUT_INVALID,
                f"Artifact 不存在: {artifact_id}",
                correlation_id=correlation_id,
            )
        if artifact.status != ArtifactStatus.DRAFT:
            raise AgentError(
                AgentErrorCode.INVALID_STATE_TRANSITION,
                "只有 DRAFT Artifact 可以送审",
                correlation_id=correlation_id,
                details={"current_status": artifact.status.value},
            )

        artifact.status = ArtifactStatus.RESULT_REVIEW
        saved = self.repository.save(artifact)

        self.audit_writer(
            action_type="AGENT_RESULT_SUBMIT",
            object_type="AgentArtifact",
            object_id=artifact_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            domain=domain,
            task_id=artifact.task_id,
            step_id=artifact.step_id,
            delta={
                "status": {
                    "before": ArtifactStatus.DRAFT.value,
                    "after": ArtifactStatus.RESULT_REVIEW.value,
                }
            },
            reason="提交 Agent 结果审核",
        )
        return saved