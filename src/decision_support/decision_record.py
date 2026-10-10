# src/decision_support/decision_record.py
"""
DecisionRecord / DecisionOption / WatchlistItem
合并服务（PRD 10.3 / 10.2 / 5.4）

包含三个部分：
    Part 1: DecisionRecord  —— 决策记录
    Part 2: DecisionOption  —— 决策选项
    Part 3: WatchlistItem   —— 关注项
"""

# ==================================================================
# Part 1: DecisionRecord (原 decision_record.py)
# ==================================================================
import uuid
from typing import Optional, Dict, List
from neo4j import Driver
from src.shared.audit_service import write_audit_event


def generate_decision_id() -> str:
    """生成决策记录 ID（格式：CI:DEC:XXXXXXXX）。"""
    return f"CI:DEC:{uuid.uuid4().hex[:8].upper()}"


def create_decision_record(
    driver: Driver, brief_id: str, decision_type: str,
    decision_summary: str, rationale: str, decision_owner: str,
    review_date: Optional[str] = None,
    affected_program_id: Optional[str] = None,
    actor_id: str = "system",
) -> str:
    """
    创建决策记录。

    - 支持的简报类型：DecisionBrief 或 IntelligenceProduct（二者均可作为 BASED_ON 对象）
    - 可选关联内部研发项目（AFFECTS_INTERNAL_PROGRAM）

    Args:
        brief_id: 决策基于的简报
        decision_type: 决策类型
        decision_summary: 决策摘要
        rationale: 决策理由
        decision_owner: 决策者
        review_date: 复盘日期
        affected_program_id: 受影响的内部研发项目（可选）
        actor_id: 操作者

    Returns:
        str: decision_id

    Raises:
        ValueError: 简报不存在
    """
    decision_id = generate_decision_id()

    with driver.session() as session:
        # 校验简报存在，并获取其 label（用于后续动态匹配）
        brief_check = session.run("""
            MATCH (b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN b, labels(b) AS labels LIMIT 1
        """, bid=brief_id).single()
        if not brief_check:
            raise ValueError(f"简报 {brief_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct）")
        _brief_label = brief_check["labels"][0]

        # 创建决策记录节点
        session.run("""
            CREATE (dr:DecisionRecord {
                decision_id: $decision_id, decision_type: $decision_type,
                decision_summary: $summary, rationale: $rationale,
                decision_owner: $owner, review_date: $review_date,
                outcome_status: 'pending',
                decided_at: datetime(), created_at: datetime(), updated_at: datetime()
            })
        """, decision_id=decision_id, decision_type=decision_type,
             summary=decision_summary, rationale=rationale,
             owner=decision_owner, review_date=review_date)

        # BASED_ON 关系（根据简报类型动态匹配 label）
        session.run(f"""
            MATCH (dr:DecisionRecord {{decision_id: $did}})
            MATCH (b:{_brief_label} {{brief_id: $bid}})
            CREATE (dr)-[:BASED_ON]->(b)
        """, did=decision_id, bid=brief_id)

        # 可选：关联内部研发项目
        if affected_program_id:
            prog_check = session.run(
                "MATCH (d:DevelopmentProgram {program_id: $pid}) RETURN d",
                pid=affected_program_id).single()
            if prog_check:
                session.run("""
                    MATCH (dr:DecisionRecord {decision_id: $did})
                    MATCH (d:DevelopmentProgram {program_id: $pid})
                    CREATE (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d)
                """, did=decision_id, pid=affected_program_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="DecisionRecord", object_id=decision_id,
            actor_id=actor_id,
            delta={"decision_type": decision_type, "decision_owner": decision_owner,
                   "brief_id": brief_id, "brief_label": _brief_label},
            reason=rationale,
        )
        return decision_id


