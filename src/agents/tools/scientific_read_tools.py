# src/agents/tools/scientific_read_tools.py
"""科学域只读 Agent 工具。"""
from typing import Callable, List
from uuid import uuid4

from src.agents.core.errors import AgentError, AgentErrorCode
from src.agents.core.models import (
    FindingSeverity,
    SourceReference,
    ValidationFinding,
)
from src.agents.tools.base import (
    AgentTool,
    ToolExecutionContext,
    ToolResult,
)


S1_SUPPORTED_LABELS = {"LysisAssay", "BiofilmAssay", "EnzymeGene"}


class BatchCompletenessTool(AgentTool):
    tool_id = "scientific.batch_completeness"
    version = "0.1"
    domain = "scientific"
    risk_level = "R0"
    access_mode = "read"

    def __init__(
        self,
        query_runner: Callable[..., List[dict]],
        finding_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.query_runner = query_runner
        self.finding_id_factory = finding_id_factory or (
            lambda: f"FIND-{uuid4().hex[:12].upper()}"
        )

    def validate_input(self, payload: dict) -> None:
        batch_id = payload.get("experiment_batch_id")
        if not isinstance(batch_id, str):
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "experiment_batch_id 必须是字符串",
            )
        if not batch_id.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "experiment_batch_id 不能为空",
            )

    def _query_batch(self, batch_id: str):
        rows = self.query_runner(
            """
            MATCH (b:ExperimentBatch {id: $batch_id})
            RETURN b.id AS id,
                   b.name AS name,
                   b.experiment_type AS experiment_type,
                   b.status AS status,
                   b.operator AS operator,
                   b.date AS date
            LIMIT 1
            """,
            batch_id=batch_id,
        )
        return rows[0] if rows else None

    def _query_linked_records(self, batch_id: str) -> List[dict]:
        return self.query_runner(
            """
            MATCH (n)-[:BELONGS_TO_BATCH]->(b:ExperimentBatch {id: $batch_id})
            WHERE any(label IN labels(n) WHERE label IN $supported_labels)
            OPTIONAL MATCH (r:Review)-[:REVIEWS]->(n)
            OPTIONAL MATCH (n)-[:DERIVED_FROM]->(src:SourceArtifact)
            WITH n,
                 labels(n) AS labs,
                 collect(DISTINCT {
                     review_id: r.review_id, decision: r.decision
                 }) AS reviews,
                 collect(DISTINCT {
                     source_id: src.source_id,
                     source_type: src.source_type,
                     source_version: coalesce(src.version, src.source_version),
                     review_status: src.review_status
                 }) AS sources
            RETURN
                CASE
                    WHEN 'LysisAssay' IN labs THEN 'LysisAssay'
                    WHEN 'BiofilmAssay' IN labs THEN 'BiofilmAssay'
                    WHEN 'EnzymeGene' IN labs THEN 'EnzymeGene'
                    ELSE labs[0]
                END AS object_type,
                coalesce(n.assay_id, n.id) AS object_id,
                properties(n) AS properties,
                [item IN reviews WHERE item.review_id IS NOT NULL] AS reviews,
                [item IN sources WHERE item.source_id IS NOT NULL] AS sources
            ORDER BY object_type, object_id
            """,
            batch_id=batch_id,
            supported_labels=sorted(S1_SUPPORTED_LABELS),
        )

    def _query_unlinked_lysis(self, batch_id: str) -> List[dict]:
        return self.query_runner(
            """
            MATCH (a:LysisAssay)
            WHERE NOT (a)-[:BELONGS_TO_BATCH]->(:ExperimentBatch)
            RETURN a.assay_id AS object_id
            ORDER BY a.assay_id
            LIMIT 100
            """
        )

    @staticmethod
    def _required_fields_for(object_type: str) -> List[str]:
        return {
            "EnzymeGene": [
                "id", "name", "gene_symbol", "enzyme_class", "target_polysaccharide",
            ],
            "BiofilmAssay": [
                "id", "control_type", "biofilm_formation_od",
                "biofilm_residual_od", "status",
            ],
            "LysisAssay": [
                "assay_id", "assay_type", "result", "evidence_level", "qc_status",
            ],
        }.get(object_type, [])

    def _build_source_references(self, record: dict) -> List[SourceReference]:
        references: List[SourceReference] = []
        for source in record.get("sources", []):
            references.append(
                SourceReference(
                    source_id=source["source_id"],
                    source_type=source.get("source_type") or "unknown",
                    source_version=source.get("source_version"),
                    object_id=record.get("object_id"),
                    trust_status="UNREVIEWED_SOURCE",
                    review_status=source.get("review_status"),
                )
            )
        return references

    def _validate_record(self, record: dict) -> List[ValidationFinding]:
        findings: List[ValidationFinding] = []
        object_type = record["object_type"]
        object_id = record.get("object_id") or ""
        properties = record.get("properties") or {}
        source_refs = self._build_source_references(record)

        for field_name in self._required_fields_for(object_type):
            value = properties.get(field_name)
            if value is None or value == "":
                findings.append(
                    ValidationFinding(
                        finding_id=self.finding_id_factory(),
                        rule_id=f"SCI-S1-REQUIRED-{object_type}-{field_name}",
                        object_type=object_type,
                        object_id=object_id,
                        field_or_relation=field_name,
                        severity=FindingSeverity.ERROR,
                        message=f"{object_type} 缺少页面明确要求的字段 {field_name}",
                        observed_value=value,
                        expected_condition="字段应有明确值",
                        source_references=source_refs,
                    )
                )

        if not source_refs:
            findings.append(
                ValidationFinding(
                    finding_id=self.finding_id_factory(),
                    rule_id="SCI-S1-SOURCE-REQUIRED",
                    object_type=object_type,
                    object_id=object_id,
                    field_or_relation="SourceArtifact",
                    severity=FindingSeverity.BLOCKING,
                    message="记录未关联可追溯来源",
                    observed_value=None,
                    expected_condition="记录应关联 SourceArtifact",
                )
            )

        valid_reviews = [r for r in record.get("reviews", []) if r.get("review_id")]
        if not valid_reviews:
            findings.append(
                ValidationFinding(
                    finding_id=self.finding_id_factory(),
                    rule_id="SCI-S1-REVIEW-MISSING",
                    object_type=object_type,
                    object_id=object_id,
                    field_or_relation="Review",
                    severity=FindingSeverity.WARNING,
                    message="记录尚无独立 Review 记录",
                    observed_value=None,
                    expected_condition="正式使用前应按业务规则审核",
                    source_references=source_refs,
                )
            )

        return findings

    def execute(
        self,
        payload: dict,
        context: ToolExecutionContext,
    ) -> ToolResult:
        self.validate_input(payload)
        batch_id = payload["experiment_batch_id"].strip()

        batch = self._query_batch(batch_id)
        if batch is None:
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                f"实验批次不存在: {batch_id}",
                correlation_id=context.correlation_id,
            )

        records = self._query_linked_records(batch_id)
        findings: List[ValidationFinding] = []
        for record in records:
            findings.extend(self._validate_record(record))

        unlinked_lysis = self._query_unlinked_lysis(batch_id)
        if unlinked_lysis:
            findings.append(
                ValidationFinding(
                    finding_id=self.finding_id_factory(),
                    rule_id="SCI-S1-LYSIS-BATCH-ASSOCIATION-UNAVAILABLE",
                    object_type="LysisAssay",
                    object_id="MULTIPLE",
                    field_or_relation="BELONGS_TO_BATCH",
                    severity=FindingSeverity.WARNING,
                    message=(
                        "发现未关联任何实验批次的 LysisAssay；"
                        "当前无法证明这些记录是否属于目标批次"
                    ),
                    observed_value={
                        "count": len(unlinked_lysis),
                        "sample_ids": [x["object_id"] for x in unlinked_lysis[:10]],
                    },
                    expected_condition="LysisAssay 应具备明确批次归属",
                )
            )

        severity_counts = {
            sev.value: 0 for sev in FindingSeverity
        }
        for f in findings:
            severity_counts[f.severity.value] += 1

        all_sources: List[SourceReference] = []
        seen = set()
        for record in records:
            for ref in self._build_source_references(record):
                key = (ref.source_id, ref.source_version)
                if key in seen:
                    continue
                seen.add(key)
                all_sources.append(ref)

        report = {
            "scenario_id": "SCI-S1-BATCH-COMPLETENESS",
            "batch": batch,
            "checked_record_count": len(records),
            "record_counts": {
                label: sum(1 for r in records if r["object_type"] == label)
                for label in sorted(S1_SUPPORTED_LABELS)
            },
            "finding_counts": severity_counts,
            "findings": [f.to_dict() for f in findings],
            "limitations": [
                "当前 LysisAssay 页面未建立 BELONGS_TO_BATCH，"
                "无法将全局未挂载记录归属于当前批次。",
                "本检查只使用当前代码中已明确的字段与关系，不推断未确认规则。",
                "检查结果不修改实验数据，也不表示科学或临床结论。",
            ],
        }

        status = (
            "blocked"
            if severity_counts[FindingSeverity.BLOCKING.value] > 0
            else "completed_with_warnings"
            if (
                severity_counts[FindingSeverity.ERROR.value] > 0
                or severity_counts[FindingSeverity.WARNING.value] > 0
            )
            else "completed"
        )

        return ToolResult(
            status=status,
            data=report,
            artifact_type="missing_data_report",
            source_references=all_sources,
            warnings=report["limitations"],
            metadata={
                "batch_id": batch_id,
                "schema_version": context.schema_version,
                "rule_set": "SCI-S1-CODE-VERIFIED-0.1",
            },
        )