# src/agents/tools/intelligence_read_tools.py
"""情报域只读 Agent 工具。"""
from datetime import date
from typing import Callable, List

from src.agents.core.errors import AgentError, AgentErrorCode
from src.agents.core.models import SourceReference
from src.agents.tools.base import AgentTool, ToolExecutionContext, ToolResult


_REVIEWED_STATUSES = {"reviewed", "approved", "confirmed"}
_UNREVIEWED_STATUSES = {"", "pending", "unreviewed", "unverified"}
_DISPUTED_STATUSES = {"disputed", "rejected"}


def _normalize_status(value) -> str:
    return str(value or "").strip().lower()


def _parse_iso_date(value: str, *, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AgentError(
            AgentErrorCode.TOOL_INPUT_INVALID,
            f"{field_name} 必须是 YYYY-MM-DD",
        ) from exc


class PeriodicIntelligenceBriefTool(AgentTool):
    tool_id = "intelligence.periodic_brief"
    version = "0.1"
    domain = "intelligence"
    risk_level = "R1"
    access_mode = "read"

    def __init__(self, *, query_runner: Callable[..., List[dict]]) -> None:
        self.query_runner = query_runner

    def validate_input(self, payload: dict) -> None:
        pathogen_id = payload.get("pathogen_id")
        if not isinstance(pathogen_id, str) or not pathogen_id.strip():
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID, "pathogen_id 不能为空"
            )
        start = _parse_iso_date(payload.get("date_from") or "", field_name="date_from")
        end = _parse_iso_date(payload.get("date_to") or "", field_name="date_to")
        if start > end:
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                "date_from 不能晚于 date_to",
            )

    def _query_pathogen(self, pathogen_id: str):
        rows = self.query_runner(
            """
            MATCH (p:Pathogen {pathogen_id: $pathogen_id})
            RETURN p.pathogen_id AS pathogen_id, p.species AS species
            LIMIT 1
            """,
            pathogen_id=pathogen_id,
        )
        return rows[0] if rows else None

    def _query_programs_and_events(self, pathogen_id: str) -> List[dict]:
        return self.query_runner(
            """
            MATCH (p:Pathogen {pathogen_id: $pathogen_id})
            MATCH (d:DevelopmentProgram)-[:TARGETS_PATHOGEN]->(p)
            OPTIONAL MATCH (e:IntelligenceEvent)-[:AFFECTS]->(d)
            OPTIONAL MATCH (e)-[:INVOLVES]->(o:Organization)
            OPTIONAL MATCH (e)-[:HAS_SOURCE]->(s:SourceArtifact)
            RETURN
                d.program_id AS program_id,
                d.canonical_name AS program_name,
                d.development_stage AS development_stage,
                d.program_status AS program_status,
                e.event_id AS event_id,
                e.title AS event_title,
                e.event_type AS event_type,
                e.event_date AS event_date,
                e.factual_summary AS factual_summary,
                e.review_status AS event_review_status,
                o.organization_id AS organization_id,
                o.canonical_name AS organization_name,
                s.source_id AS source_id,
                s.source_type AS source_type,
                s.title AS source_title,
                s.url AS source_url,
                s.published_date AS source_published_date,
                s.review_status AS source_review_status
            ORDER BY e.event_date DESC, d.canonical_name
            LIMIT 500
            """,
            pathogen_id=pathogen_id,
        )

    @staticmethod
    def _date_in_range(value, *, date_from: date, date_to: date) -> bool:
        if value is None or value == "":
            return False
        try:
            current = date.fromisoformat(str(value)[:10])
        except ValueError:
            return False
        return date_from <= current <= date_to

    @staticmethod
    def _source_ref(row: dict):
        source_id = row.get("source_id")
        if not source_id:
            return None
        normalized = _normalize_status(row.get("source_review_status"))
        return SourceReference(
            source_id=source_id,
            source_type=row.get("source_type") or "unknown",
            source_version=None,
            object_id=row.get("event_id"),
            locator=row.get("source_url"),
            trust_status=(
                "REVIEWED_SOURCE"
                if normalized in _REVIEWED_STATUSES
                else "UNREVIEWED_SOURCE"
            ),
            review_status=row.get("source_review_status"),
        )

    @staticmethod
    def _event_record(event: dict) -> dict:
        return {
            "event_id": event["event_id"],
            "title": event.get("title"),
            "event_type": event.get("event_type"),
            "event_date": event.get("event_date"),
            "factual_summary": event.get("factual_summary"),
            "review_status": event.get("review_status"),
            "organization_id": event.get("organization_id"),
            "organization_name": event.get("organization_name"),
            "program_ids": sorted(event.get("program_ids", [])),
            "source_ids": sorted(event.get("source_ids", [])),
        }

    def execute(self, payload: dict, context: ToolExecutionContext) -> ToolResult:
        self.validate_input(payload)
        pathogen_id = payload["pathogen_id"].strip()
        start = _parse_iso_date(payload["date_from"], field_name="date_from")
        end = _parse_iso_date(payload["date_to"], field_name="date_to")

        pathogen = self._query_pathogen(pathogen_id)
        if pathogen is None:
            raise AgentError(
                AgentErrorCode.TOOL_INPUT_INVALID,
                f"Pathogen 不存在：{pathogen_id}",
                correlation_id=context.correlation_id,
            )

        rows = self._query_programs_and_events(pathogen_id)

        programs = {}
        events = {}
        source_refs = {}
        data_gaps: List[dict] = []

        for row in rows:
            program_id = row.get("program_id")
            if program_id:
                programs.setdefault(program_id, {
                    "program_id": program_id,
                    "name": row.get("program_name"),
                    "development_stage": row.get("development_stage"),
                    "program_status": row.get("program_status"),
                })

            event_id = row.get("event_id")
            if not event_id:
                continue
            if not self._date_in_range(
                row.get("event_date"), date_from=start, date_to=end
            ):
                continue

            event = events.setdefault(event_id, {
                "event_id": event_id,
                "title": row.get("event_title"),
                "event_type": row.get("event_type"),
                "event_date": str(row.get("event_date") or "")[:10],
                "factual_summary": row.get("factual_summary"),
                "review_status": row.get("event_review_status"),
                "organization_id": row.get("organization_id"),
                "organization_name": row.get("organization_name"),
                "program_ids": set(),
                "source_ids": set(),
            })
            if program_id:
                event["program_ids"].add(program_id)

            reference = self._source_ref(row)
            if reference is not None:
                event["source_ids"].add(reference.source_id)
                source_refs.setdefault(reference.source_id, reference)

        fact_events, unreviewed_events, disputed_events = [], [], []
        for event in events.values():
            normalized = _normalize_status(event.get("review_status"))
            record = self._event_record(event)
            if normalized in _REVIEWED_STATUSES:
                fact_events.append(record)
            elif normalized in _DISPUTED_STATUSES:
                disputed_events.append(record)
            else:
                unreviewed_events.append(record)

            if not record["source_ids"]:
                data_gaps.append({
                    "object_type": "IntelligenceEvent",
                    "object_id": record["event_id"],
                    "gap": "缺少 SourceArtifact",
                })

        for program in programs.values():
            related = [
                e for e in events.values()
                if program["program_id"] in e["program_ids"]
            ]
            if not related:
                data_gaps.append({
                    "object_type": "DevelopmentProgram",
                    "object_id": program["program_id"],
                    "gap": "时间范围内没有关联情报事件",
                })

        unique_sources = list(source_refs.values())
        source_tiers = {}
        for reference in unique_sources:
            row = next((r for r in rows if r.get("source_id") == reference.source_id), {})
            tier = row.get("credibility_tier") or "unknown"
            source_tiers[tier] = source_tiers.get(tier, 0) + 1

        all_event_dates = sorted(
            [e["event_date"] for e in (fact_events + unreviewed_events + disputed_events)
             if e.get("event_date")],
            reverse=True,
        )

        report = {
            "scenario_id": "INT-I1-PERIODIC-BRIEF-DRAFT",
            "title": f"{pathogen.get('species') or pathogen_id} 周期情报简报草稿",
            "scope": {
                "pathogen_id": pathogen_id,
                "pathogen_species": pathogen.get("species"),
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
            },
            "facts": sorted(fact_events, key=lambda x: x["event_date"], reverse=True),
            "unreviewed_items": sorted(
                unreviewed_events, key=lambda x: x["event_date"], reverse=True
            ),
            "disputed_items": sorted(
                disputed_events, key=lambda x: x["event_date"], reverse=True
            ),
            "programs": sorted(
                programs.values(), key=lambda x: x.get("name") or ""
            ),
            "source_summary": {
                "unique_source_count": len(unique_sources),
                "by_credibility_tier": source_tiers,
            },
            "rule_based_summary": {
                "program_count": len(programs),
                "reviewed_event_count": len(fact_events),
                "unreviewed_event_count": len(unreviewed_events),
                "disputed_event_count": len(disputed_events),
                "latest_event_date": all_event_dates[0] if all_event_dates else None,
            },
            "data_gaps": data_gaps,
            "limitations": [
                "简报只覆盖通过 DevelopmentProgram → Pathogen 和 "
                "IntelligenceEvent → DevelopmentProgram 路径关联的数据。",
                "reviewed 与 approved 被视为已审核状态，但原始状态值仍保留。",
                "未审核和争议事件不进入 facts。",
                "来源可信度仅反映来源渠道，不代表内容正确。",
                "该产物为 Agent 草稿，未经人工审核不得发布。",
            ],
            "review_status": "draft",
        }

        warnings = []
        if unreviewed_events:
            warnings.append(f"存在 {len(unreviewed_events)} 条未审核事件")
        if disputed_events:
            warnings.append(f"存在 {len(disputed_events)} 条争议或拒绝事件")
        if data_gaps:
            warnings.append(f"存在 {len(data_gaps)} 项数据缺口")

        return ToolResult(
            status="completed_with_warnings" if warnings else "completed",
            data=report,
            artifact_type="intelligence_brief_draft",
            source_references=unique_sources,
            warnings=warnings,
            metadata={
                "pathogen_id": pathogen_id,
                "date_from": start.isoformat(),
                "date_to": end.isoformat(),
                "query_path": (
                    "Pathogen<-TARGETS_PATHOGEN-DevelopmentProgram"
                    "<-AFFECTS-IntelligenceEvent"
                ),
                "aggregation_method": "deterministic_no_llm",
            },
        )