def update_decision_outcome(driver, decision_id, outcome_status, actor_id="system"):
    """
    更新决策结果状态。

    合法值：pending / successful / unsuccessful / mixed
    """
    valid_outcomes = ["pending", "successful", "unsuccessful", "mixed"]
    if outcome_status not in valid_outcomes:
        raise ValueError(f"结果状态必须是 {valid_outcomes} 之一")

    with driver.session() as session:
        check = session.run(
            "MATCH (dr:DecisionRecord {decision_id: $did}) RETURN dr",
            did=decision_id).single()
        if not check:
            raise ValueError(f"决策 {decision_id} 不存在")
        session.run("""
            MATCH (dr:DecisionRecord {decision_id: $did})
            SET dr.outcome_status = $status, dr.updated_at = datetime()
        """, did=decision_id, status=outcome_status)
        write_audit_event(
            driver, action_type="STATUS_CHANGE",
            object_type="DecisionRecord", object_id=decision_id,
            actor_id=actor_id, delta={"outcome_status": outcome_status},
            reason=f"决策结果更新为 {outcome_status}",
        )
        return True


def get_decision_record(driver, decision_id):
    """
    按 ID 查询决策记录，附带 BASED_ON 简报信息与受影响的内部项目。
    """
    with driver.session() as session:
        result = session.run("""
            MATCH (dr:DecisionRecord {decision_id: $did})
            OPTIONAL MATCH (dr)-[:BASED_ON]->(b)
            WHERE b:DecisionBrief OR b:IntelligenceProduct
            OPTIONAL MATCH (dr)-[:AFFECTS_INTERNAL_PROGRAM]->(d:DevelopmentProgram)
            RETURN dr, b.brief_id AS brief_id, b.title AS brief_title,
                   d.program_id AS affected_program_id,
                   d.canonical_name AS affected_program_name
        """, did=decision_id).single()
        if not result:
            return None
        data = dict(result["dr"])
        data["brief_id"] = result.get("brief_id")
        data["brief_title"] = result.get("brief_title")
        data["affected_program_id"] = result.get("affected_program_id")
        data["affected_program_name"] = result.get("affected_program_name")
        return data


def get_decisions_by_brief(driver, brief_id):
    """查询基于某简报的所有决策记录，按决策时间倒序。"""
    with driver.session() as session:
        result = session.run("""
            MATCH (dr:DecisionRecord)-[:BASED_ON]->(b)
            WHERE (b:DecisionBrief AND b.brief_id = $bid)
               OR (b:IntelligenceProduct AND b.brief_id = $bid)
            RETURN dr ORDER BY dr.decided_at DESC
        """, bid=brief_id)
        return [dict(record["dr"]) for record in result]


# ==================================================================
# Part 2: DecisionOption (原 decision_option_service.py)
# ==================================================================

# 受控词表：决策选项类型
OPTION_TYPES = {"monitor", "evaluate", "partner", "deprioritize",
                "IP_review", "invest", "no_action"}
# 受控词表：风险级别
RISK_LEVELS = {"high", "medium", "low", "unknown"}


def generate_option_id() -> str:
    """生成决策选项 ID（格式：CI:OPT:XXXXXXXX）。"""
    return f"CI:OPT:{uuid.uuid4().hex[:8].upper()}"


def _resolve_brief_label(session, brief_id):
    """
    内部函数：识别 brief_id 对应的 label（DecisionBrief 或 IntelligenceProduct）。
    用于后续动态拼接 Cypher。
    """
    r = session.run("""
        MATCH (b)
        WHERE (b:DecisionBrief AND b.brief_id = $bid)
           OR (b:IntelligenceProduct AND b.brief_id = $bid)
        RETURN labels(b)[0] AS label LIMIT 1
    """, bid=brief_id).single()
    return r["label"] if r else None


