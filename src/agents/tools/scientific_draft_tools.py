# src/agents/tools/scientific_draft_tools.py
"""科学域候选生成 Agent 工具（S2）。"""
from typing import Callable, List
from uuid import uuid4

from src.agents.core.errors import AgentError, AgentErrorCode
from src.agents.core.models import SourceReference
from src.agents.tools.base import AgentTool, ToolExecutionContext, ToolResult


class EvidencePackageDraftTool(AgentTool):
    tool_id = "scientific.draft_evidence_package"
    version = "0.1"
    domain = "scientific"
    risk_level = "R1"
    access_mode = "candidate_write"

    def __init__(
        self,
        query_runner: Callable[..., List[dict]],
    ) -> None:
        self.query_runner = query_runner

    def validate_input(self, payload: dict) -> None:
        phage_id = payload.get("phage_id")
        host_id = payload.get("host_strain_id")
        if not isinstance(phage_id, str) or not phage_id.strip():
            raise AgentError(AgentErrorCode.TOOL_INPUT_INVALID, "phage_id 不能为空")
        if not isinstance(host_id, str) or not host_id.strip():
            raise AgentError(AgentErrorCode.TOOL_INPUT_INVALID, "host_strain_id 不能为空")

    def _query_entities(self, phage_id: str, host_id: str):
        # 查询噬菌体和宿主
        phage = self.query_runner(
            "MATCH (p:Phage {phage_id: $pid}) RETURN p.phage_id AS id, p.name AS name LIMIT 1",
            pid=phage_id,
        )
        host = self.query_runner(
            "MATCH (h:HostStrain {host_strain_id: $hid}) RETURN h.host_strain_id AS id, h.name AS name LIMIT 1",
            hid=host_id,
        )
        return (phage[0] if phage else None, host[0] if host else None)

    def _query_assays_and_sources(self, phage_id: str, host_id: str):
        # 假设图谱中 LysisAssay 关联了 Phage 和 HostStrain（关系名请根据实际调整）
        # 这里同时去查关联的 SourceArtifact
        return self.query_runner(
            """
            MATCH (p:Phage {phage_id: $pid})
            MATCH (h:HostStrain {host_strain_id: $hid})
            OPTIONAL MATCH (a:LysisAssay)-[:TESTED_PHAGE]->(p)
            WHERE (a)-[:TESTED_HOST]->(h)
            OPTIONAL MATCH (a)-[:DERIVED_FROM]->(src:SourceArtifact)
            RETURN
                a.assay_id AS assay_id,
                a.assay_type AS assay_type,
                a.result AS result,
                a.evidence_level AS evidence_level,
                a.qc_status AS qc_status,
                collect(DISTINCT {
                    source_id: src.source_id,
                    source_type: src.source_type,
                    review_status: src.review_status
                }) AS sources
            LIMIT 200
            """,
            pid=phage_id,
            hid=host_id,
        )

    def execute(self, payload: dict, context: ToolExecutionContext) -> ToolResult:
        self.validate_input(payload)
        phage_id = payload["phage_id"].strip()
        host_id = payload["host_strain_id"].strip()

        phage, host = self._query_entities(phage_id, host_id)
        if not phage:
            raise AgentError(AgentErrorCode.TOOL_INPUT_INVALID, f"噬菌体不存在: {phage_id}", correlation_id=context.correlation_id)
        if not host:
            raise AgentError(AgentErrorCode.TOOL_INPUT_INVALID, f"宿主菌株不存在: {host_id}", correlation_id=context.correlation_id)

        records = self._query_assays_and_sources(phage_id, host_id)

        facts = []
        missing_evidence = []
        source_refs = []
        seen_sources = set()

        for r in records:
            # 如果没有 assay_id，说明二者没有实验记录
            if not r.get("assay_id"):
                continue
            
            # 提取来源
            valid_sources = [s for s in r.get("sources", []) if s.get("source_id")]
            for s in valid_sources:
                if s["source_id"] not in seen_sources:
                    seen_sources.add(s["source_id"])
                    source_refs.append(SourceReference(
                        source_id=s["source_id"], source_type=s.get("source_type") or "unknown",
                        object_id=r["assay_id"], trust_status="UNREVIEWED_SOURCE", review_status=s.get("review_status")
                    ))

            # 组装事实
            fact = {
                "assay_id": r["assay_id"],
                "assay_type": r.get("assay_type"),
                "result": r.get("result"),
                "evidence_level": r.get("evidence_level"),
                "qc_status": r.get("qc_status"),
                "sources": [s["source_id"] for s in valid_sources]
            }
            facts.append(fact)

            # 缺失项检查
            if not valid_sources:
                missing_evidence.append({"assay_id": r["assay_id"], "gap": "缺少 SourceArtifact 来源"})
            if r.get("qc_status") != "passed":
                missing_evidence.append({"assay_id": r["assay_id"], "gap": f"QC 状态非 passed (当前: {r.get('qc_status')})"})

        if not facts:
            missing_evidence.append({"object": "ALL", "gap": "未找到任何针对该组合的裂解实验记录"})

        # 组装最终草稿包
        report = {
            "scenario_id": "SCI-S2-EVIDENCE-PACKAGE-DRAFT",
            "title": f"证据包草稿: {phage['name']} 感染 {host['name']}",
            "subjects": {
                "phage": phage,
                "host_strain": host,
            },
            "experimental_facts": facts,
            "analysis_and_conclusions": [],  # 留空，Agent 不生成分析结论
            "missing_evidence": missing_evidence,
            "limitations": [
                "此证据包为受控 Agent 生成的草稿，未经过领域专家审核。",
                "系统仅提取了已知的关联记录，不推断未登记的交叉反应。",
                "不能作为临床有效性的直接证据。"
            ],
            "review_status": "draft",
        }

        warnings = []
        if missing_evidence:
            warnings.append(f"发现 {len(missing_evidence)} 项缺失证据")

        return ToolResult(
            status="completed_with_warnings" if warnings else "completed",
            data=report,
            artifact_type="draft_evidence_package",
            source_references=source_refs,
            warnings=warnings,
            metadata={"phage_id": phage_id, "host_strain_id": host_id, "aggregation_method": "deterministic_no_llm"},
        )