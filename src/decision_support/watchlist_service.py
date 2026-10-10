# src/decision_support/watchlist_service.py
"""WatchlistItem 服务 —— 符合 PRD 5.4"""
import uuid
from datetime import datetime
from typing import Optional, List, Dict

from neo4j import Driver

from src.shared.audit_service import write_audit_event


TARGET_TYPES = {
    "organization":         ("Organization",         "organization_id"),
    "development_program":  ("DevelopmentProgram",   "program_id"),
    "engineering_strategy": ("EngineeringStrategy",  "strategy_id"),
    "pathogen":             ("Pathogen",             "pathogen_id"),
    "patent_family":        ("PatentFamily",         "patent_family_id"),
    "clinical_trial":       ("ClinicalTrial",        "trial_id"),
}

WATCHLIST_STATUSES = {"active", "archived", "closed"}


def generate_watchlist_item_id() -> str:
    return f"CI:WATCH:{uuid.uuid4().hex[:8].upper()}"


def create_watchlist_item(
    driver: Driver,
    target_type: str,
    target_id: str,
    reason: str,
    priority: str = "medium",
    owner_id: str = "analyst",
    review_date: Optional[str] = None,
    derived_from_brief_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建关注项。

    v0.6 修复：derived_from_brief_id 支持 DecisionBrief 和 IntelligenceProduct 双标签。
    """
    if target_type not in TARGET_TYPES:
        raise ValueError(f"target_type 必须是 {TARGET_TYPES.keys()} 之一")

    label, id_prop = TARGET_TYPES[target_type]
    watchlist_item_id = generate_watchlist_item_id()

    with driver.session() as session:
        check = session.run(
            f"MATCH (t:{label} {{`{id_prop}`: $tid}}) RETURN t LIMIT 1",
            tid=target_id,
        ).single()
        if not check:
            raise ValueError(f"目标 {target_type} {target_id} 不存在")

        session.run(
            """
            CREATE (wi:WatchlistItem {
                watchlist_item_id: $wid,
                target_type: $ttype,
                target_id: $tid,
                reason: $reason,
                priority: $priority,
                owner_id: $owner,
                review_date: $review_date,
                status: 'active',
                created_at: datetime(),
                updated_at: datetime()
            })
            """,
            wid=watchlist_item_id,
            ttype=target_type,
            tid=target_id,
            reason=reason,
            priority=priority,
            owner=owner_id,
            review_date=review_date,
        )

        session.run(
            f"""
            MATCH (wi:WatchlistItem {{watchlist_item_id: $wid}})
            MATCH (t:{label} {{`{id_prop}`: $tid}})
            MERGE (wi)-[:WATCHES]->(t)
            """,
            wid=watchlist_item_id,
            tid=target_id,
        )

        # v0.6：DERIVED_FROM 支持双标签
        if derived_from_brief_id:
            session.run(
                """
                MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
                MATCH (b)
                WHERE (b:DecisionBrief AND b.brief_id = $bid)
                   OR (b:IntelligenceProduct AND b.brief_id = $bid)
                MERGE (wi)-[:DERIVED_FROM]->(b)
                """,
                wid=watchlist_item_id,
                bid=derived_from_brief_id,
            )

        write_audit_event(
            driver,
            action_type="CREATE",
            object_type="WatchlistItem",
            object_id=watchlist_item_id,
            actor_id=actor_id,
            delta={
                "target_type": target_type,
                "target_id": target_id,
                "priority": priority,
            },
            reason=f"加入关注项: {reason[:60]}",
        )

    return watchlist_item_id


def get_watchlist_item(driver: Driver, watchlist_item_id: str) -> Optional[Dict]:
    with driver.session() as session:
        r = session.run(
            """
            MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
            OPTIONAL MATCH (wi)-[:WATCHES]->(t)
            OPTIONAL MATCH (wi)-[:DERIVED_FROM]->(b)
            WHERE b IS NULL OR b:DecisionBrief OR b:IntelligenceProduct
            RETURN wi,
                   labels(t)[0] AS target_label,
                   t AS target_node,
                   b.brief_id AS brief_id
            """,
            wid=watchlist_item_id,
        ).single()
        if not r:
            return None
        data = dict(r["wi"])
        data["target_label"] = r["target_label"]
        data["target_node"] = dict(r["target_node"]) if r["target_node"] else None
        data["derived_from_brief_id"] = r["brief_id"]
        return data


def list_watchlist_items(
    driver: Driver,
    status: Optional[str] = None,
    target_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    filters = []
    params: Dict = {"limit": limit}
    if status:
        filters.append("wi.status = $status")
        params["status"] = status
    if target_type:
        filters.append("wi.target_type = $ttype")
        params["ttype"] = target_type
    where = " AND ".join(filters) if filters else "true"

    with driver.session() as session:
        r = session.run(
            f"""
            MATCH (wi:WatchlistItem)
            WHERE {where}
            OPTIONAL MATCH (wi)-[:WATCHES]->(t)
            RETURN wi.watchlist_item_id AS watchlist_item_id,
                   wi.target_type AS target_type,
                   wi.target_id AS target_id,
                   wi.reason AS reason,
                   wi.priority AS priority,
                   wi.owner_id AS owner_id,
                   wi.review_date AS review_date,
                   wi.status AS status,
                   wi.created_at AS created_at,
                   labels(t)[0] AS target_label,
                   coalesce(t.canonical_name, t.public_name, t.species, t.title, t.strategy_type, t.nct_id) AS target_name
            ORDER BY wi.priority DESC, wi.created_at DESC
            LIMIT $limit
            """,
            **params,
        )
        return [dict(rec) for rec in r]


def close_watchlist_item(
    driver: Driver,
    watchlist_item_id: str,
    reason: str = "",
    actor_id: str = "system",
) -> bool:
    with driver.session() as session:
        check = session.run(
            "MATCH (wi:WatchlistItem {watchlist_item_id: $wid}) RETURN wi",
            wid=watchlist_item_id,
        ).single()
        if not check:
            raise ValueError(f"关注项 {watchlist_item_id} 不存在")

        session.run(
            """
            MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
            SET wi.status = 'closed', wi.updated_at = datetime()
            """,
            wid=watchlist_item_id,
        )

        write_audit_event(
            driver,
            action_type="STATUS_CHANGE",
            object_type="WatchlistItem",
            object_id=watchlist_item_id,
            actor_id=actor_id,
            delta={"status": {"before": "active", "after": "closed"}},
            reason=reason or f"关闭关注项 {watchlist_item_id}",
        )
        return True