def create_decision_option(driver, brief_id, option_type, option_summary,
                           pros=None, cons=None, risk_level="medium",
                           actor_id="system"):
    """
    创建决策选项，建立 OPTION_FOR 关系。

    Args:
        brief_id: 所属简报
        option_type: monitor / evaluate / partner / deprioritize / IP_review / invest / no_action
        option_summary: 选项摘要
        pros / cons: 优点 / 缺点列表
        risk_level: high / medium / low / unknown
        actor_id: 操作者

    Returns:
        str: option_id
    """
    if option_type not in OPTION_TYPES:
        raise ValueError(f"option_type 必须是 {sorted(OPTION_TYPES)} 之一")
    if risk_level not in RISK_LEVELS:
        raise ValueError(f"risk_level 必须是 {sorted(RISK_LEVELS)} 之一")

    pros = pros or []
    cons = cons or []

    with driver.session() as s:
        brief_label = _resolve_brief_label(s, brief_id)
        if not brief_label:
            raise ValueError(f"简报 {brief_id} 不存在（既不是 DecisionBrief 也不是 IntelligenceProduct）")
        option_id = generate_option_id()
        s.run(f"""
            MATCH (b:{brief_label} {{brief_id: $bid}})
            CREATE (o:DecisionOption {{
                option_id: $oid, option_type: $otype,
                option_summary: $summary, pros: $pros, cons: $cons,
                risk_level: $risk, review_status: 'pending',
                created_at: datetime(), updated_at: datetime()
            }})
            CREATE (o)-[:OPTION_FOR]->(b)
        """, bid=brief_id, oid=option_id, otype=option_type,
             summary=option_summary, pros=pros, cons=cons, risk=risk_level)

    write_audit_event(
        driver, action_type="CREATE",
        object_type="DecisionOption", object_id=option_id,
        actor_id=actor_id,
        delta={"brief_id": brief_id, "brief_label": brief_label,
               "option_type": option_type, "risk_level": risk_level},
        reason=f"创建决策选项: {option_summary[:60]}",
    )
    return option_id


def list_options_for_brief(driver, brief_id):
    """列出某简报的所有决策选项。"""
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


# ==================================================================
# Part 3: WatchlistItem (原 watchlist_service.py)
# ==================================================================
from datetime import datetime

# target_type → (Neo4j label, id 属性名)
TARGET_TYPES = {
    "organization":         ("Organization",         "organization_id"),
    "development_program":  ("DevelopmentProgram",   "program_id"),
    "engineering_strategy": ("EngineeringStrategy",  "strategy_id"),
    "pathogen":             ("Pathogen",             "pathogen_id"),
    "patent_family":        ("PatentFamily",         "patent_family_id"),
    "clinical_trial":       ("ClinicalTrial",        "trial_id"),
}
# 受控词表：关注项状态
WATCHLIST_STATUSES = {"active", "archived", "closed"}


def generate_watchlist_item_id() -> str:
    """生成关注项 ID（格式：CI:WATCH:XXXXXXXX）。"""
    return f"CI:WATCH:{uuid.uuid4().hex[:8].upper()}"


def create_watchlist_item(driver, target_type, target_id, reason,
                          priority="medium", owner_id="analyst",
                          review_date=None, derived_from_brief_id=None,
                          actor_id="system"):
    """
    创建关注项。

    - 校验目标对象存在
    - 建立 WATCHES 关系
    - 可选：DERIVED_FROM 关联到某简报

    Args:
        target_type: organization / development_program / engineering_strategy /
                     pathogen / patent_family / clinical_trial
        target_id: 目标对象 ID
        reason: 关注原因
        priority: 优先级
        owner_id: 负责人
        review_date: 复盘日期
        derived_from_brief_id: 来源简报（可选）
        actor_id: 操作者

    Returns:
        str: watchlist_item_id
    """
    if target_type not in TARGET_TYPES:
        raise ValueError(f"target_type 必须是 {TARGET_TYPES.keys()} 之一")
    label, id_prop = TARGET_TYPES[target_type]
    watchlist_item_id = generate_watchlist_item_id()

    with driver.session() as session:
        # 校验目标存在
        check = session.run(
            f"MATCH (t:{label} {{`{id_prop}`: $tid}}) RETURN t LIMIT 1",
            tid=target_id).single()
        if not check:
            raise ValueError(f"目标 {target_type} {target_id} 不存在")

        # 创建关注项
        session.run("""
            CREATE (wi:WatchlistItem {
                watchlist_item_id: $wid, target_type: $ttype, target_id: $tid,
                reason: $reason, priority: $priority, owner_id: $owner,
                review_date: $review_date, status: 'active',
                created_at: datetime(), updated_at: datetime()
            })
        """, wid=watchlist_item_id, ttype=target_type, tid=target_id,
             reason=reason, priority=priority, owner=owner_id,
             review_date=review_date)

        # WATCHES 关系
        session.run(f"""
            MATCH (wi:WatchlistItem {{watchlist_item_id: $wid}})
            MATCH (t:{label} {{`{id_prop}`: $tid}})
            MERGE (wi)-[:WATCHES]->(t)
        """, wid=watchlist_item_id, tid=target_id)

        # 可选：DERIVED_FROM 简报
        if derived_from_brief_id:
            session.run("""
                MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
                MATCH (b)
                WHERE (b:DecisionBrief AND b.brief_id = $bid)
                   OR (b:IntelligenceProduct AND b.brief_id = $bid)
                MERGE (wi)-[:DERIVED_FROM]->(b)
            """, wid=watchlist_item_id, bid=derived_from_brief_id)

        write_audit_event(
            driver, action_type="CREATE",
            object_type="WatchlistItem", object_id=watchlist_item_id,
            actor_id=actor_id,
            delta={"target_type": target_type, "target_id": target_id,
                   "priority": priority},
            reason=f"加入关注项: {reason[:60]}",
        )
    return watchlist_item_id


