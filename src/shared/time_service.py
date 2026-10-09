# src/shared/time_service.py
"""
PRD 14.3 时间语义工具

- 所有主对象默认带 valid_from / valid_to
- valid_from 默认 = 创建时间
- valid_to = null 表示"当前有效"
- 支持 as_of_date 查询：某时刻哪些对象有效

用法：
    from src.shared.time_service import (
        set_valid_from, close_validity, query_as_of, backfill_valid_from
    )
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


TIME_TRACKED_LABELS = {
    "Organization": "organization_id",
    "DevelopmentProgram": "program_id",
    "IntelligenceEvent": "event_id",
    "EngineeringStrategy": "strategy_id",
    "EngineeredPhageConstruct": "construct_id",
    "TechnicalClaim": "claim_id",
    "TechnicalResult": "result_id",
    "PatentFamily": "patent_family_id",
    "ClinicalTrial": "trial_id",
    "IntelligenceProduct": "brief_id",
    "DecisionRecord": "decision_id",
    "TechnologyAssessment": "technology_assessment_id",
    "CompetitorAssessment": "assessment_id",
}


def _today_iso() -> str:
    return datetime.now().isoformat()


def set_valid_from(
    driver: Driver,
    label: str,
    node_id: str,
    valid_from: Optional[str] = None,
    actor_id: str = "system",
) -> bool:
    """显式设置 valid_from（默认今天）。"""
    if label not in TIME_TRACKED_LABELS:
        raise ValueError(f"label 必须是 {sorted(TIME_TRACKED_LABELS)} 之一")
    id_prop = TIME_TRACKED_LABELS[label]
    vf = valid_from or _today_iso()

    with driver.session() as s:
        r = s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.valid_from = $vf,
                n.updated_at = datetime()
            RETURN n.{id_prop} AS oid
        """, oid=node_id, vf=vf).single()
        if not r:
            raise ValueError(f"{label} {node_id} 不存在")

    write_audit_event(
        driver, action_type="UPDATE", object_type=label, object_id=node_id,
        actor_id=actor_id, delta={"valid_from": vf},
        reason=f"设置 valid_from = {vf}",
    )
    return True


def close_validity(
    driver: Driver,
    label: str,
    node_id: str,
    valid_to: Optional[str] = None,
    actor_id: str = "system",
) -> bool:
    """关闭有效期（valid_to = now）。"""
    if label not in TIME_TRACKED_LABELS:
        raise ValueError(f"label 必须是 {sorted(TIME_TRACKED_LABELS)} 之一")
    id_prop = TIME_TRACKED_LABELS[label]
    vt = valid_to or _today_iso()

    with driver.session() as s:
        r = s.run(f"""
            MATCH (n:{label} {{`{id_prop}`: $oid}})
            SET n.valid_to = $vt,
                n.updated_at = datetime()
            RETURN n.{id_prop} AS oid
        """, oid=node_id, vt=vt).single()
        if not r:
            raise ValueError(f"{label} {node_id} 不存在")

    write_audit_event(
        driver, action_type="UPDATE", object_type=label, object_id=node_id,
        actor_id=actor_id, delta={"valid_to": vt},
        reason=f"设置 valid_to = {vt}",
    )
    return True


def query_as_of(
    driver: Driver,
    label: str,
    as_of: str,
    limit: int = 500,
) -> List[Dict]:
    """
    查询某时刻有效的对象。
    判定：valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of)
    """
    if label not in TIME_TRACKED_LABELS:
        raise ValueError(f"label 必须是 {sorted(TIME_TRACKED_LABELS)} 之一")
    id_prop = TIME_TRACKED_LABELS[label]

    with driver.session() as s:
        rows = list(s.run(f"""
            MATCH (n:{label})
            WHERE (n.valid_from IS NULL OR n.valid_from <= $as_of)
              AND (n.valid_to IS NULL OR n.valid_to > $as_of)
            RETURN n.{id_prop} AS id, n.valid_from AS valid_from,
                   n.valid_to AS valid_to
            LIMIT $limit
        """, as_of=as_of, limit=limit))
    return [dict(r) for r in rows]


def backfill_valid_from(
    driver: Driver,
    label: Optional[str] = None,
    actor_id: str = "time_backfill",
) -> Dict:
    """
    给历史数据补 valid_from（如果为空）。
    默认所有 TIME_TRACKED_LABELS。
    """
    labels = [label] if label else list(TIME_TRACKED_LABELS.keys())
    result = {"processed": 0, "updated": 0, "by_label": {}}

    with driver.session() as s:
        for lb in labels:
            id_prop = TIME_TRACKED_LABELS[lb]
            r = s.run(f"""
                MATCH (n:{lb})
                WHERE n.valid_from IS NULL
                SET n.valid_from = COALESCE(
                    n.created_at,
                    n.discovered_at,
                    n.assessed_at,
                    datetime()
                )
                RETURN count(n) AS c
            """).single()
            c = r["c"] if r else 0
            result["by_label"][lb] = c
            result["updated"] += c

    write_audit_event(
        driver, action_type="MIGRATION", object_type="TimeSemantics",
        object_id="backfill_valid_from", actor_id=actor_id,
        delta=result, reason=f"回填 valid_from：{result['updated']} 条",
    )
    return result


def time_coverage_report(driver: Driver) -> Dict:
    """统计各 label 的 valid_from 覆盖率"""
    with driver.session() as s:
        report = {}
        for lb, id_prop in TIME_TRACKED_LABELS.items():
            total = s.run(f"MATCH (n:{lb}) RETURN count(n) AS c").single()["c"]
            covered = s.run(
                f"MATCH (n:{lb}) WHERE n.valid_from IS NOT NULL RETURN count(n) AS c"
            ).single()["c"]
            report[lb] = {
                "total": total,
                "covered": covered,
                "coverage": round(covered / total * 100, 1) if total else 0,
            }
    return report