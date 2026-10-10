# src/shared/utils.py
"""
通用工具函数。

包含两部分：
    Part 1: 原 utils.py 的工具函数（安全 JSON 序列化、证据包打印）
    Part 2: 从 time_service.py 合并而来的时间语义工具（PRD 14.3）

时间语义约定：
    - 对象通过 valid_from / valid_to 表达生效区间
    - valid_to = null 表示当前仍有效
    - query_as_of 用 as_of 时间做区间查询
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


def safe_json_dumps(obj, indent=2):
    """
    安全的 JSON 序列化，处理 datetime 等类型。

    - datetime → isoformat 字符串
    - 其他不可序列化类型 → str()
    """
    def default_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)
    return json.dumps(obj, ensure_ascii=False, indent=indent, default=default_serializer)


def print_evidence_package(pkg: Dict):
    """
    在 Jupyter 中美化打印 Evidence Package。

    输出三块：Matching Evidence / Clinical Evidence / Explanation
    """
    from IPython.display import display, Markdown

    display(Markdown("## 🧬 Matching Evidence"))
    for item in pkg.get("matching_evidence", []):
        display(Markdown(f"- **{item.get('phage_name')}** (L{item.get('evidence_level')}): {item.get('infection_result')}, 概率 {item.get('infection_probability')}"))

    display(Markdown("## 📋 Clinical Evidence"))
    for item in pkg.get("clinical_evidence", []):
        display(Markdown(f"- **{item.get('case_id')}**: {item.get('phage_treatment')} → {item.get('clinical_outcome')}"))

    display(Markdown("## 💡 Explanation"))
    display(Markdown(pkg.get("explanation", "无解释")))


# ========================================================
# ★ 从 src/shared/time_service.py 合并而来
# PRD 14.3 时间语义工具
# ========================================================

# 需要做时间语义管理的 label → id 属性名
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
    """返回当前时间的 ISO 格式字符串。"""
    return datetime.now().isoformat()


def set_valid_from(
    driver: Driver,
    label: str,
    node_id: str,
    valid_from: Optional[str] = None,
    actor_id: str = "system",
) -> bool:
    """
    显式设置 valid_from（默认今天）。

    Args:
        label: 节点类型（必须在 TIME_TRACKED_LABELS 中）
        node_id: 节点 ID
        valid_from: ISO 时间字符串（默认当前时间）
        actor_id: 操作者

    Returns:
        bool: 成功返回 True
    """
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
    """
    关闭有效期（valid_to = now）。

    Args:
        label: 节点类型
        node_id: 节点 ID
        valid_to: ISO 时间字符串（默认当前时间）
        actor_id: 操作者

    Returns:
        bool: 成功返回 True
    """
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

    默认处理所有 TIME_TRACKED_LABELS；可传 label 只处理单一类型。

    Returns:
        Dict: {processed, updated, by_label}
    """
    labels = [label] if label else list(TIME_TRACKED_LABELS.keys())
    result = {"processed": 0, "updated": 0, "by_label": {}}

    with driver.session() as s:
        for lb in labels:
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
    """
    统计各 label 的 valid_from 覆盖率。

    Returns:
        Dict: {label: {total, covered, coverage(%)}}
    """
    with driver.session() as s:
        report = {}
        for lb, _id_prop in TIME_TRACKED_LABELS.items():
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