def get_watchlist_item(driver, watchlist_item_id):
    """
    按 ID 查询关注项，附带目标节点与来源简报。
    """
    with driver.session() as session:
        r = session.run("""
            MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
            OPTIONAL MATCH (wi)-[:WATCHES]->(t)
            OPTIONAL MATCH (wi)-[:DERIVED_FROM]->(b)
            WHERE b IS NULL OR b:DecisionBrief OR b:IntelligenceProduct
            RETURN wi, labels(t)[0] AS target_label, t AS target_node,
                   b.brief_id AS brief_id
        """, wid=watchlist_item_id).single()
        if not r:
            return None
        data = dict(r["wi"])
        data["target_label"] = r["target_label"]
        data["target_node"] = dict(r["target_node"]) if r["target_node"] else None
        data["derived_from_brief_id"] = r["brief_id"]
        return data


def list_watchlist_items(driver, status=None, target_type=None, limit=50):
    """
    列出关注项（可按状态、目标类型过滤）。
    """
    filters = []
    params = {"limit": limit}
    if status:
        filters.append("wi.status = $status")
        params["status"] = status
    if target_type:
        filters.append("wi.target_type = $ttype")
        params["ttype"] = target_type
    where = " AND ".join(filters) if filters else "true"

    with driver.session() as session:
        r = session.run(f"""
            MATCH (wi:WatchlistItem)
            WHERE {where}
            OPTIONAL MATCH (wi)-[:WATCHES]->(t)
            RETURN wi.watchlist_item_id AS watchlist_item_id,
                   wi.target_type AS target_type, wi.target_id AS target_id,
                   wi.reason AS reason, wi.priority AS priority,
                   wi.owner_id AS owner_id, wi.review_date AS review_date,
                   wi.status AS status, wi.created_at AS created_at,
                   labels(t)[0] AS target_label,
                   coalesce(t.canonical_name, t.public_name, t.species, t.title, t.strategy_type, t.nct_id) AS target_name
            ORDER BY wi.priority DESC, wi.created_at DESC LIMIT $limit
        """, **params)
        return [dict(rec) for rec in r]


def close_watchlist_item(driver, watchlist_item_id, reason="", actor_id="system"):
    """
    关闭关注项（status → 'closed'）。
    """
    with driver.session() as session:
        check = session.run(
            "MATCH (wi:WatchlistItem {watchlist_item_id: $wid}) RETURN wi",
            wid=watchlist_item_id).single()
        if not check:
            raise ValueError(f"关注项 {watchlist_item_id} 不存在")
        session.run("""
            MATCH (wi:WatchlistItem {watchlist_item_id: $wid})
            SET wi.status = 'closed', wi.updated_at = datetime()
        """, wid=watchlist_item_id)
        write_audit_event(
            driver, action_type="STATUS_CHANGE",
            object_type="WatchlistItem", object_id=watchlist_item_id,
            actor_id=actor_id,
            delta={"status": {"before": "active", "after": "closed"}},
            reason=reason or f"关闭关注项 {watchlist_item_id}",
        )
        return True