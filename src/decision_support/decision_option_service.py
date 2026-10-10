# src/decision_support/decision_option_service.py
"""
DecisionOption 服务（PRD 10.2）

关系：
    (DecisionOption)-[:OPTION_FOR]->(DecisionBrief | IntelligenceProduct)

v0.6 修复：同时支持 DecisionBrief 和 IntelligenceProduct 两种简报标签。
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

from neo4j import Driver

from src.shared.audit_service import write_audit_event


OPTION_TYPES = {"monitor", "evaluate", "partner", "deprioritize", "IP_review", "invest", "no_action"}
RISK_LEVELS = {"high", "medium", "low", "unknown"}


def generate_option_id() -> str:
    return f"CI:OPT:{uuid.uuid4().hex[:8].upper()}"


def _resolve_brief_label(session, brief_id: str) -> Optional[str]:
    """返回 'DecisionBrief' 或 'IntelligenceProduct'，找不到返回 None。"""
    r = session.run("""
        MATCH (b)
        WHERE (b:DecisionBrief AND b.brief_id = $bid)
           OR (b:IntelligenceProduct AND b.brief_id = $bid)
        RETURN labels(b)[0] AS label
        LIMIT 1
    """, bid=brief_id).single()
    return r["label"] if r else None


def create_decision_option(
    driver: Driver,
    brief_id: str,
    option_type: str,
    option_summary: str,
    pros: Optional[List[str]] = None,
    cons: Optional[List[str]] = None,
    risk_level: str = "medium",
    actor_id: str = "system",
) -> str:
    if option_type not in OPTION_TYPES:
        raise ValueError(f"option_type 必须是 {sorted(OPTION_TYPES)} 之一")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"risk_level 必须是 {sorted(RISK_LEVELS)} 之一")

    pros = pros or []
    cons = cons or []

    with driver.session() as s:
        brief_label = _resolve_brief_label(s, brief_id)
        if not brief_label:
            raise ValueError(
                f"简报 {brief_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct）"
            )

        option_id = generate_option_id()
        s.run(f"""
            MATCH (b:{brief_label} {{brief_id: $bid}})
            CREATE (o:DecisionOption {{
                option_id: $oid,
                option_type: $otype,
                option_summary: $summary,
                pros: $pros,
                cons: $cons,
                risk_level: $risk,
                review_status: 'pending',
                created_at: datetime(),
                updated_at: datetime()
            }})
            CREATE (o)-[:OPTION_FOR]->(b)
        """, bid=brief_id, oid=option_id, otype=option_type,
             summary=option_summary, pros=pros, cons=cons, risk=risk_level)

    write_audit_event(
        driver,
        action_type="CREATE",
        object_type="DecisionOption",
        object_id=option_id,
        actor_id=actor_id,
        delta={"brief_id": brief_id, "brief_label": brief_label,
               "option_type": option_type, "risk_level": risk_level},
        reason=f"创建决策选项: {option_summary[:60]}",
    )
    return option_id


def list_options_for_brief(driver: Driver, brief_id: str) -> List[Dict]:
    with driver.session() as s:
        rows = list(s.run("""
            MATCH (o:DecisionOption)-[:OPTION_FOR]->(b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN o.option_id AS option_id, o.option_type AS option_type,
                   o.option_summary AS option_summary,
                   o.pros AS pros, o.cons AS cons,
                   o.risk_level AS risk_level,
                   o.review_status AS review_status
            ORDER BY o.created_at
        """, bid=brief_id))
    return [dict(r) for r in rows]